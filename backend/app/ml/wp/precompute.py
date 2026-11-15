"""Historical per-delivery win-probability curves with the v2 engine.

Each delivery stores team1/team2/draw probabilities *before* and *after* the ball
in the existing ``match_win_probabilities`` blob format, so the API and frontend
are unchanged. "After" is the state before the next delivery of the match (so
innings transitions are handled by the same state reconstruction); after the
final delivery it is the recorded result. All pre-match context (Elo, venue and
era par) is computed exactly as in training, so curves are reproducible.

Packed item: [innings, over, ball, batter_id, bowler_id, team1_batting,
              before(team1, team2, draw), after(team1, team2, draw),
              runs, wickets, flags, confidence_code]
confidence_code: 0 normal, 1 low support, 2 decided by the Laws.
"""
from __future__ import annotations

import gzip
import json
from typing import Dict, Iterable, Optional

import numpy as np
import pandas as pd
from sqlalchemy.dialects.postgresql import insert

from . import context, data
from . import features as F
from .constants import GROUPS, LIMITED_GROUPS
from .engine import WinProbabilityEngine, load_bundle

CONF_CODE = {"normal": 0, "low": 1, "certain": 2}


def _prepare(db, cache_dir=None):
    matches = data.load_matches(db)
    innings = data.load_innings_summary(db)
    elo, _ = context.compute_elo(matches)
    pars, _ = context.compute_pars(matches, innings)
    return F.build_match_table(matches, elo, pars), innings


def group_predictions(db, group: str, table: pd.DataFrame, innings: pd.DataFrame, match_ids=None, cache_dir=None):
    """Return (frame, team1/team2/draw before arrays, confidence) for every delivery in ``group``."""
    engine = WinProbabilityEngine(load_bundle(group))
    deliveries = data.load_deliveries(db, GROUPS[group], cache_dir, match_ids=match_ids)
    frame = F.delivery_frame(deliveries, innings, table)
    frame = F.add_innings_context(frame, innings)
    if group in LIMITED_GROUPS:
        frame = frame[frame["innings_number"].isin([1, 2])].reset_index(drop=True)
        raw = F.limited_raw_states(frame, group)
        pred = engine.predict_limited_frame(raw)
        t1, t2, dr = F.orient_to_team1(pred["batting_win"], raw["batting_is_team1"])
        dr = pred["tie"].to_numpy()
        t1 = np.where(dr > 0, 0.0, t1)
        t2 = np.where(dr > 0, 0.0, t2)
    else:
        frame = frame[frame["innings_number"].between(1, 4)].reset_index(drop=True)
        raw = F.multiday_raw_states(frame)
        pred = engine.predict_multiday_frame(raw)
        t1, t2, dr = F.orient_to_team1(pred["batting_win"], raw["batting_is_team1"], pred["bowling_win"], pred["draw"])
    before = np.column_stack([t1, t2, dr])
    return engine, frame, before, pred["status"].to_numpy(), pred["confidence"].to_numpy()


def _result_vector(row) -> Optional[np.ndarray]:
    if row["has_winner"]:
        return np.array([1.0, 0.0, 0.0]) if row["winner_id"] == row["team1_id"] else np.array([0.0, 1.0, 0.0])
    if row["is_draw"] or row["is_tie"]:
        return np.array([0.0, 0.0, 1.0])
    return None


def precompute(db, groups: Optional[Iterable[str]] = None, match_ids: Optional[Iterable[str]] = None,
               cache_dir=None, commit_every: int = 200) -> Dict[str, int]:
    from app.models.models import MatchWinProbability

    table, innings = _prepare(db, cache_dir)
    wanted = set(match_ids) if match_ids is not None else None
    summary: Dict[str, int] = {}
    for group in groups or GROUPS:
        sub = table[table["group"] == group]
        ids = None
        if wanted is not None:
            ids = [m for m in sub["match_id"] if m in wanted]
            if not ids:
                continue
        engine, frame, before, status, confidence = group_predictions(db, group, table, innings, ids, cache_dir)
        meta = sub.set_index("match_id")
        rows = []
        starts = np.flatnonzero(np.r_[True, frame["match_id"].to_numpy()[1:] != frame["match_id"].to_numpy()[:-1]])
        ends = np.r_[starts[1:], len(frame)]
        seen = set()
        for s, e in zip(starts, ends):
            match_id = frame.at[s, "match_id"]
            seen.add(match_id)
            m = meta.loc[match_id]
            result = _result_vector(m)
            if result is None:
                rows.append(dict(match_id=match_id, match_format=m["match_format"], format_family=group,
                                 model_version=engine.version, status="unlabelled_no_result", delivery_count=0,
                                 predictions_gzip=None, exclusion_reason="No result / abandoned: there is no outcome to forecast."))
                continue
            if (status[s:e] == "invalid").any():
                rows.append(dict(match_id=match_id, match_format=m["match_format"], format_family=group,
                                 model_version=engine.version, status="invalid_state", delivery_count=0, predictions_gzip=None,
                                 exclusion_reason="Source data contains an impossible match state (e.g. balls beyond the innings limit)."))
                continue
            b = before[s:e]
            after = np.vstack([b[1:], result[None, :]])
            f = frame.iloc[s:e]
            flags = f["boundary"].to_numpy() | np.where(f["wickets"].to_numpy() > 0, 4, 0)
            packed = [[int(i), int(o) + 1, int(q) + 1, bat if isinstance(bat, str) else None,
                       bow if isinstance(bow, str) else None, int(t1b),
                       *[round(float(v), 5) for v in pb], *[round(float(v), 5) for v in pa], int(r), int(wk), int(fl),
                       CONF_CODE.get(c, 0)]
                      for i, o, q, bat, bow, t1b, pb, pa, r, wk, fl, c in zip(
                          f["innings_number"], f["over_number"], f["delivery_sequence"], f["batter_id"], f["bowler_id"],
                          f["batting_is_team1"], b, after, f["total_runs"], f["wickets"], flags, confidence[s:e])]
            rows.append(dict(match_id=match_id, match_format=m["match_format"], format_family=group,
                             model_version=engine.version, status="available", delivery_count=len(packed),
                             predictions_gzip=gzip.compress(json.dumps(packed, separators=(",", ":")).encode(), 6),
                             exclusion_reason=None))
            if len(rows) >= commit_every:
                _upsert(db, MatchWinProbability, rows)
                rows = []
        # Matches without any regulation deliveries (abandoned before a ball).
        targets = set(ids) if ids is not None else set(sub["match_id"])
        for match_id in targets - seen:
            m = meta.loc[match_id]
            rows.append(dict(match_id=match_id, match_format=m["match_format"], format_family=group,
                             model_version=engine.version, status="unlabelled_no_result", delivery_count=0,
                             predictions_gzip=None, exclusion_reason="No deliveries recorded for this match."))
        _upsert(db, MatchWinProbability, rows)
        summary[group] = len(targets)
    return summary


def _upsert(db, model, rows):
    if not rows:
        return
    stmt = insert(model.__table__).values(rows)
    stmt = stmt.on_conflict_do_update(index_elements=["match_id"], set_={
        c: stmt.excluded[c] for c in ("match_format", "format_family", "model_version", "status", "delivery_count",
                                      "predictions_gzip", "exclusion_reason")} | {"built_at": pd.Timestamp.utcnow().to_pydatetime()})
    db.execute(stmt)
    db.commit()
