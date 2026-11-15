"""Match-state reconstruction and feature engineering (batting-team perspective).

Every probability produced by v2 is the chance that the **batting side** wins
(limited overs) or the (batting win, bowling win, draw) distribution (multi-day).
Callers convert to team1/team2 with ``batting_is_team1`` at the very end, so the
orientation is decided in exactly one place (``orient_to_team1``).

States are *pre-delivery*: they include everything that happened before the
ball is bowled and nothing after it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from .constants import FULL_BALLS, GROUP_OF_FORMAT, LIMITED_GROUPS, MIN_SUPPORT, PARTITIONS

# --------------------------------------------------------------------------------------
# Feature definitions
# --------------------------------------------------------------------------------------

LIMITED_FEATURES: Dict[int, List[str]] = {
    1: ["runs", "wickets_lost", "wickets_remaining", "legal_balls", "balls_remaining", "current_run_rate",
        "resources_remaining", "expected_remaining_runs", "expected_final_score", "projected_minus_venue_par",
        "venue_par", "era_par", "elo_diff", "batting_won_toss", "female", "international"],
    2: ["runs", "wickets_lost", "wickets_remaining", "legal_balls", "balls_remaining", "target", "runs_required",
        "current_run_rate", "required_run_rate", "rrr_minus_crr", "runs_required_per_ball",
        "runs_required_per_wicket", "resources_remaining", "expected_remaining_runs", "chase_resource_ratio",
        "par_margin", "target_minus_venue_par", "venue_par", "era_par", "elo_diff", "batting_won_toss",
        "female", "international"],
}
# Monotonic directions for HistGradientBoosting on the primitive cricket quantities only
# (derived ratios are left unconstrained because they are non-monotone combinations).
LIMITED_MONOTONE: Dict[int, Dict[str, int]] = {
    1: {"runs": 1, "wickets_remaining": 1, "elo_diff": 1},
    2: {"runs_required": -1, "wickets_remaining": 1, "balls_remaining": 1, "elo_diff": 1},
}
MULTIDAY_FEATURES: List[str] = [
    "innings_number", "innings_runs", "wickets_lost", "wickets_remaining", "innings_legal_balls",
    "match_legal_balls", "innings_run_rate", "batting_prior_runs", "opposition_runs", "lead",
    "runs_required", "runs_required_per_wicket", "venue_par", "era_par", "elo_diff", "batting_won_toss",
    "female", "international",
]


class InvalidStateError(ValueError):
    """Raised for impossible or inconsistent match states."""


# --------------------------------------------------------------------------------------
# Resource table (built from training matches only)
# --------------------------------------------------------------------------------------

@dataclass
class ResourceTable:
    """Expected runs remaining by (balls remaining, wickets lost) for one format group."""
    full_balls: int
    expected: np.ndarray  # shape (full_balls + 1, 11)
    counts: np.ndarray    # training first-innings states per cell (support)
    raw_mean: np.ndarray  # unsmoothed cell means (nan where empty)

    @property
    def full_innings_runs(self) -> float:
        return float(self.expected[self.full_balls, 0])

    def _index(self, balls_remaining, wickets_lost):
        b = np.clip(np.asarray(balls_remaining, dtype=float), 0, self.full_balls).astype(int)
        w = np.clip(np.asarray(wickets_lost, dtype=float), 0, 10).astype(int)
        return b, w

    def remaining(self, balls_remaining, wickets_lost):
        b, w = self._index(balls_remaining, wickets_lost)
        return self.expected[b, w]

    def resources(self, balls_remaining, wickets_lost):
        return self.remaining(balls_remaining, wickets_lost) / self.full_innings_runs

    def support(self, balls_remaining, wickets_lost, window: int = 6):
        """Training states within +-window balls at the same wickets lost."""
        b, w = self._index(balls_remaining, wickets_lost)
        cum = np.vstack([np.zeros((1, 11)), np.cumsum(self.counts, axis=0)])
        lo = np.clip(b - window, 0, self.full_balls)
        hi = np.clip(b + window + 1, 0, self.full_balls + 1)
        return cum[hi, w] - cum[lo, w]


def fit_resource_table(states: pd.DataFrame, full_balls: int) -> ResourceTable:
    """Fit from first-innings states of *training* matches whose innings ran its full course.

    ``states`` needs ``balls_remaining``, ``wickets_lost`` and ``runs_remaining`` columns.
    The raw cell means are smoothed with a monotone gradient-boosted regression
    (more balls -> more runs, more wickets lost -> fewer runs) so sparse cells (for
    example 9 down with 250 balls left) are not left empty or noisy.
    """
    from sklearn.ensemble import HistGradientBoostingRegressor

    b = states["balls_remaining"].to_numpy(dtype=int)
    w = states["wickets_lost"].to_numpy(dtype=int)
    y = states["runs_remaining"].to_numpy(dtype=float)
    counts = np.zeros((full_balls + 1, 11))
    sums = np.zeros((full_balls + 1, 11))
    np.add.at(counts, (b, w), 1)
    np.add.at(sums, (b, w), y)
    with np.errstate(invalid="ignore", divide="ignore"):
        raw = np.where(counts > 0, sums / counts, np.nan)
    model = HistGradientBoostingRegressor(max_iter=300, learning_rate=0.05, max_depth=6,
                                          monotonic_cst=[1, -1], random_state=0)
    model.fit(np.column_stack([b, w]), y)
    grid_b, grid_w = np.meshgrid(np.arange(full_balls + 1), np.arange(11), indexing="ij")
    expected = model.predict(np.column_stack([grid_b.ravel(), grid_w.ravel()])).reshape(full_balls + 1, 11)
    expected = np.maximum(expected, 0.0)
    expected[0, :] = 0.0
    expected[:, 10] = 0.0
    # Enforce monotonicity exactly after clipping.
    expected = np.maximum.accumulate(expected, axis=0)
    expected = np.minimum.accumulate(expected, axis=1)
    return ResourceTable(full_balls=full_balls, expected=expected, counts=counts, raw_mean=raw)


# --------------------------------------------------------------------------------------
# Match table, labels and partitions
# --------------------------------------------------------------------------------------

def build_match_table(matches: pd.DataFrame, elo: pd.DataFrame, pars: pd.DataFrame) -> pd.DataFrame:
    table = matches.merge(elo, on="match_id", how="left").merge(pars, on="match_id", how="left")
    table["group"] = table["match_format"].map(GROUP_OF_FORMAT)
    table["female"] = table["gender"].astype(str).str.casefold().isin({"female", "women", "women's"}).astype(float)
    table["international"] = table["match_format"].isin(["T20I", "ODI", "Test"]).astype(float)
    result = table["result_type"].fillna("").astype(str).str.strip().str.casefold()
    table["is_draw"] = result.isin({"draw", "drawn"})
    table["is_tie"] = result.isin({"tie", "tied"}) & table["winner_id"].isna()
    table["has_winner"] = table["winner_id"].notna() & (
        (table["winner_id"] == table["team1_id"]) | (table["winner_id"] == table["team2_id"]))
    return table


def assign_partitions(table: pd.DataFrame, labelled: pd.Series) -> pd.Series:
    """Chronological, match-level partitions; a calendar date never straddles two partitions."""
    partition = pd.Series("unlabelled", index=table.index, dtype=object)
    for group, sub in table[labelled].groupby("group"):
        dates = np.sort(sub["start_date"].values)
        bounds, acc = [], 0.0
        for name, frac in PARTITIONS[:-1]:
            acc += frac
            bounds.append((name, dates[min(len(dates) - 1, int(round(acc * len(dates))) - 1)]))
        assigned = pd.Series(PARTITIONS[-1][0], index=sub.index, dtype=object)
        for name, cutoff in reversed(bounds):
            assigned[sub["start_date"] <= cutoff] = name
        partition.loc[sub.index] = assigned
    return partition


# --------------------------------------------------------------------------------------
# Per-delivery reconstruction
# --------------------------------------------------------------------------------------

def delivery_frame(deliveries: pd.DataFrame, innings: pd.DataFrame, match_table: pd.DataFrame) -> pd.DataFrame:
    """Attach innings/match info and pre/post running totals to each delivery."""
    inn = innings[innings["is_super_over"] == 0][[
        "innings_id", "match_id", "innings_number", "batting_team_id", "target_runs", "target_overs"]]
    frame = deliveries.copy()
    frame["innings_id"] = frame["innings_id"].astype(str)
    frame = frame.merge(inn.astype({"innings_id": str}), on="innings_id", how="inner")
    cols = ["match_id", "start_date", "group", "match_format", "team1_id", "team2_id", "winner_id",
            "toss_winner_id", "elo_team1", "elo_team2", "elo_games_team1", "elo_games_team2", "era_par",
            "venue_par", "venue_innings", "female", "international", "is_draw", "is_tie", "has_winner"]
    frame = frame.merge(match_table[cols], on="match_id", how="inner")
    frame = frame.sort_values(["start_date", "match_id", "innings_number", "over_number", "delivery_sequence"],
                              kind="stable").reset_index(drop=True)
    g = frame.groupby("innings_id", sort=False)
    for name, src in (("runs", "total_runs"), ("wkts", "wickets"), ("legal_count", "legal")):
        post = g[src].cumsum()
        frame[f"post_{name}"] = post.astype("int32")
        frame[f"pre_{name}"] = (post - frame[src]).astype("int32")
    frame["batting_is_team1"] = frame["batting_team_id"] == frame["team1_id"]
    frame["elo_diff"] = np.where(frame["batting_is_team1"], frame["elo_team1"] - frame["elo_team2"],
                                 frame["elo_team2"] - frame["elo_team1"])
    frame["batting_won_toss"] = (frame["toss_winner_id"] == frame["batting_team_id"]).astype(float)
    # Batting-side label: 1/0 win/loss; 2 marks a draw for multi-day; NaN = unlabelled.
    bat_won = frame["winner_id"] == frame["batting_team_id"]
    label = np.where(frame["has_winner"], np.where(bat_won, 0, 1), np.nan)  # 0 bat win, 1 bowl win
    label = np.where(frame["is_draw"], 2, label)
    frame["label_multi"] = label
    frame["label_bat_win"] = np.where(frame["has_winner"], bat_won.astype(float), np.nan)
    return frame


def add_innings_context(frame: pd.DataFrame, innings: pd.DataFrame) -> pd.DataFrame:
    """Targets for limited overs (derived when the source omits them) and prior-innings totals."""
    inn = innings[innings["is_super_over"] == 0].copy()
    inn = inn.sort_values(["match_id", "innings_number"])
    first_total = inn[inn["innings_number"] == 1].set_index("match_id")["runs"]
    frame["first_innings_total"] = frame["match_id"].map(first_total)
    # Prior runs per side and match balls before each innings (multi-day).
    inn["prev_legal"] = inn.groupby("match_id")["legal_balls"].cumsum() - inn["legal_balls"]
    priors = []
    for match_id, g in inn.groupby("match_id", sort=False):
        totals: Dict[str, int] = {}
        for row in g.itertuples(index=False):
            bat = row.batting_team_id
            opp = sum(v for k, v in totals.items() if k != bat)
            priors.append((row.innings_id, totals.get(bat, 0), opp, row.prev_legal))
            totals[bat] = totals.get(bat, 0) + int(row.runs)
    prior = pd.DataFrame(priors, columns=["innings_id", "batting_prior_runs", "opposition_runs", "match_legal_before"])
    prior["innings_id"] = prior["innings_id"].astype(str)
    return frame.merge(prior, on="innings_id", how="left")


# --------------------------------------------------------------------------------------
# Limited overs
# --------------------------------------------------------------------------------------

def limited_raw_states(frame: pd.DataFrame, group: str, which: str = "pre") -> pd.DataFrame:
    """Raw counters (``pre`` or ``post`` the delivery) for innings 1-2 rows of ``frame``."""
    full = FULL_BALLS[group]
    out = pd.DataFrame({
        "match_id": frame["match_id"].values,
        "innings": frame["innings_number"].values.astype(int),
        "runs": frame[f"{which}_runs"].values,
        "wickets_lost": frame[f"{which}_wkts"].values,
        "legal_balls": frame[f"{which}_legal_count"].values,
        "elo_diff": frame["elo_diff"].values,
        "venue_par": frame["venue_par"].values,
        "era_par": frame["era_par"].values,
        "batting_won_toss": frame["batting_won_toss"].values,
        "female": frame["female"].values,
        "international": frame["international"].values,
        "batting_is_team1": frame["batting_is_team1"].values,
    }, index=frame.index)
    inn2 = out["innings"] == 2
    target = frame["target_runs"].astype(float)
    derived = frame["first_innings_total"].astype(float) + 1
    out["target_source"] = np.where(inn2, np.where(target.notna(), "recorded", "first_innings_total+1"), "")
    out["target"] = np.where(inn2, target.fillna(derived), np.nan)
    overs = frame["target_overs"].astype(float)
    max_balls = np.where(inn2 & overs.notna(), np.minimum(overs * 6, full), full)
    # CPI stores revised (DLS) target overs as SMALLINT, so Cricsheet's fractional
    # allotments (e.g. 14.3 overs = 87 balls) are rounded (to 14 -> 84 balls). If a
    # delivery is bowled beyond the recorded allotment, the true allotment is larger:
    # that is observable when the ball is bowled, so pre-delivery states use at least
    # one more ball than already bowled. Applies only to reduced chases.
    reduced = inn2 & overs.notna() & (overs * 6 < full)
    if which == "pre":
        max_balls = np.where(reduced, np.maximum(max_balls, out["legal_balls"] + 1), max_balls)
    out["max_balls"] = np.minimum(max_balls, full)
    out["allotment_rounded"] = reduced & (out["legal_balls"] >= overs * 6)
    return out


def limited_terminal(raw: pd.DataFrame) -> np.ndarray:
    """Batting-side outcome if the *match* is already decided, else NaN.

    Innings 2: target reached -> 1; all out or balls exhausted short of the target ->
    0, or 0.5 when the scores are level (tie). Innings 1 is never match-terminal.
    """
    runs, wk, legal = raw["runs"].to_numpy(float), raw["wickets_lost"].to_numpy(float), raw["legal_balls"].to_numpy(float)
    target = raw["target"].to_numpy(float)
    inn2 = raw["innings"].to_numpy() == 2
    over = (wk >= 10) | (legal >= raw["max_balls"].to_numpy(float))
    out = np.full(len(raw), np.nan)
    won = inn2 & (runs >= target)
    out[won] = 1.0
    lost = inn2 & ~won & over
    out[lost] = np.where(runs[lost] == target[lost] - 1, 0.5, 0.0)
    return out


def validate_limited(raw: pd.DataFrame, group: str) -> np.ndarray:
    """Boolean mask of states that are physically possible."""
    full = FULL_BALLS[group]
    ok = (raw["runs"] >= 0) & raw["wickets_lost"].between(0, 10) & (raw["legal_balls"] >= 0)
    ok &= raw["legal_balls"] <= raw["max_balls"]
    ok &= raw["innings"].isin([1, 2])
    inn2 = raw["innings"] == 2
    ok &= ~inn2 | (raw["target"].notna() & (raw["target"] >= 1) & (raw["max_balls"] <= full) & (raw["max_balls"] > 0))
    return ok.to_numpy()


def limited_features(raw: pd.DataFrame, innings: int, table: ResourceTable) -> pd.DataFrame:
    f = pd.DataFrame(index=raw.index)
    runs = raw["runs"].astype(float)
    wl = raw["wickets_lost"].astype(float)
    legal = raw["legal_balls"].astype(float)
    balls_rem = (raw["max_balls"] - raw["legal_balls"]).astype(float).clip(lower=0)
    era = raw["era_par"].astype(float).fillna(table.full_innings_runs)
    venue = raw["venue_par"].astype(float).fillna(era)
    f["runs"] = runs
    f["wickets_lost"] = wl
    f["wickets_remaining"] = 10 - wl
    f["legal_balls"] = legal
    f["balls_remaining"] = balls_rem
    f["current_run_rate"] = np.where(legal > 0, runs * 6 / legal.replace(0, np.nan), np.nan)
    res = table.resources(balls_rem, wl)
    f["resources_remaining"] = res
    f["expected_remaining_runs"] = res * venue
    f["venue_par"] = venue
    f["era_par"] = era
    f["elo_diff"] = raw["elo_diff"].astype(float).fillna(0.0)
    f["batting_won_toss"] = raw["batting_won_toss"].astype(float)
    f["female"] = raw["female"].astype(float)
    f["international"] = raw["international"].astype(float)
    if innings == 1:
        f["expected_final_score"] = runs + f["expected_remaining_runs"]
        f["projected_minus_venue_par"] = f["expected_final_score"] - venue
    else:
        target = raw["target"].astype(float)
        req = (target - runs).clip(lower=0)
        safe_balls = balls_rem.replace(0, np.nan)
        f["target"] = target
        f["runs_required"] = req
        f["required_run_rate"] = req * 6 / safe_balls
        f["rrr_minus_crr"] = f["required_run_rate"] - f["current_run_rate"]
        f["runs_required_per_ball"] = req / safe_balls
        f["runs_required_per_wicket"] = req / (10 - wl).replace(0, np.nan)
        f["chase_resource_ratio"] = req / f["expected_remaining_runs"].clip(lower=1.0)
        f["par_margin"] = f["expected_remaining_runs"] - req
        f["target_minus_venue_par"] = target - 1 - venue
    return f[LIMITED_FEATURES[innings]]


def sample_states(frame: pd.DataFrame, stride: int) -> pd.DataFrame:
    """One pre-delivery state per legal-ball count (first delivery at that count), strided."""
    first = ~frame.duplicated(["innings_id", "pre_legal_count"])
    keep = first & (frame["pre_legal_count"] % stride == 0)
    return frame[keep]


# --------------------------------------------------------------------------------------
# Multi-day
# --------------------------------------------------------------------------------------

def multiday_raw_states(frame: pd.DataFrame, which: str = "pre") -> pd.DataFrame:
    legal = frame[f"{which}_legal_count"].values
    return pd.DataFrame({
        "match_id": frame["match_id"].values,
        "innings": frame["innings_number"].values.astype(int),
        "runs": frame[f"{which}_runs"].values,
        "wickets_lost": frame[f"{which}_wkts"].values,
        "legal_balls": legal,
        "match_legal_balls": frame["match_legal_before"].values + legal,
        "batting_prior_runs": frame["batting_prior_runs"].values,
        "opposition_runs": frame["opposition_runs"].values,
        "elo_diff": frame["elo_diff"].values,
        "venue_par": frame["venue_par"].values,
        "era_par": frame["era_par"].values,
        "batting_won_toss": frame["batting_won_toss"].values,
        "female": frame["female"].values,
        "international": frame["international"].values,
        "batting_is_team1": frame["batting_is_team1"].values,
    }, index=frame.index)


def multiday_terminal(raw: pd.DataFrame) -> np.ndarray:
    """Return 0 (batting win), 1 (bowling win), 3 (tie) when decided, else NaN.

    Innings 4: batting side passes the opposition total -> batting win; all out short
    -> bowling win; all out level -> tie. Innings 3: all out still behind -> innings
    defeat. Draws are never inferred from the score (time is not recorded).
    """
    inn = raw["innings"].to_numpy()
    total = raw["batting_prior_runs"].to_numpy(float) + raw["runs"].to_numpy(float)
    opp = raw["opposition_runs"].to_numpy(float)
    allout = raw["wickets_lost"].to_numpy(float) >= 10
    out = np.full(len(raw), np.nan)
    out[(inn == 4) & (total > opp)] = 0
    out[(inn == 4) & allout & (total < opp)] = 1
    out[(inn == 4) & allout & (total == opp)] = 3
    out[(inn == 3) & allout & (total < opp)] = 1
    return out


def validate_multiday(raw: pd.DataFrame) -> np.ndarray:
    ok = (raw["runs"] >= 0) & raw["wickets_lost"].between(0, 10) & (raw["legal_balls"] >= 0)
    ok &= raw["innings"].isin([1, 2, 3, 4]) & (raw["match_legal_balls"] >= raw["legal_balls"])
    ok &= (raw["batting_prior_runs"] >= 0) & (raw["opposition_runs"] >= 0)
    ok &= ~((raw["innings"] == 1) & ((raw["batting_prior_runs"] > 0) | (raw["opposition_runs"] > 0)))
    return ok.to_numpy()


def multiday_features(raw: pd.DataFrame) -> pd.DataFrame:
    f = pd.DataFrame(index=raw.index)
    runs = raw["runs"].astype(float)
    wl = raw["wickets_lost"].astype(float)
    legal = raw["legal_balls"].astype(float)
    inn = raw["innings"].astype(float)
    prior = raw["batting_prior_runs"].astype(float)
    opp = raw["opposition_runs"].astype(float)
    era = raw["era_par"].astype(float)
    f["innings_number"] = inn
    f["innings_runs"] = runs
    f["wickets_lost"] = wl
    f["wickets_remaining"] = 10 - wl
    f["innings_legal_balls"] = legal
    f["match_legal_balls"] = raw["match_legal_balls"].astype(float)
    f["innings_run_rate"] = np.where(legal > 0, runs * 6 / legal.replace(0, np.nan), np.nan)
    f["batting_prior_runs"] = prior
    f["opposition_runs"] = opp
    f["lead"] = prior + runs - opp
    req = np.where(inn == 4, (opp - prior - runs + 1).clip(lower=0), np.nan)
    f["runs_required"] = req
    f["runs_required_per_wicket"] = req / (10 - wl).replace(0, np.nan)
    f["era_par"] = era
    f["venue_par"] = raw["venue_par"].astype(float).fillna(era)
    f["elo_diff"] = raw["elo_diff"].astype(float).fillna(0.0)
    f["batting_won_toss"] = raw["batting_won_toss"].astype(float)
    f["female"] = raw["female"].astype(float)
    f["international"] = raw["international"].astype(float)
    return f[MULTIDAY_FEATURES]


def multiday_support_key(innings, wickets_lost, match_legal_balls):
    """Cells used to count training support for multi-day states (innings, wickets, 15-over block)."""
    return (np.asarray(innings, int) * 1000 + np.clip(np.asarray(wickets_lost, int), 0, 10) * 100
            + np.clip(np.asarray(match_legal_balls, float) // 90, 0, 99).astype(int))


# --------------------------------------------------------------------------------------
# Orientation
# --------------------------------------------------------------------------------------

def orient_to_team1(batting_win, batting_is_team1, bowling_win=None, draw=None):
    """Convert batting-side probabilities to (team1_win, team2_win, draw_or_tie)."""
    bw = np.asarray(batting_win, dtype=float)
    lw = 1.0 - bw if bowling_win is None else np.asarray(bowling_win, dtype=float)
    dr = np.zeros_like(bw) if draw is None else np.asarray(draw, dtype=float)
    t1 = np.asarray(batting_is_team1, dtype=bool)
    return np.where(t1, bw, lw), np.where(t1, lw, bw), dr


def support_flag(count) -> np.ndarray:
    return np.where(np.asarray(count) >= MIN_SUPPORT, "normal", "low")
