"""Leakage-aware IPL auction price model trained on imported sale records."""
from datetime import datetime, timezone
import re
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.model_selection import GroupKFold
from sqlalchemy import select
from sqlalchemy.orm import Session
from scipy.optimize import lsq_linear

from app.analytics.auction_form import FORM_FEATURES, load_form_snapshots
from app.models.models import AuctionHistoryRecord, AuctionModelRun

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
