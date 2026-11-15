"""Unified career statistics across the ball-by-ball and scorecard layers.

Unit of aggregation: one (canonical match, innings, player). Each is counted
once however many sources hold it (see reconcile.py for the precedence rules).
Every metric reports its status (verified / derived / incomplete / unavailable)
and its basis: how many innings carry the fields it needs, out of how many.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Dict, Iterable, List, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.hybrid import coverage as cov
from app.hybrid import eligibility as el
from app.hybrid import formats
from app.hybrid.reconcile import BALL_BY_BALL, BAT_FIELDS, BOWL_FIELDS, SCORECARD, SourceRecord, reconcile
from app.models.models import ReconciliationFlag

COUNTED_SCORECARD = ("validated", "insufficient_fields")   # 'inconsistent' innings never count


# --------------------------------------------------------------------------- fetch

def _innings_ids(db: Session, sql: str, player_id: str, cid: Optional[str]) -> List[str]:
    ids = [r for (r,) in db.execute(text(sql), {"p": player_id})]
    if cid and ids:
        ids = [r for (r,) in db.execute(text("""SELECT i.id FROM match_innings i JOIN canonical_matches c
            ON c.match_id = i.match_id WHERE c.id = :cid AND i.id = ANY(:ids)"""), {"cid": cid, "ids": ids})]
    return ids


def _bb_batting(db: Session, player_id: str, cid: Optional[str] = None) -> List[Dict]:
    # Innings first (index lookups), then aggregate only those innings: keeps the planner off a full scan.
    ids = _innings_ids(db, """
        SELECT innings_id FROM deliveries WHERE batter_id = :p
        UNION SELECT innings_id FROM deliveries WHERE non_striker_id = :p
        UNION SELECT d.innings_id FROM wickets w JOIN deliveries d ON d.id = w.delivery_id WHERE w.player_out_id = :p""",
        player_id, cid)
    if not ids:
        return []
    return [dict(r._mapping) for r in db.execute(text("""
        SELECT c.id AS cid, c.format_class, c.start_date, c.coverage_status, i.innings_number,
            COALESCE(SUM(d.batter_runs) FILTER (WHERE d.batter_id = :p), 0) AS runs,
            COUNT(*) FILTER (WHERE d.batter_id = :p AND d.is_ball_faced_by_batter) AS balls,
            COUNT(*) FILTER (WHERE d.batter_id = :p AND d.is_boundary_four) AS fours,
            COUNT(*) FILTER (WHERE d.batter_id = :p AND d.is_boundary_six) AS sixes,
            bool_or(w.is_batter_dismissed AND w.player_out_id = :p) IS TRUE AS is_out
        FROM match_innings i
        JOIN canonical_matches c ON c.match_id = i.match_id
        JOIN deliveries d ON d.innings_id = i.id
        LEFT JOIN wickets w ON w.delivery_id = d.id AND w.player_out_id = :p
        WHERE i.id = ANY(:ids) AND NOT i.is_super_over
        GROUP BY c.id, c.format_class, c.start_date, c.coverage_status, i.id, i.innings_number"""),
        {"p": player_id, "ids": ids})]


def _bb_bowling(db: Session, player_id: str, cid: Optional[str] = None) -> List[Dict]:
    ids = _innings_ids(db, "SELECT DISTINCT innings_id FROM deliveries WHERE bowler_id = :p", player_id, cid)
    if not ids:
        return []
    return [dict(r._mapping) for r in db.execute(text("""
        WITH overs AS (
            SELECT d.innings_id, d.over_number, bool_and(d.bowler_id = :p) AS sole,
                   COUNT(*) FILTER (WHERE d.is_legal_ball) AS legal, SUM(d.bowling_runs) AS conceded
            FROM deliveries d WHERE d.innings_id = ANY(:ids)
            GROUP BY 1, 2 HAVING bool_or(d.bowler_id = :p)
        ), maidens AS (
            SELECT innings_id, COUNT(*) AS maidens FROM overs WHERE sole AND conceded = 0 AND legal >= 6 GROUP BY 1
        )
        SELECT c.id AS cid, c.format_class, c.start_date, c.coverage_status, i.innings_number,
            COUNT(*) FILTER (WHERE d.is_legal_ball) AS legal_balls,
            SUM(d.bowling_runs) AS runs_conceded,
            COALESCE(SUM(wk.n), 0) AS wickets,
            COALESCE(MAX(mx.maidens), 0) AS maidens
        FROM deliveries d JOIN match_innings i ON i.id = d.innings_id AND NOT i.is_super_over
        JOIN canonical_matches c ON c.match_id = i.match_id
        LEFT JOIN LATERAL (SELECT COUNT(*) FILTER (WHERE w.is_bowler_wicket) AS n FROM wickets w
                           WHERE w.delivery_id = d.id) wk ON TRUE
        LEFT JOIN maidens mx ON mx.innings_id = i.id
        WHERE d.innings_id = ANY(:ids) AND d.bowler_id = :p
        GROUP BY c.id, c.format_class, c.start_date, c.coverage_status, i.id, i.innings_number"""),
        {"p": player_id, "ids": ids})]


def _sc_batting(db: Session, player_id: str, cid: Optional[str] = None) -> List[Dict]:
    extra = "AND c.id = :cid" if cid else ""
    return [dict(r._mapping) for r in db.execute(text(f"""
        SELECT c.id AS cid, c.format_class, c.start_date, c.coverage_status, si.innings_number, r.source_key,
               si.validation_status, b.runs, b.balls_faced AS balls, b.fours, b.sixes, b.is_out
        FROM scorecard_batting b JOIN scorecard_innings si ON si.id = b.scorecard_innings_id
        JOIN match_source_refs r ON r.id = si.source_ref_id JOIN canonical_matches c ON c.id = si.canonical_match_id
        WHERE b.player_id = :p AND NOT b.did_not_bat {extra}"""), {"p": player_id, "cid": cid})]


def _sc_bowling(db: Session, player_id: str, cid: Optional[str] = None) -> List[Dict]:
    extra = "AND c.id = :cid" if cid else ""
    return [dict(r._mapping) for r in db.execute(text(f"""
        SELECT c.id AS cid, c.format_class, c.start_date, c.coverage_status, si.innings_number, r.source_key,
               si.validation_status, b.legal_balls, b.runs_conceded, b.wickets, b.maidens
        FROM scorecard_bowling b JOIN scorecard_innings si ON si.id = b.scorecard_innings_id
        JOIN match_source_refs r ON r.id = si.source_ref_id JOIN canonical_matches c ON c.id = si.canonical_match_id
        WHERE b.player_id = :p {extra}"""), {"p": player_id, "cid": cid})]


# --------------------------------------------------------------------------- merge

def merge(bb_rows: Iterable[Dict], sc_rows: Iterable[Dict], fields: Tuple[str, ...]) -> Tuple[List[Dict], List, int]:
    """Merge layers into one record per (canonical match, innings). Returns (records, conflicts, excluded)."""
    groups: Dict[Tuple[str, int], Dict] = {}
    excluded = 0
    for r in bb_rows:
        g = groups.setdefault((r["cid"], r["innings_number"]), {"meta": r, "src": []})
        g["src"].append(SourceRecord(BALL_BY_BALL, "cricsheet", {f: r.get(f) for f in fields},
                                     complete=r["coverage_status"] == cov.FULL))
    for r in sc_rows:
        if r["validation_status"] not in COUNTED_SCORECARD:
            excluded += 1
            continue
        g = groups.setdefault((r["cid"], r["innings_number"]), {"meta": r, "src": []})
        g["src"].append(SourceRecord(SCORECARD, r["source_key"], {f: r.get(f) for f in fields}))
    records, conflicts = [], []
    for (cid, n), g in groups.items():
        rec = reconcile(g["src"], fields)
        m = g["meta"]
        records.append({"cid": cid, "innings_number": n, "format_class": m["format_class"],
                        "start_date": m["start_date"], "coverage_status": m["coverage_status"],
                        "provenance": rec.provenance, "sources": rec.sources, **rec.values})
        conflicts.extend((cid, n, *c) for c in rec.conflicts)
    return records, conflicts, excluded


# --------------------------------------------------------------------------- metrics

def _m(metric: str, value, eligible: int, total: int, **extra) -> Dict:
    return {"value": value, "status": el.status_for(metric, eligible, total),
            "basis": {"innings": eligible, "of": total}, **extra}


def batting_metrics(records: List[Dict]) -> Dict:
    n = len(records)
    with_runs = el.records_with(records, ("runs",))
    with_out = el.records_with(records, ("is_out",))
    with_avg = el.records_with(records, ("runs", "is_out"))
    with_sr = el.records_with(records, ("runs", "balls"))
    runs = sum(r["runs"] for r in with_runs)
    outs = sum(1 for r in with_avg if r["is_out"])
    hs = max(with_runs, key=lambda r: (r["runs"], not r.get("is_out")), default=None)
    sr_balls = sum(r["balls"] for r in with_sr)
    return {
        "innings": {"value": n, "status": el.VERIFIED if n else el.UNAVAILABLE, "basis": {"innings": n, "of": n}},
        "runs": _m("runs", runs, len(with_runs), n),
        "not_outs": _m("not_outs", sum(1 for r in with_out if not r["is_out"]), len(with_out), n),
        "highest_score": _m("highest_score", None if hs is None else f"{hs['runs']}{'*' if hs.get('is_out') is False else ''}",
                            len(with_runs), n),
        "hundreds": _m("hundreds", sum(1 for r in with_runs if r["runs"] >= 100), len(with_runs), n),
        "fifties": _m("fifties", sum(1 for r in with_runs if 50 <= r["runs"] < 100), len(with_runs), n),
        "batting_average": _m("batting_average", round(sum(r["runs"] for r in with_avg) / outs, 2) if outs else None,
                              len(with_avg), n),
        "strike_rate": _m("strike_rate", round(100 * sum(r["runs"] for r in with_sr) / sr_balls, 2) if sr_balls else None,
                          len(with_sr), n),
        "fours": _m("fours", sum(r["fours"] for r in el.records_with(records, ("fours",))),
                    len(el.records_with(records, ("fours",))), n),
        "sixes": _m("sixes", sum(r["sixes"] for r in el.records_with(records, ("sixes",))),
                    len(el.records_with(records, ("sixes",))), n),
    }


def bowling_metrics(records: List[Dict]) -> Dict:
    n = len(records)
    wk = el.records_with(records, ("wickets",))
    rc = el.records_with(records, ("runs_conceded",))
    balls = el.records_with(records, ("legal_balls",))
    avg = el.records_with(records, ("runs_conceded", "wickets"))
    eco = el.records_with(records, ("runs_conceded", "legal_balls"))
    srr = el.records_with(records, ("legal_balls", "wickets"))
    avg_w = sum(r["wickets"] for r in avg)
    eco_b = sum(r["legal_balls"] for r in eco)
    sr_w = sum(r["wickets"] for r in srr)
    best = max(avg, key=lambda r: (r["wickets"], -r["runs_conceded"]), default=None)
    return {
        "innings": {"value": n, "status": el.VERIFIED if n else el.UNAVAILABLE, "basis": {"innings": n, "of": n}},
        "wickets": _m("wickets", sum(r["wickets"] for r in wk), len(wk), n),
        "runs_conceded": _m("runs_conceded", sum(r["runs_conceded"] for r in rc), len(rc), n),
        "balls_bowled": _m("balls_bowled", sum(r["legal_balls"] for r in balls), len(balls), n),
        "maidens": _m("maidens", sum(r["maidens"] for r in el.records_with(records, ("maidens",))),
                      len(el.records_with(records, ("maidens",))), n),
        "bowling_average": _m("bowling_average", round(sum(r["runs_conceded"] for r in avg) / avg_w, 2) if avg_w else None,
                              len(avg), n),
        "economy": _m("economy", round(6 * sum(r["runs_conceded"] for r in eco) / eco_b, 2) if eco_b else None,
                      len(eco), n, note="runs per six legal balls"),
        "bowling_strike_rate": _m("bowling_strike_rate", round(sum(r["legal_balls"] for r in srr) / sr_w, 1) if sr_w else None,
                                  len(srr), n),
        "best_innings": _m("wickets", None if best is None else f"{best['wickets']}/{best['runs_conceded']}", len(avg), n),
        "five_wicket_hauls": _m("wickets", sum(1 for r in wk if r["wickets"] >= 5), len(wk), n),
    }


def _provenance(records: List[Dict]) -> Dict[str, int]:
    out: Dict[str, int] = defaultdict(int)
    for r in records:
        out[r["provenance"]] += 1
    return dict(out)


def player_career(db: Session, player_id: str, gender: Optional[str] = None) -> Dict:
    bat, bat_conf, bat_ex = merge(_bb_batting(db, player_id), _sc_batting(db, player_id), BAT_FIELDS)
    bowl, bowl_conf, bowl_ex = merge(_bb_bowling(db, player_id), _sc_bowling(db, player_id), BOWL_FIELDS)
    apps = db.execute(text("""
        SELECT c.id, c.format_class, c.coverage_status, c.gender FROM match_appearances a
        JOIN canonical_matches c ON c.id = a.canonical_match_id WHERE a.player_id = :p"""), {"p": player_id}).all()
    matches: Dict[str, Dict[str, str]] = defaultdict(dict)
    for cid, fc, status, g in apps:
        if gender is None or g == gender:
            matches[fc][cid] = status
    for r in bat + bowl:  # participation seen in innings data also counts as an appearance
        matches[r["format_class"]].setdefault(r["cid"], r["coverage_status"])

    by_format = {}
    for fc in [f for f in formats.ALL_CLASSES if f in matches]:
        b = [r for r in bat if r["format_class"] == fc]
        w = [r for r in bowl if r["format_class"] == fc]
        statuses = defaultdict(int)
        for s in matches[fc].values():
            statuses[s] += 1
        by_format[fc] = {
            "label": formats.LABELS.get(fc, fc),
            "matches": {"value": len(matches[fc]), "status": el.VERIFIED, "by_coverage": dict(statuses)},
            "ball_by_ball_matches": statuses.get(cov.FULL, 0),
            "batting": batting_metrics(b), "bowling": bowling_metrics(w),
            "provenance": {"batting": _provenance(b), "bowling": _provenance(w)},
            "first_date": min((r["start_date"] for r in b + w), default=None),
            "last_date": max((r["start_date"] for r in b + w), default=None),
        }
    intl_bat = [r for r in bat if r["format_class"] in formats.INTERNATIONAL]
    intl_bowl = [r for r in bowl if r["format_class"] in formats.INTERNATIONAL]
    return {
        "player_id": player_id,
        "formats": by_format,
        "international_combined": {
            "matches": sum(len(matches[f]) for f in formats.INTERNATIONAL if f in matches),
            "batting": batting_metrics(intl_bat), "bowling": bowling_metrics(intl_bowl),
        },
        "conflicts": [{"canonical_match_id": c[0], "innings_number": c[1], "metric": c[2], "values": c[3],
                       "value_used": c[4], "rule": c[5]} for c in bat_conf + bowl_conf],
        "excluded_inconsistent_scorecard_innings": bat_ex + bowl_ex,
    }


# --------------------------------------------------------------------------- conflict persistence

def detect_conflicts(db: Session, canonical_id: str) -> int:
    """Persist source disagreements for every player in one canonical match. Returns flags written."""
    players = [p for (p,) in db.execute(text("""
        SELECT DISTINCT player_id FROM scorecard_batting WHERE canonical_match_id = :c AND player_id IS NOT NULL
        UNION SELECT DISTINCT player_id FROM scorecard_bowling WHERE canonical_match_id = :c AND player_id IS NOT NULL"""),
        {"c": canonical_id})]
    written = 0
    for pid in players:
        _, bc, _ = merge(_bb_batting(db, pid, canonical_id), _sc_batting(db, pid, canonical_id), BAT_FIELDS)
        _, wc, _ = merge(_bb_bowling(db, pid, canonical_id), _sc_bowling(db, pid, canonical_id), BOWL_FIELDS)
        for cid, n, metric, values, used, rule in bc + wc:
            flag = db.query(ReconciliationFlag).filter_by(canonical_match_id=cid, innings_number=n,
                                                          player_id=pid, metric=metric).one_or_none()
            values = {k: v for k, v in values.items()}
            resolution = f"Value used: {used!r} (rule: {rule})" if used is not None else f"Unresolved ({rule})"
            if flag is None:
                db.add(ReconciliationFlag(canonical_match_id=cid, innings_number=n, player_id=pid, metric=metric,
                                          values=values, resolution=resolution))
            elif flag.status != "resolved" or flag.values != values:
                flag.values, flag.resolution, flag.status = values, resolution, "open"
            written += 1
    db.flush()
    return written
