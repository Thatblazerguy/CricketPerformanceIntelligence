"""Pre-match context that only uses information available before a match starts.

* Chronological Elo per (pool, gender, team). A result only updates ratings after
  a format-specific lag, so matches that overlap in time never see each other.
* Era par: mean completed first-innings total for the group and gender over the
  previous ``ERA_WINDOW_DAYS`` (strictly earlier dates).
* Venue par: prior first-innings totals at the venue, shrunk towards era par.
"""
from __future__ import annotations

import heapq
from collections import defaultdict
from typing import Dict, Tuple

import numpy as np
import pandas as pd

from .constants import (ELO_K, ELO_POOL, ELO_RESULT_LAG_DAYS, ELO_START, ERA_MIN_INNINGS,
                        ERA_WINDOW_DAYS, FULL_BALLS, GROUP_OF_FORMAT, VENUE_SHRINK)


def _team1_score(row) -> float | None:
    """Result from team1's perspective: 1 win, 0 loss, .5 tie/draw, None no result."""
    result = str(row.result_type or "").strip().casefold()
    if isinstance(row.winner_id, str) and row.winner_id:
        if row.winner_id == row.team1_id:
            return 1.0
        if row.winner_id == row.team2_id:
            return 0.0
        return None
    if result in {"tie", "tied", "draw", "drawn"}:
        return 0.5
    return None


def compute_elo(matches: pd.DataFrame) -> Tuple[pd.DataFrame, Dict[str, dict]]:
    """Return per-match pre-match ratings and the final rating snapshot.

    The snapshot (``{pool|gender|team: {"rating", "games", "last"}}``) is what live
    predictions use; it is the state after every result available in the data.
    """
    frame = matches.sort_values(["start_date", "match_id"]).reset_index(drop=True)
    ratings: Dict[tuple, float] = defaultdict(lambda: ELO_START)
    games: Dict[tuple, int] = defaultdict(int)
    last: Dict[tuple, str] = {}
    pending: list = []  # (available_date, seq, key1, key2, score)
    out = np.full((len(frame), 4), np.nan)
    seq = 0
    for idx, row in enumerate(frame.itertuples(index=False)):
        today = row.start_date
        while pending and pending[0][0] <= today:
            _, _, k1, k2, score, played = heapq.heappop(pending)
            r1, r2 = ratings[k1], ratings[k2]
            expected = 1.0 / (1.0 + 10 ** ((r2 - r1) / 400.0))
            ratings[k1] = r1 + ELO_K * (score - expected)
            ratings[k2] = r2 - ELO_K * (score - expected)
            games[k1] += 1
            games[k2] += 1
            last[k1] = last[k2] = str(played.date())
        pool = ELO_POOL.get(row.match_format)
        if pool is None or not isinstance(row.team1_id, str) or not isinstance(row.team2_id, str):
            continue
        k1 = (pool, row.gender, row.team1_id)
        k2 = (pool, row.gender, row.team2_id)
        out[idx] = (ratings[k1], ratings[k2], games[k1], games[k2])
        score = _team1_score(row)
        if score is not None:
            lag = pd.Timedelta(days=ELO_RESULT_LAG_DAYS.get(row.match_format, 1))
            seq += 1
            heapq.heappush(pending, (today + lag, seq, k1, k2, score, today))
    while pending:  # final snapshot includes every completed result
        _, _, k1, k2, score, played = heapq.heappop(pending)
        r1, r2 = ratings[k1], ratings[k2]
        expected = 1.0 / (1.0 + 10 ** ((r2 - r1) / 400.0))
        ratings[k1] = r1 + ELO_K * (score - expected)
        ratings[k2] = r2 - ELO_K * (score - expected)
        games[k1] += 1
        games[k2] += 1
        last[k1] = last[k2] = str(played.date())
    result = pd.DataFrame(out, columns=["elo_team1", "elo_team2", "elo_games_team1", "elo_games_team2"])
    result.insert(0, "match_id", frame["match_id"].values)
    snapshot = {"|".join(key): {"rating": float(ratings[key]), "games": int(games[key]), "last": last.get(key)}
                for key in ratings}
    return result, snapshot


def _qualifying_first_innings(matches: pd.DataFrame, innings: pd.DataFrame) -> pd.DataFrame:
    first = innings[(innings["innings_number"] == 1) & (innings["is_super_over"] == 0)]
    frame = first.merge(matches[["match_id", "start_date", "gender", "match_format", "venue_id"]], on="match_id")
    frame["group"] = frame["match_format"].map(GROUP_OF_FORMAT)
    full = frame["group"].map(FULL_BALLS)
    limited = full.notna()
    # Limited overs: only innings that ran their natural course (all out or full overs),
    # so rain-shortened innings do not drag par down. Multi-day: all first innings.
    complete = ~limited | (frame["wickets"] >= 10) | (frame["legal_balls"] >= full.fillna(0))
    return frame[complete & frame["group"].notna()].sort_values("start_date")


def compute_pars(matches: pd.DataFrame, innings: pd.DataFrame) -> Tuple[pd.DataFrame, dict]:
    """Per-match era par and venue par using strictly earlier dates only."""
    qual = _qualifying_first_innings(matches, innings)
    target = matches[["match_id", "start_date", "gender", "match_format", "venue_id"]].copy()
    target["group"] = target["match_format"].map(GROUP_OF_FORMAT)
    target["era_par"] = np.nan
    target["venue_par"] = np.nan
    target["venue_innings"] = 0
    snapshot = {"era": {}, "venue": {}}
    window = np.timedelta64(ERA_WINDOW_DAYS, "D")
    for (group, gender), hist in qual.groupby(["group", "gender"]):
        hist = hist.sort_values("start_date")
        dates = hist["start_date"].values
        runs = hist["runs"].to_numpy(dtype=float)
        csum = np.concatenate([[0.0], np.cumsum(runs)])
        mask = (target["group"] == group) & (target["gender"] == gender)
        d = target.loc[mask, "start_date"].values
        hi = np.searchsorted(dates, d, side="left")  # strictly before match date
        lo = np.searchsorted(dates, d - window, side="left")
        n_window = hi - lo
        use_all = n_window < ERA_MIN_INNINGS
        lo = np.where(use_all, 0, lo)
        n = hi - lo
        era = np.where(n > 0, (csum[hi] - csum[lo]) / np.maximum(n, 1), np.nan)
        target.loc[mask, "era_par"] = era
        cut = dates[-1] - window if len(dates) else None
        recent_runs = runs[dates >= cut] if cut is not None else runs
        if len(recent_runs) < ERA_MIN_INNINGS:
            recent_runs = runs
        snapshot["era"][f"{group}|{gender}"] = {"par": float(recent_runs.mean()) if len(recent_runs) else None,
                                                "innings": int(len(recent_runs))}
        # Venue par: per-venue cumulative history, shrunk to the era par at the match date.
        venue_hist = {v: (g["start_date"].values, np.concatenate([[0.0], np.cumsum(g["runs"].to_numpy(dtype=float))]))
                      for v, g in hist.groupby("venue_id")}
        idx = target.index[mask]
        vpar = np.full(len(idx), np.nan)
        vcount = np.zeros(len(idx), dtype=int)
        for j, (venue, date, e) in enumerate(zip(target.loc[idx, "venue_id"].values, d, era)):
            if venue in venue_hist and not np.isnan(e):
                vd, vc = venue_hist[venue]
                k = np.searchsorted(vd, date, side="left")
                vpar[j] = (vc[k] + VENUE_SHRINK * e) / (k + VENUE_SHRINK)
                vcount[j] = k
            else:
                vpar[j] = e
        target.loc[idx, "venue_par"] = vpar
        target.loc[idx, "venue_innings"] = vcount
        era_now = snapshot["era"][f"{group}|{gender}"]["par"]
        for venue, (vd, vc) in venue_hist.items():
            if era_now is not None:
                snapshot["venue"][f"{group}|{gender}|{venue}"] = {
                    "par": float((vc[-1] + VENUE_SHRINK * era_now) / (len(vd) + VENUE_SHRINK)), "innings": int(len(vd))}
    return target[["match_id", "era_par", "venue_par", "venue_innings"]], snapshot
