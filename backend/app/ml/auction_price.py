"""IPL auction price models.

Version 1 (``train_price_model`` / ``predict_team_bids``): the original
RandomForest trained on imported sale records with franchise one-hot features
and role-specific form adjusters, evaluated on one chronological split. It is
kept unchanged as a baseline and for backward compatibility.

Version 2 (below ``MODEL_FAMILY``): the successor used by Auction Intelligence.
Auction price / sale-probability model with leakage-free rolling backtests.

Target
    log(final price / season purse). Expressing price as a share of the
    per-franchise purse makes seasons with different purses comparable (a
    ₹10 cr buy meant more in 2018 than in 2026) without inventing an inflation
    index. Seasons whose purse is unknown are excluded from training.

Models
    * Price: scikit-learn HistGradientBoosting with quantile loss at
      q = 0.1 / 0.5 / 0.9 (native NaN handling — missing stays missing).
      Interval endpoints are conformally calibrated (CQR) on the most recent
      training season, so the 80% range is widened only by observed error.
    * Sale probability: HistGradientBoosting classifier trained on seasons
      that record unsold players (2021 partial, 2022, 2023 complete lists).

Leakage controls
    * Features for an auction are computed with ``as_of = auction date``
      (``app.auction.features``) — nothing on/after the auction date.
    * Prior price features use strictly earlier seasons only.
    * Rolling-origin backtest: to predict season S the model is trained only
      on seasons < S. Lots flagged ``conflict`` are excluded as targets.

Baselines (same rolling protocol)
    * base_price: predict the reserve price.
    * role_median: median prior-season share of purse by role × overseas × auction type.
    * performance_only: same learner restricted to on-field features.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.model_selection import GroupKFold
from sqlalchemy import delete, select
from sqlalchemy.orm import Session
from scipy.optimize import lsq_linear

from app.analytics.auction_form import FORM_FEATURES, load_form_snapshots
from app.auction.features import FEATURE_VERSION, get_features
from app.models.models import (
    AuctionBacktestPrediction, AuctionFranchiseSeason, AuctionHistoryRecord, AuctionLot, AuctionModelRun, AuctionSeason,
)

NUMERIC = ["auction_year", "base_price_lakh", "prior_price_lakh", "prior_auction_count"]
CATEGORICAL = ["role", "nationality", "franchise"]
FORM_ADJUSTMENT_FEATURES = {
    "Batter": ["form_bat_runs_per_match", "form_bat_average", "form_bat_strike_rate",
               "form_bat_consistency", "form_bat_high_score", "form_recent_trend",
               "form_opposition_strength", "form_sample_matches"],
    "Bowler": ["form_bowl_wickets_per_match", "form_bowl_economy", "form_bowl_average",
               "form_bowl_strike_rate", "form_bowl_consistency", "form_recent_trend",
               "form_opposition_strength", "form_sample_matches"],
    "All-Rounder": ["form_bat_runs_per_match", "form_bat_average", "form_bat_strike_rate",
                    "form_bat_consistency", "form_bat_high_score", "form_bowl_wickets_per_match",
                    "form_bowl_economy", "form_bowl_average", "form_bowl_strike_rate",
                    "form_bowl_consistency", "form_recent_trend", "form_opposition_strength",
                    "form_sample_matches"],
    "Wicketkeeper": ["form_bat_runs_per_match", "form_bat_average", "form_bat_strike_rate",
                     "form_bat_consistency", "form_bat_high_score", "form_keeper_stumpings_per_match",
                     "form_recent_trend", "form_opposition_strength", "form_sample_matches"],
}
FORM_NEGATIVE_FEATURES = {"form_bat_consistency", "form_bowl_economy", "form_bowl_average",
                          "form_bowl_strike_rate", "form_bowl_consistency"}
SOURCE_PRIORITY = {"outside-edge/ipl_auction": 0, "rixabhh/IPL-Auction-Analysis": 1}


def _norm(value):
    return re.sub(r"\s+", " ", str(value or "")).strip().casefold()


def _team_key(value):
    key = _norm(value)
    aliases = {
        "csk": "chennai super kings", "mi": "mumbai indians", "kkr": "kolkata knight riders",
        "rcb": "royal challengers bengaluru", "royal challengers bangalore": "royal challengers bengaluru",
        "rr": "rajasthan royals", "dc": "delhi capitals", "delhi daredevils": "delhi capitals",
        "srh": "sunrisers hyderabad", "pbks": "punjab kings", "kxip": "punjab kings",
        "kings xi punjab": "punjab kings", "dch": "deccan chargers", "dcp": "deccan chargers",
        "gl": "gujarat lions", "rps": "rising pune supergiant", "pwi": "pune warriors india",
        "gt": "gujarat titans", "lsg": "lucknow super giants",
    }
    return aliases.get(key, key)


def _role_key(value):
    key = _norm(value).replace("-", " ")
    if "keeper" in key or "wicket" in key:
        return "Wicketkeeper"
    if "all round" in key or "allround" in key:
        return "All-Rounder"
    if "bowl" in key:
        return "Bowler"
    if "bat" in key:
        return "Batter"
    return "Unknown"


def prepare_history(records, form_snapshots=None):
    rows = []
    for item in records:
        if item.status != "SOLD" or item.acquisition_type != "auction" or item.final_price_lakh is None:
            continue
        if float(item.final_price_lakh) <= 0:
            continue
        rows.append({
            "player_key": item.player_id or _norm(item.source_player_name),
            "player_name": item.source_player_name,
            "auction_year": int(item.auction_year),
            "base_price_lakh": float(item.base_price_lakh) if item.base_price_lakh is not None else np.nan,
            "final_price_lakh": float(item.final_price_lakh),
            "role": _role_key(item.role), "nationality": item.nationality or "Unknown",
            "franchise": _team_key(item.franchise_name), "acquisition_type": item.acquisition_type,
            "source_name": item.source_name,
        })
    if not rows:
        return pd.DataFrame()
    frame = pd.DataFrame(rows)
    frame["source_priority"] = frame["source_name"].map(SOURCE_PRIORITY).fillna(9)
    # Repositories overlap. Prefer the broader source when the same player-year-
    # franchise transaction appears in both, preserving conflicting records for audit.
    frame = frame.sort_values(["source_priority", "source_name"])
    frame = frame.drop_duplicates(["player_key", "auction_year", "franchise", "acquisition_type"], keep="first")
    frame = frame.sort_values(["player_key", "auction_year"]).reset_index(drop=True)
    frame["prior_price_lakh"] = np.nan
    frame["prior_auction_count"] = 0
    for _, group in frame.groupby("player_key", sort=False):
        previous, count = np.nan, 0
        for _, same_year in group.groupby("auction_year", sort=True):
            frame.loc[same_year.index, "prior_price_lakh"] = previous
            frame.loc[same_year.index, "prior_auction_count"] = count
            # Outcomes from this auction year become usable only for a later year.
            previous = float(same_year.iloc[-1]["final_price_lakh"])
            count += len(same_year)
    for feature in FORM_FEATURES:
        frame[feature] = np.nan
    for index, row in frame.iterrows():
        snapshot = (form_snapshots or {}).get((row.get("player_key"), int(row["auction_year"])), {})
        for feature in FORM_FEATURES:
            frame.at[index, feature] = snapshot.get(feature)
    return frame


def _pipeline():
    transform = ColumnTransformer([
        ("numeric", SimpleImputer(strategy="median", add_indicator=True), NUMERIC),
        ("categorical", Pipeline([
            ("fill", SimpleImputer(strategy="constant", fill_value="Unknown")),
            ("onehot", OneHotEncoder(handle_unknown="ignore")),
        ]), CATEGORICAL),
    ])
    return Pipeline([
        ("features", transform),
        ("model", RandomForestRegressor(n_estimators=300, min_samples_leaf=3,
                                        max_features=0.8, random_state=42, n_jobs=1)),
    ])


def _form_adjustment_frame(frame, role):
    columns = FORM_ADJUSTMENT_FEATURES.get(role, [])
    values = frame.reindex(columns=columns).copy()
    for column in FORM_NEGATIVE_FEATURES.intersection(columns):
        values[column] = -values[column]
    return values


class PositiveResidualRegressor:
    """Small regularized least-squares model with non-negative form effects."""
    def __init__(self, alpha=5.0):
        self.alpha = float(alpha)
        self.imputer = SimpleImputer(strategy="median")
        self.scaler = StandardScaler()

    def fit(self, values, target):
        matrix = self.scaler.fit_transform(self.imputer.fit_transform(values))
        self.lower_bounds_ = np.nanmin(matrix, axis=0)
        self.upper_bounds_ = np.nanmax(matrix, axis=0)
        target = np.asarray(target, dtype=float)
        self.intercept_ = float(np.mean(target))
        centered = target - self.intercept_
        ridge = np.sqrt(self.alpha) * np.eye(matrix.shape[1])
        solution = lsq_linear(np.vstack((matrix, ridge)),
                              np.concatenate((centered, np.zeros(matrix.shape[1]))),
                              bounds=(0.0, np.inf), method="bvls", tol=1e-8)
        self.coef_ = solution.x
        return self

    def predict(self, values):
        matrix = self.scaler.transform(self.imputer.transform(values))
        # Keep live form snapshots inside the training distribution. This is
        # data-derived clipping and avoids unstable extrapolation for tiny samples.
        matrix = np.nan_to_num(matrix, nan=0.0, posinf=0.0, neginf=0.0)
        matrix = np.minimum(np.maximum(matrix, self.lower_bounds_), self.upper_bounds_)
        return np.sum(matrix * self.coef_[None, :], axis=1) + self.intercept_


def _fit_form_adjusters(frame, residuals):
    """Fit positive-direction, role-specific log-price residual models.

    Positive constraints encode only the direction of a quality feature (e.g.
    lower economy is better); coefficient sizes are learned from sale records.
    """
    adjusters = {}
    eligible = frame["form_sample_matches"].fillna(0) >= 3
    for role, columns in FORM_ADJUSTMENT_FEATURES.items():
        mask = eligible & (frame["role"] == role)
        if int(mask.sum()) < 20:
            continue
        model = PositiveResidualRegressor(alpha=5.0)
        model.fit(_form_adjustment_frame(frame.loc[mask], role), residuals[mask.to_numpy()])
        adjusters[role] = model
    return adjusters


def _predict_form_adjustments(frame, adjusters):
    adjustments = np.zeros(len(frame), dtype=float)
    roles = frame["role"].tolist()
    for role, model in adjusters.items():
        indexes = [index for index, value in enumerate(roles) if value == role
                   and float(frame.iloc[index].get("form_sample_matches") or 0) >= 3]
        if indexes:
            values = _form_adjustment_frame(frame.iloc[indexes], role)
            adjustments[indexes] = model.predict(values)
    return adjustments


def _out_of_fold_predictions(frame, target, features):
    predictions = np.zeros(len(frame), dtype=float)
    splitter = GroupKFold(n_splits=3)
    for train_indexes, hold_indexes in splitter.split(frame, target, groups=frame["player_key"]):
        model = _pipeline()
        model.fit(frame.iloc[train_indexes][features], target[train_indexes])
        predictions[hold_indexes] = model.predict(frame.iloc[hold_indexes][features])
    return predictions


def train_price_model(db: Session):
    records = db.scalars(select(AuctionHistoryRecord).order_by(AuctionHistoryRecord.auction_year)).all()
    raw_sale_rows = sum(1 for row in records if row.status == "SOLD" and row.acquisition_type == "auction"
                        and row.final_price_lakh is not None and float(row.final_price_lakh) > 0)
    linked = {(row.player_id, int(row.auction_year), _role_key(row.role))
              for row in records if row.player_id and row.status == "SOLD"
              and row.acquisition_type == "auction" and row.final_price_lakh is not None
              and float(row.final_price_lakh) > 0}
    snapshots = load_form_snapshots(db, linked)
    frame = prepare_history(records, snapshots)
    if len(frame) < 50 or frame["auction_year"].nunique() < 5:
        raise ValueError("At least 50 sold auction records across 5 auction years are required for training")
    years = sorted(frame["auction_year"].unique())
    cutoff = years[max(1, int(len(years) * 0.8))]
    train = frame[frame.auction_year < cutoff]
    validation = frame[frame.auction_year >= cutoff]
    if len(train) < 30 or len(validation) < 10:
        raise ValueError("Chronological evaluation needs at least 30 training and 10 validation transactions")
    features = NUMERIC + CATEGORICAL
    y_train = np.log1p(train.final_price_lakh.to_numpy(dtype=float))
    eval_model = _pipeline()
    eval_model.fit(train[features], y_train)
    train_oof = _out_of_fold_predictions(train, y_train, features)
    eval_adjusters = _fit_form_adjusters(train, y_train - train_oof)
    validation_base_log = eval_model.predict(validation[features])
    validation_adjustment = _predict_form_adjustments(validation, eval_adjusters)
    prediction = np.maximum(np.expm1(validation_base_log + validation_adjustment), 0)
    core_prediction = np.maximum(np.expm1(validation_base_log), 0)
    actual = validation.final_price_lakh.to_numpy(dtype=float)
    baseline = np.repeat(float(train.final_price_lakh.median()), len(actual))
    evaluation = {
        "target": "final auction price for sold auction acquisitions",
        "price_unit": "INR lakh",
        "validation_method": "chronological holdout; training years strictly before validation_start_year",
        "validation_start_year": int(cutoff),
        "validation_years": sorted(int(y) for y in validation.auction_year.unique()),
        "mae_lakh": round(float(mean_absolute_error(actual, prediction)), 3),
        "rmse_lakh": round(float(np.sqrt(mean_squared_error(actual, prediction))), 3),
        "r2": round(float(r2_score(actual, prediction)), 4) if len(actual) > 1 else None,
        "core_model_mae_lakh": round(float(mean_absolute_error(actual, core_prediction)), 3),
        "form_adjusted_validation_rows": int(sum(1 for value in validation_adjustment if value != 0)),
        "form_adjuster_roles": sorted(eval_adjusters.keys()),
        "baseline_median_mae_lakh": round(float(mean_absolute_error(actual, baseline)), 3),
        "baseline_median_rmse_lakh": round(float(np.sqrt(mean_squared_error(actual, baseline))), 3),
        "deduplicated_rows": int(len(frame)),
        "source_rows_used": int(raw_sale_rows),
        "duplicates_removed": int(raw_sale_rows - len(frame)),
        "training_years": sorted(int(y) for y in train.auction_year.unique()),
        "records_by_role": {str(k): int(v) for k, v in frame.role.value_counts().items()},
        "records_by_franchise": {str(k): int(v) for k, v in frame.franchise.value_counts().items()},
        "linked_form_snapshots": int((frame["form_sample_matches"] >= 3).sum()),
        "form_feature_coverage": {feature: int(frame[feature].notna().sum()) for feature in FORM_FEATURES},
    }
    all_target = np.log1p(frame.final_price_lakh.to_numpy(dtype=float))
    all_oof = _out_of_fold_predictions(frame, all_target, features)
    form_adjusters = _fit_form_adjusters(frame, all_target - all_oof)
    model = _pipeline()
    model.fit(frame[features], all_target)
    model_version = "ipl-auction-price-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    artifact_dir = Path(__file__).resolve().parents[2] / "artifacts" / "auction"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = artifact_dir / (model_version + ".joblib")
    joblib.dump({"pipeline": model, "features": features, "target_transform": "log1p",
                 "form_adjusters": form_adjusters, "form_features": FORM_FEATURES,
                 "model_version": model_version, "currency_unit": "INR lakh"}, artifact_path)
    run = AuctionModelRun(task="price_regression", model_version=model_version,
                          training_rows=len(frame), validation_rows=len(validation),
                          evaluation_json=evaluation,
                          feature_schema_json={"numeric": NUMERIC, "categorical": CATEGORICAL,
                                               "leakage_controls": ["same-year price excluded",
                                                                     "recent form uses matches before auction year",
                                                                     "prior price uses strictly earlier auction years"],
                                               "form_features": FORM_FEATURES,
                                               "form_adjustment": "role-specific positive-constrained regression learned from out-of-fold historical price residuals",
                                               "form_weighting": "12 most recent appearances; exponential one-year half-life; franchise T20, T20I, domestic T20, ODI and multi-day formats receive descending relevance weights"},
                          artifact_path=str(artifact_path.relative_to(Path(__file__).resolve().parents[2])))
    db.add(run)
    db.commit()
    return run


def role_key(value):
    key = _norm(value).replace("-", " ").replace("_", " ")
    if "keeper" in key or "wicket" in key:
        return "Wicketkeeper"
    if "all round" in key or "allround" in key:
        return "All-Rounder"
    if "bowl" in key:
        return "Bowler"
    if "batt" in key or "bat" in key:
        return "Batter"
    return "Unknown"


def predict_team_bids(model_payload, candidates):
    """Batch-predict INR lakh sale prices for team/player candidate rows."""
    frame = pd.DataFrame([{
        "auction_year": row["auction_year"],
        "base_price_lakh": row["base_price_lakh"],
        "prior_price_lakh": row["prior_price_lakh"],
        "prior_auction_count": row["prior_auction_count"],
        "role": _role_key(row["role"]),
        "nationality": row["nationality"] or "Unknown",
        "franchise": _team_key(row["franchise"]),
        **{feature: row.get(feature) for feature in FORM_FEATURES},
    } for row in candidates])
    if frame.empty:
        return []
    log_values = model_payload["pipeline"].predict(frame[model_payload["features"]])
    adjusters = model_payload.get("form_adjusters") or {}
    if adjusters:
        log_values = log_values + _predict_form_adjustments(frame, adjusters)
    values = np.maximum(np.expm1(log_values), 0)
    return [float(value) for value in values]


# ==========================================================================
# Version 2
# ==========================================================================

MODEL_FAMILY = "auction-v2"
ARTIFACT_DIR = Path(__file__).resolve().parents[2] / "artifacts" / "auction"
QUANTILES = (0.1, 0.5, 0.9)
MIN_TRAIN_SEASON = 2014

PERF_FEATURES = [
    "bat_sr_eq", "bat_avg_eq", "bat_boundary_pct", "bat_dot_pct", "bat_runs_per_inns", "bat_death_sr",
    "bat_pp_sr", "bat_mid_sr", "bat_evidence_balls", "pos_top_share", "pos_lower_share",
    "bowl_econ_eq", "bowl_sr_eq", "bowl_dot_pct", "bowl_wkts_per_inns", "bowl_death_econ", "bowl_pp_econ",
    "bowl_evidence_balls", "bowl_death_share", "bowl_balls_per_inns",
    "ipl_matches_career", "t20_matches_career", "t20_career_years", "days_since_ipl", "days_since_t20",
    "stumpings_window", "ipl_share_of_evidence",
]
MARKET_FEATURES = [
    "base_share", "prior_price_share", "prior_retained_share", "seasons_since_prior", "prior_count",
    "is_overseas", "is_capped", "is_mega", "is_marquee", "role_bat", "role_bowl", "role_ar", "role_wk",
    "is_pace", "is_spin", "market_liquidity", "age_at_auction",
]
ALL_FEATURES = PERF_FEATURES + MARKET_FEATURES


# --------------------------------------------------------------------------
# Dataset construction
# --------------------------------------------------------------------------

def _season_meta(db: Session) -> Dict[int, AuctionSeason]:
    return {s.season: s for s in db.scalars(select(AuctionSeason)).all()}


def _liquidity(db: Session) -> Dict[int, float]:
    """Pre-auction purse available per open squad slot (lakh), where known."""
    rows = db.scalars(select(AuctionFranchiseSeason)).all()
    by = defaultdict(list)
    for r in rows:
        by[r.season].append(r)
    out = {}
    for season, rs in by.items():
        if all(r.purse_before_auction_lakh is not None and r.slots_left for r in rs) and len(rs) >= 8:
            out[season] = sum(float(r.purse_before_auction_lakh) for r in rs) / max(1, sum(r.slots_left for r in rs))
    return out


def _prior_prices(lots: List[AuctionLot]) -> Dict[Tuple[str, int], dict]:
    """For each (player, season): latest strictly-earlier sale and retention price."""
    by_player = defaultdict(list)
    for lot in lots:
        if lot.player_id and lot.status in ("SOLD", "RETAINED") and lot.final_price_lakh is not None:
            by_player[lot.player_id].append(lot)
    out = {}
    for pid, items in by_player.items():
        items.sort(key=lambda l: l.season)
        seasons = sorted({l.season for l in lots if l.player_id == pid})
        for s in seasons:
            earlier = [l for l in items if l.season < s]
            sold = [l for l in earlier if l.status == "SOLD"]
            ret = [l for l in earlier if l.status == "RETAINED"]
            out[(pid, s)] = {
                "prior_sold": sold[-1] if sold else None,
                "prior_retained": ret[-1] if ret else None,
                "count": len(earlier),
            }
    return out


def build_frame(db: Session, seasons: Optional[List[int]] = None, include_retained: bool = False) -> pd.DataFrame:
    meta = _season_meta(db)
    all_lots = db.scalars(select(AuctionLot)).all()
    priors = _prior_prices(all_lots)
    liquidity = _liquidity(db)
    purse_by_season = {s: float(m.purse_lakh) for s, m in meta.items() if m.purse_lakh}
    target_lots = [l for l in all_lots if (seasons is None or l.season in seasons)
                   and (include_retained or l.acquisition_type == "auction")]
    feats_by_season = {}
    for season in sorted({l.season for l in target_lots}):
        m = meta.get(season)
        if not m or not m.auction_date:
            continue
        ids = [l.player_id for l in target_lots if l.season == season and l.player_id]
        feats_by_season[season] = get_features(db, ids, m.auction_date)
    rows = []
    for lot in target_lots:
        m = meta.get(lot.season)
        purse = purse_by_season.get(lot.season)
        feats = feats_by_season.get(lot.season, {}).get(lot.player_id, {}) if lot.player_id else {}
        prior = priors.get((lot.player_id, lot.season), {}) if lot.player_id else {}
        ps, pr = prior.get("prior_sold"), prior.get("prior_retained")
        row = {
            "lot_id": lot.id, "season": lot.season, "player_id": lot.player_id, "player_name": lot.player_name,
            "status": lot.status, "franchise": lot.franchise, "verification": lot.verification,
            "price_lakh": float(lot.final_price_lakh) if lot.final_price_lakh is not None else np.nan,
            "base_lakh": float(lot.base_price_lakh) if lot.base_price_lakh is not None else np.nan,
            "purse_lakh": purse if purse else np.nan, "role": lot.role or "UNK",
            "overseas": lot.overseas, "set_code": lot.set_code,
        }
        for k in PERF_FEATURES:
            v = feats.get(k)
            row[k] = float(v) if v is not None else np.nan
        row["base_share"] = row["base_lakh"] / purse if purse and not math.isnan(row["base_lakh"]) else np.nan
        row["prior_price_share"] = (float(ps.final_price_lakh) / purse_by_season[ps.season]
                                    if ps and purse_by_season.get(ps.season) else np.nan)
        row["prior_retained_share"] = (float(pr.final_price_lakh) / purse_by_season[pr.season]
                                       if pr and purse_by_season.get(pr.season) else np.nan)
        latest = max([x.season for x in (ps, pr) if x], default=None)
        row["seasons_since_prior"] = lot.season - latest if latest else np.nan
        row["prior_count"] = float(prior.get("count", 0))
        row["is_overseas"] = np.nan if lot.overseas is None else float(lot.overseas)
        row["is_capped"] = np.nan if lot.capped is None else float(lot.capped)
        row["is_mega"] = float(bool(m and m.auction_type == "MEGA"))
        row["is_marquee"] = float(bool(lot.set_code and lot.set_code.upper().startswith("M")
                                       and lot.set_code[1:].isdigit()))
        for r in ("bat", "bowl", "ar", "wk"):
            row[f"role_{r}"] = np.nan if not lot.role else float(lot.role.lower() == r)
        row["is_pace"] = np.nan if not lot.bowling_kind else float(lot.bowling_kind == "pace")
        row["is_spin"] = np.nan if not lot.bowling_kind else float(lot.bowling_kind == "spin")
        row["market_liquidity"] = liquidity.get(lot.season, np.nan) / purse if purse and lot.season in liquidity else np.nan
        row["age_at_auction"] = float(lot.age_at_auction) if lot.age_at_auction else np.nan
        rows.append(row)
    frame = pd.DataFrame(rows)
    if not frame.empty:
        frame["target"] = np.log(frame["price_lakh"] / frame["purse_lakh"])
    return frame


# --------------------------------------------------------------------------
# Fitting
# --------------------------------------------------------------------------

def _hgb_quantile(q: float, seed: int = 7) -> HistGradientBoostingRegressor:
    return HistGradientBoostingRegressor(loss="quantile", quantile=q, max_iter=300, learning_rate=0.05,
                                         max_leaf_nodes=15, min_samples_leaf=15, l2_regularization=1.0,
                                         random_state=seed)


class PriceModel:
    def __init__(self, features: List[str]):
        self.features = features
        self.models = {}
        self.cqr_adjust = 0.0
        self.calibration_season = None

    def fit(self, train: pd.DataFrame) -> "PriceModel":
        seasons = sorted(train.season.unique())
        # Conformalised quantile regression: fit on all but the latest season,
        # measure interval misses on the latest, then refit on everything.
        if len(seasons) >= 3:
            cal_season = seasons[-1]
            fit_part, cal = train[train.season < cal_season], train[train.season == cal_season]
            if len(cal) >= 20 and len(fit_part) >= 100:
                lo = _hgb_quantile(0.1).fit(fit_part[self.features], fit_part.target)
                hi = _hgb_quantile(0.9).fit(fit_part[self.features], fit_part.target)
                scores = np.maximum(lo.predict(cal[self.features]) - cal.target,
                                    cal.target - hi.predict(cal[self.features]))
                n = len(scores)
                level = min(1.0, math.ceil((n + 1) * 0.8) / n)
                self.cqr_adjust = float(max(0.0, np.quantile(scores, level)))
                self.calibration_season = int(cal_season)
        for q in QUANTILES:
            self.models[q] = _hgb_quantile(q).fit(train[self.features], train.target)
        return self

    def predict(self, frame: pd.DataFrame) -> pd.DataFrame:
        X = frame[self.features]
        out = pd.DataFrame(index=frame.index)
        p10 = self.models[0.1].predict(X) - self.cqr_adjust
        p50 = self.models[0.5].predict(X)
        p90 = self.models[0.9].predict(X) + self.cqr_adjust
        stacked = np.sort(np.vstack([p10, p50, p90]), axis=0)  # guard quantile crossing
        for name, vals in zip(("p10", "p50", "p90"), stacked):
            out[name] = np.exp(vals) * frame["purse_lakh"].to_numpy()
        # A sale can never close below the reserve.
        base = frame["base_lakh"].to_numpy()
        for col in ("p10", "p50", "p90"):
            out[col] = np.where(np.isnan(base), out[col], np.maximum(out[col], base))
        return out


def fit_sale_classifier(frame: pd.DataFrame):
    """Regularised logistic regression on standardised features (ranking model).

    Probabilities are later prior-shifted to the auction's expected sale rate,
    because training seasons record unsold players unevenly (2021 is partial)."""
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    data = frame[frame.status.isin(["SOLD", "UNSOLD"])]
    if data.status.nunique() < 2 or (data.status == "UNSOLD").sum() < 30:
        return None
    clf = make_pipeline(SimpleImputer(strategy="median", add_indicator=True, keep_empty_features=True),
                        StandardScaler(), LogisticRegression(C=0.3, max_iter=3000))
    with np.errstate(all="ignore"):
        clf.fit(data[ALL_FEATURES], (data.status == "SOLD").astype(int))
    return clf


def sale_probabilities(clf, frame: pd.DataFrame, expected_rate: Optional[float]) -> np.ndarray:
    with np.errstate(all="ignore"):
        p = clf.predict_proba(frame[ALL_FEATURES])[:, 1]
    if expected_rate is None or not (0 < expected_rate < 1) or not len(p):
        return p
    # Prior shift: move the logit intercept until the mean probability equals
    # the expected sale rate (open squad slots / players in the pool).
    logit = np.log(np.clip(p, 1e-6, 1 - 1e-6) / (1 - np.clip(p, 1e-6, 1 - 1e-6)))
    lo, hi = -15.0, 15.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if np.mean(1 / (1 + np.exp(-(logit + mid)))) > expected_rate:
            hi = mid
        else:
            lo = mid
    return 1 / (1 + np.exp(-(logit + (lo + hi) / 2)))


def expected_sale_rate(db: Session, season: int, pool_size: Optional[int] = None) -> Tuple[Optional[float], str]:
    """Open squad slots ÷ pool size — both known before an auction when recorded."""
    meta = db.get(AuctionSeason, season)
    rows = db.scalars(select(AuctionFranchiseSeason).where(AuctionFranchiseSeason.season == season)).all()
    slots = sum(r.slots_left for r in rows if r.slots_left) if rows and all(r.slots_left for r in rows) else None
    pool = pool_size or ((meta.rule_sources or {}).get("pool_size_reported") if meta else None)
    if slots and pool:
        return min(0.95, slots / pool), f"{slots} open slots / {pool} players in pool"
    return None, "expected sale rate unknown (slots or pool size not recorded); probabilities uncalibrated"


# --------------------------------------------------------------------------
# Metrics
# --------------------------------------------------------------------------

def price_metrics(actual: np.ndarray, pred: np.ndarray, lo: Optional[np.ndarray] = None,
                  hi: Optional[np.ndarray] = None) -> Dict:
    actual, pred = np.asarray(actual, float), np.asarray(pred, float)
    mask = ~np.isnan(actual) & ~np.isnan(pred)
    a, p = actual[mask], pred[mask]
    if not len(a):
        return {"n": 0}
    out = {
        "n": int(len(a)),
        "mae_lakh": round(float(np.mean(np.abs(a - p))), 2),
        "rmse_lakh": round(float(np.sqrt(np.mean((a - p) ** 2))), 2),
        "median_ae_lakh": round(float(np.median(np.abs(a - p))), 2),
        # MAPE is only meaningful with strictly positive targets (all sale prices are).
        "mape_pct": round(float(np.mean(np.abs(a - p) / a) * 100), 1),
        "bias_lakh": round(float(np.mean(p - a)), 2),
        "log_mae": round(float(np.mean(np.abs(np.log(a) - np.log(np.maximum(p, 1e-6))))), 4),
    }
    if lo is not None and hi is not None:
        lo, hi = np.asarray(lo, float)[mask], np.asarray(hi, float)[mask]
        out["coverage_80"] = round(float(np.mean((a >= lo) & (a <= hi))), 3)
        out["mean_interval_width_lakh"] = round(float(np.mean(hi - lo)), 2)
    return out


def classification_metrics(actual_sold: np.ndarray, prob: np.ndarray, threshold: float = 0.5) -> Dict:
    y = np.asarray(actual_sold, int)
    pred = (np.asarray(prob) >= threshold).astype(int)
    tp = int(((pred == 1) & (y == 1)).sum()); fp = int(((pred == 1) & (y == 0)).sum())
    fn = int(((pred == 0) & (y == 1)).sum()); tn = int(((pred == 0) & (y == 0)).sum())
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = 2 * precision * recall / (precision + recall) if precision and recall else None
    # Unsold is the minority/harder class; report it too.
    up = tn / (tn + fn) if tn + fn else None
    ur = tn / (tn + fp) if tn + fp else None
    brier = float(np.mean((np.asarray(prob) - y) ** 2)) if len(y) else None
    return {"n": int(len(y)), "sold_precision": _r(precision), "sold_recall": _r(recall), "sold_f1": _r(f1),
            "unsold_precision": _r(up), "unsold_recall": _r(ur), "accuracy": _r((tp + tn) / len(y) if len(y) else None),
            "brier": _r(brier), "base_rate_sold": _r(float(y.mean()) if len(y) else None),
            "confusion": {"tp": tp, "fp": fp, "fn": fn, "tn": tn}}


def _r(v, d=3):
    return round(v, d) if v is not None else None


# --------------------------------------------------------------------------
# Baselines
# --------------------------------------------------------------------------

def role_median_baseline(train: pd.DataFrame, test: pd.DataFrame) -> np.ndarray:
    key = lambda df: df["role"].astype(str) + "|" + df["is_overseas"].astype(str) + "|" + df["is_mega"].astype(str)
    shares = train.assign(k=key(train), share=np.exp(train.target)).groupby("k")["share"].median()
    overall = float(np.exp(train.target).median())
    s = key(test).map(shares).fillna(overall).to_numpy()
    out = s * test["purse_lakh"].to_numpy()
    base = test["base_lakh"].to_numpy()
    return np.where(np.isnan(base), out, np.maximum(out, base))


# --------------------------------------------------------------------------
# Backtest + training entry points
# --------------------------------------------------------------------------

def _version(frame: pd.DataFrame) -> str:
    digest = hashlib.sha1(json.dumps({"features": ALL_FEATURES, "fv": FEATURE_VERSION,
                                      "rows": int(len(frame))}, sort_keys=True).encode()).hexdigest()[:6]
    return f"{MODEL_FAMILY}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}-{digest}"


def run_backtest(db: Session, first_test_season: int = 2018, persist: bool = True) -> Dict:
    frame = build_frame(db)
    sold = frame[(frame.status == "SOLD") & frame.price_lakh.notna() & frame.purse_lakh.notna()
                 & (frame.verification != "conflict") & (frame.season >= MIN_TRAIN_SEASON)]
    version = _version(frame)
    seasons = sorted(s for s in sold.season.unique() if s >= first_test_season)
    per_season, all_rows = [], []
    for s in seasons:
        train, test = sold[sold.season < s], sold[sold.season == s]
        if len(train) < 150 or len(test) < 20:
            continue
        model = PriceModel(ALL_FEATURES).fit(train)
        pred = model.predict(test)
        perf = PriceModel(PERF_FEATURES).fit(train).predict(test)["p50"].to_numpy()
        rmed = role_median_baseline(train, test)
        base = test["base_lakh"].to_numpy()
        actual = test["price_lakh"].to_numpy()
        entry = {"season": int(s), "train_seasons": sorted(int(x) for x in train.season.unique()),
                 "calibration_season": model.calibration_season, "cqr_log_adjust": round(model.cqr_adjust, 4),
                 "cpi": price_metrics(actual, pred.p50.to_numpy(), pred.p10.to_numpy(), pred.p90.to_numpy()),
                 "baseline_role_median": price_metrics(actual, rmed),
                 "baseline_performance_only": price_metrics(actual, perf),
                 "baseline_base_price": price_metrics(actual, base),
                 "base_price_known_rows": int(np.sum(~np.isnan(base)))}
        # Like-for-like comparison on rows where the base price is known.
        known = ~np.isnan(base)
        if known.sum() >= 15:
            entry["cpi_on_base_known_rows"] = price_metrics(actual[known], pred.p50.to_numpy()[known])
        per_season.append(entry)
        for (idx, row), p10, p50, p90, rm, pf in zip(test.iterrows(), pred.p10, pred.p50, pred.p90, rmed, perf):
            all_rows.append({"season": int(s), "lot_id": row.lot_id, "player_id": row.player_id,
                             "actual_status": row.status, "actual_price_lakh": row.price_lakh,
                             "actual_franchise": row.franchise, "p10": p10, "p50": p50, "p90": p90,
                             "baselines": {"role_median": round(float(rm), 2), "performance_only": round(float(pf), 2),
                                           "base_price": None if math.isnan(row.base_lakh) else row.base_lakh},
                             "role": row.role, "overseas": None if pd.isna(row.is_overseas) else bool(row.is_overseas)})

    # Sale-probability backtest: only seasons with recorded unsold players.
    cls_frame = frame[frame.status.isin(["SOLD", "UNSOLD"]) & (frame.season >= 2021)]
    classification = []
    for s in sorted(cls_frame[cls_frame.status == "UNSOLD"].season.unique()):
        train = cls_frame[cls_frame.season < s]
        test = cls_frame[cls_frame.season == s]
        clf = fit_sale_classifier(train)
        if clf is None:
            classification.append({"season": int(s), "skipped": "insufficient earlier seasons with unsold records"})
            continue
        rate, rate_basis = expected_sale_rate(db, int(s), pool_size=int(len(test)))
        prob = sale_probabilities(clf, test, rate)
        y = (test.status == "SOLD").to_numpy().astype(int)
        from sklearn.metrics import roc_auc_score
        k = int(y.sum())
        top_k = np.argsort(-prob)[:k]
        classification.append({"season": int(s), "expected_rate_basis": rate_basis,
                               **classification_metrics(y, prob),
                               "auc": round(float(roc_auc_score(y, prob)), 3),
                               "top_k_precision": round(float(y[top_k].mean()), 3) if k else None,
                               "majority_class_accuracy": round(float(max(y.mean(), 1 - y.mean())), 3),
                               "majority_class_brier": round(float(y.mean() * (1 - y.mean())), 3)})
        sold_prob = dict(zip(test.lot_id, prob))
        for r in all_rows:
            if r["season"] == s and r["lot_id"] in sold_prob:
                r["sold_probability"] = float(sold_prob[r["lot_id"]])
        for lot_id, status, pr in zip(test.lot_id, test.status, prob):
            if status == "UNSOLD":
                all_rows.append({"season": int(s), "lot_id": lot_id, "player_id": None, "actual_status": "UNSOLD",
                                 "actual_price_lakh": None, "actual_franchise": None, "p10": None, "p50": None,
                                 "p90": None, "baselines": {}, "sold_probability": float(pr)})

    pooled = pd.DataFrame([r for r in all_rows if r["actual_status"] == "SOLD"])
    summary = {}
    if not pooled.empty:
        summary["cpi"] = price_metrics(pooled.actual_price_lakh, pooled.p50, pooled.p10, pooled.p90)
        summary["baseline_role_median"] = price_metrics(pooled.actual_price_lakh, pooled.baselines.map(lambda b: b["role_median"]))
        summary["baseline_performance_only"] = price_metrics(pooled.actual_price_lakh, pooled.baselines.map(lambda b: b["performance_only"]))
        bp = pooled.baselines.map(lambda b: b["base_price"]).astype(float)
        summary["baseline_base_price"] = price_metrics(pooled.actual_price_lakh, bp)
        known = bp.notna()
        summary["cpi_on_base_known_rows"] = price_metrics(pooled.actual_price_lakh[known], pooled.p50[known])
        summary["by_role"] = {str(r): price_metrics(g.actual_price_lakh, g.p50, g.p10, g.p90)
                              for r, g in pooled.groupby("role")}
        summary["by_overseas"] = {str(k): price_metrics(g.actual_price_lakh, g.p50, g.p10, g.p90)
                                  for k, g in pooled.groupby(pooled.overseas.astype(str))}
        summary["by_franchise"] = {str(k): price_metrics(g.actual_price_lakh, g.p50, g.p10, g.p90)
                                   for k, g in pooled.groupby("actual_franchise")}
        # Error diagnostics for model improvement (signed log error by segment).
        pooled["log_err"] = np.log(np.maximum(pooled.p50, 1)) - np.log(pooled.actual_price_lakh)
        diag = []
        for col in ("role", "overseas"):
            for k, g in pooled.groupby(pooled[col].astype(str)):
                if len(g) >= 25:
                    diag.append({"segment": f"{col}={k}", "n": int(len(g)),
                                 "median_log_error": round(float(g.log_err.median()), 3),
                                 "direction": "over-predicts" if g.log_err.median() > 0.1 else
                                 "under-predicts" if g.log_err.median() < -0.1 else "unbiased"})
        summary["error_diagnostics"] = diag
        cpi_mae = summary["cpi"]["mae_lakh"]
        summary["beats_baselines"] = {k: (cpi_mae < summary[k]["mae_lakh"]) for k in
                                      ("baseline_role_median", "baseline_performance_only") if summary[k].get("n")}
        if summary["cpi_on_base_known_rows"].get("n"):
            summary["beats_baselines"]["baseline_base_price"] = \
                summary["cpi_on_base_known_rows"]["mae_lakh"] < summary["baseline_base_price"]["mae_lakh"]

    evaluation = {"protocol": "rolling-origin: train on seasons < S, test on S; features as-of auction date",
                  "target": "log(final price / season purse); reported in INR lakh",
                  "excluded": "lots with conflicting source prices; seasons with unknown purse (pre-2014)",
                  "per_season": per_season, "pooled": summary, "classification": classification,
                  "feature_version": FEATURE_VERSION, "features": ALL_FEATURES}
    if persist:
        db.execute(delete(AuctionBacktestPrediction).where(AuctionBacktestPrediction.model_version == version))
        for r in all_rows:
            db.add(AuctionBacktestPrediction(
                model_version=version, season=r["season"], lot_id=r["lot_id"], player_id=r.get("player_id"),
                actual_status=r["actual_status"],
                actual_price_lakh=None if r.get("actual_price_lakh") is None or pd.isna(r["actual_price_lakh"]) else r["actual_price_lakh"],
                actual_franchise=r.get("actual_franchise"),
                p10_lakh=_num(r.get("p10")), p50_lakh=_num(r.get("p50")), p90_lakh=_num(r.get("p90")),
                sold_probability=r.get("sold_probability"), baselines=r.get("baselines", {}),
                details={"role": r.get("role"), "overseas": r.get("overseas")}))
        db.add(AuctionModelRun(task="v2_backtest", model_version=version,
                               training_rows=int(len(sold)), validation_rows=int(len(pooled)),
                               evaluation_json=_jsonable(evaluation),
                               feature_schema_json={"features": ALL_FEATURES, "feature_version": FEATURE_VERSION},
                               artifact_path="(backtest only)"))
        db.commit()
    return {"model_version": version, **_jsonable(evaluation)}


def train_production(db: Session) -> Dict:
    """Fit on every eligible season and persist the artifact used for live valuation."""
    frame = build_frame(db)
    sold = frame[(frame.status == "SOLD") & frame.price_lakh.notna() & frame.purse_lakh.notna()
                 & (frame.verification != "conflict") & (frame.season >= MIN_TRAIN_SEASON)]
    model = PriceModel(ALL_FEATURES).fit(sold)
    clf = fit_sale_classifier(frame[frame.status.isin(["SOLD", "UNSOLD"]) & (frame.season >= 2021)])
    version = _version(frame)
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    path = ARTIFACT_DIR / f"{version}.joblib"
    joblib.dump({"price": model, "sale": clf, "features": ALL_FEATURES, "version": version,
                 "feature_version": FEATURE_VERSION}, path)
    run = AuctionModelRun(task="v2_price", model_version=version, training_rows=int(len(sold)), validation_rows=0,
                          evaluation_json={"training_seasons": sorted(int(s) for s in sold.season.unique()),
                                           "cqr_log_adjust": model.cqr_adjust,
                                           "calibration_season": model.calibration_season,
                                           "sale_classifier": clf is not None},
                          feature_schema_json={"features": ALL_FEATURES, "feature_version": FEATURE_VERSION},
                          artifact_path=str(path.relative_to(ARTIFACT_DIR.parents[1])))
    db.add(run)
    db.commit()
    return {"model_version": version, "training_rows": int(len(sold))}


_MODEL_CACHE: Dict[str, dict] = {}


def load_production(db: Session) -> Optional[dict]:
    run = db.scalar(select(AuctionModelRun).where(AuctionModelRun.task == "v2_price")
                    .order_by(AuctionModelRun.created_at.desc()))
    if not run:
        return None
    if run.model_version not in _MODEL_CACHE:
        path = ARTIFACT_DIR.parents[1] / run.artifact_path
        if not path.exists():
            return None
        _MODEL_CACHE.clear()
        _MODEL_CACHE[run.model_version] = {**joblib.load(path), "run": run}
    return _MODEL_CACHE[run.model_version]


def _num(v):
    return None if v is None or (isinstance(v, float) and math.isnan(v)) else round(float(v), 2)


def _jsonable(obj):
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return None if math.isnan(obj) else float(obj)
    if isinstance(obj, float) and math.isnan(obj):
        return None
    return obj
