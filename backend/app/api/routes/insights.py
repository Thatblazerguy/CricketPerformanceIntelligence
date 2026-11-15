"""Aggregation endpoints behind the analytics dashboards.

All statistics are computed in SQL from stored ball-by-ball deliveries and then
summarised by the pure helpers in :mod:`app.analytics.insights`. Each response
carries its sample sizes and the filters that were applied so charts can show
both. Nothing here fabricates a value: undefined ratios are ``None``.
"""
from __future__ import annotations

from collections import defaultdict
from threading import Lock
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.analytics.insights import (
    FORMAT_INNINGS_BALLS, batting_rates, bowling_rates, build_standings, consistency_summary,
    histogram, normalise_bowling_style, nrr_balls, overs_display, percentile_rank, ratio,
    rolling_average_by_dismissal, rolling_mean,
)
from app.db.session import get_db

router = APIRouter()

_CACHE: Dict[tuple, Any] = {}
_CACHE_LOCK = Lock()
_CACHE_MAX = 64


def _cached(key: tuple, build):
    with _CACHE_LOCK:
        if key in _CACHE:
            return _CACHE[key]
    value = build()
    with _CACHE_LOCK:
        if len(_CACHE) >= _CACHE_MAX:
            _CACHE.pop(next(iter(_CACHE)))
        _CACHE[key] = value
    return value


def clear_cache() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()


def _match_filters(params: dict, *, format=None, gender=None, competition=None, start_year=None,
                   end_year=None, season=None, venue_id=None, vs_team_id=None, alias="m") -> str:
    """Shared WHERE fragment for matches; every condition is parameterised."""
    if start_year and end_year and start_year > end_year:
        raise HTTPException(status_code=422, detail="Start year must be on or before end year.")
    conds = ["1=1"]
    if format:
        conds.append(f"{alias}.match_format = :format"); params["format"] = format
    if gender and gender.lower() != "all":
        conds.append(f"LOWER({alias}.gender) = :gender"); params["gender"] = gender.lower()
    if competition:
        conds.append(f"{alias}.tournament_id IN (SELECT id FROM tournaments WHERE name ILIKE :competition)")
        params["competition"] = f"%{competition}%"
    if start_year:
        conds.append(f"{alias}.start_date >= :start_date"); params["start_date"] = f"{start_year}-01-01"
    if end_year:
        conds.append(f"{alias}.start_date <= :end_date"); params["end_date"] = f"{end_year}-12-31"
    if season:
        conds.append(f"{alias}.season = :season"); params["season"] = season
    if venue_id:
        conds.append(f"{alias}.venue_id = :venue_id"); params["venue_id"] = venue_id
    if vs_team_id:
        conds.append(f"(:vs_team_id IN ({alias}.team1_id, {alias}.team2_id))"); params["vs_team_id"] = vs_team_id
    return " AND ".join(conds)


def _rows(db: Session, sql: str, params: dict) -> List[dict]:
    return [dict(r._mapping) for r in db.execute(text(sql), params)]


# --------------------------------------------------------------------------- players

@router.get("/players/{player_id}/innings-log")
def player_innings_log(
    player_id: str,
    format: Optional[str] = None,
    gender: Optional[str] = None,
    competition: Optional[str] = None,
    start_year: Optional[int] = None,
    end_year: Optional[int] = None,
    season: Optional[str] = None,
    venue_id: Optional[str] = None,
    vs_team_id: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Innings-by-innings batting and bowling records plus distributions derived from them.

    Opponent filtering uses the side the player faced in that innings, so an
    all-rounder's batting and bowling logs both mean "against this team"."""
    key = ("innings-log", player_id, format, gender, competition, start_year, end_year, season, venue_id, vs_team_id)
    return _cached(key, lambda: _player_innings_log(db, player_id, format, gender, competition, start_year, end_year, season, venue_id, vs_team_id))


def _player_innings_log(db, player_id, format, gender, competition, start_year, end_year, season, venue_id, vs_team_id):
    if not db.execute(text("SELECT 1 FROM players WHERE id = :pid"), {"pid": player_id}).scalar():
        raise HTTPException(status_code=404, detail="Player not found")
    params: dict = {"pid": player_id}
    mf = _match_filters(params, format=format, gender=gender, competition=competition, start_year=start_year,
                        end_year=end_year, season=season, venue_id=venue_id)
    opp_bat = opp_bowl = ""
    if vs_team_id:
        params["vs_team_id"] = vs_team_id
        opp_bat = "AND (CASE WHEN mi.batting_team_id = m.team1_id THEN m.team2_id ELSE m.team1_id END) = :vs_team_id"
        opp_bowl = "AND mi.batting_team_id = :vs_team_id"

    batting = _rows(db, f"""
    WITH inns AS (
        SELECT DISTINCT d.innings_id FROM deliveries d
        WHERE d.batter_id = :pid OR d.non_striker_id = :pid
        UNION
        SELECT d.innings_id FROM wickets w JOIN deliveries d ON d.id = w.delivery_id WHERE w.player_out_id = :pid
    ), scoped AS (
        SELECT mi.id AS innings_id, mi.match_id, mi.innings_number, mi.batting_team_id, m.start_date, m.season,
               m.match_format, m.venue_id,
               CASE WHEN mi.batting_team_id = m.team1_id THEN m.team2_id ELSE m.team1_id END AS opponent_id
        FROM inns JOIN match_innings mi ON mi.id = inns.innings_id JOIN matches m ON m.id = mi.match_id
        WHERE mi.is_super_over = FALSE AND {mf} {opp_bat}
    ), first_seen AS (
        SELECT x.innings_id, x.player_id, MIN(x.ord) AS ord FROM (
            -- ANY(ARRAY(...)) makes the planner use ix_delivery_innings_id instead of scanning all deliveries.
            SELECT d.innings_id, d.batter_id AS player_id, (d.over_number * 1000 + d.delivery_sequence) * 2 AS ord
            FROM deliveries d WHERE d.innings_id = ANY(ARRAY(SELECT innings_id FROM scoped))
            UNION ALL
            SELECT d.innings_id, d.non_striker_id, (d.over_number * 1000 + d.delivery_sequence) * 2 + 1
            FROM deliveries d WHERE d.innings_id = ANY(ARRAY(SELECT innings_id FROM scoped))
        ) x WHERE x.player_id IS NOT NULL GROUP BY x.innings_id, x.player_id
    ), positions AS (
        SELECT innings_id, player_id, RANK() OVER (PARTITION BY innings_id ORDER BY ord) AS position FROM first_seen
    ), bat AS (
        SELECT d.innings_id,
               SUM(d.batter_runs) AS runs,
               SUM(CASE WHEN d.is_ball_faced_by_batter THEN 1 ELSE 0 END) AS balls,
               SUM(CASE WHEN d.is_boundary_four THEN 1 ELSE 0 END) AS fours,
               SUM(CASE WHEN d.is_boundary_six THEN 1 ELSE 0 END) AS sixes,
               SUM(CASE WHEN d.is_ball_faced_by_batter AND d.batter_runs = 0 THEN 1 ELSE 0 END) AS dots
        FROM deliveries d JOIN scoped s ON s.innings_id = d.innings_id WHERE d.batter_id = :pid
        GROUP BY d.innings_id
    ), outs AS (
        SELECT d.innings_id, MIN(w.dismissal_type) AS dismissal_type,
               MIN(CASE WHEN w.is_bowler_wicket THEN p.canonical_name END) AS bowler
        FROM wickets w JOIN deliveries d ON d.id = w.delivery_id JOIN scoped s ON s.innings_id = d.innings_id
        LEFT JOIN players p ON p.id = d.bowler_id
        WHERE w.player_out_id = :pid AND w.is_batter_dismissed = TRUE GROUP BY d.innings_id
    )
    SELECT s.innings_id, s.match_id, s.innings_number, s.start_date, s.season, s.match_format,
           opp.canonical_name AS opponent, opp.id AS opponent_id, v.canonical_name AS venue, v.id AS venue_id,
           COALESCE(b.runs, 0) AS runs, COALESCE(b.balls, 0) AS balls, COALESCE(b.fours, 0) AS fours,
           COALESCE(b.sixes, 0) AS sixes, COALESCE(b.dots, 0) AS dots,
           o.dismissal_type, o.bowler AS dismissed_by, pos.position
    FROM scoped s
    LEFT JOIN bat b ON b.innings_id = s.innings_id
    LEFT JOIN outs o ON o.innings_id = s.innings_id
    LEFT JOIN positions pos ON pos.innings_id = s.innings_id AND pos.player_id = :pid
    LEFT JOIN teams opp ON opp.id = s.opponent_id
    LEFT JOIN venues v ON v.id = s.venue_id
    ORDER BY s.start_date, s.match_id, s.innings_number
    """, params)

    scoring = _rows(db, f"""
    SELECT LEAST(d.batter_runs, 6) AS runs_off_ball,
           SUM(CASE WHEN d.is_boundary_four THEN 1 ELSE 0 END) AS boundary_fours,
           SUM(CASE WHEN d.is_boundary_six THEN 1 ELSE 0 END) AS boundary_sixes,
           COUNT(*) AS balls
    FROM deliveries d JOIN match_innings mi ON mi.id = d.innings_id JOIN matches m ON m.id = mi.match_id
    WHERE d.batter_id = :pid AND d.is_ball_faced_by_batter AND mi.is_super_over = FALSE AND {mf} {opp_bat}
    GROUP BY 1 ORDER BY 1
    """, params)

    style_split = _rows(db, f"""
    WITH styles AS (
        SELECT player_id, MIN(attribute_value) AS style FROM player_attributes
        WHERE attribute_type = 'bowling_style' GROUP BY player_id
    )
    SELECT st.style,
           SUM(d.batter_runs) AS runs,
           SUM(CASE WHEN d.is_ball_faced_by_batter THEN 1 ELSE 0 END) AS balls,
           SUM(CASE WHEN d.is_boundary_four THEN 1 ELSE 0 END) AS fours,
           SUM(CASE WHEN d.is_boundary_six THEN 1 ELSE 0 END) AS sixes,
           SUM(CASE WHEN d.is_ball_faced_by_batter AND d.batter_runs = 0 THEN 1 ELSE 0 END) AS dots,
           COUNT(w.id) AS dismissals
    FROM deliveries d JOIN match_innings mi ON mi.id = d.innings_id JOIN matches m ON m.id = mi.match_id
    LEFT JOIN styles st ON st.player_id = d.bowler_id
    LEFT JOIN wickets w ON w.delivery_id = d.id AND w.player_out_id = :pid AND w.is_batter_dismissed = TRUE AND w.is_bowler_wicket = TRUE
    WHERE d.batter_id = :pid AND mi.is_super_over = FALSE AND {mf} {opp_bat}
    GROUP BY st.style
    """, params)

    bowling = _rows(db, f"""
    WITH spells AS (
        SELECT d.innings_id, d.over_number,
               SUM(CASE WHEN d.is_legal_ball THEN 1 ELSE 0 END) AS legal,
               SUM(d.bowling_runs) AS runs,
               SUM(CASE WHEN d.is_legal_ball AND d.bowling_runs = 0 THEN 1 ELSE 0 END) AS dots,
               SUM(CASE WHEN d.is_boundary_four OR d.is_boundary_six THEN 1 ELSE 0 END) AS boundaries,
               SUM(CASE WHEN d.is_boundary_four THEN 1 ELSE 0 END) AS fours,
               SUM(CASE WHEN d.is_boundary_six THEN 1 ELSE 0 END) AS sixes
        FROM deliveries d JOIN match_innings mi ON mi.id = d.innings_id JOIN matches m ON m.id = mi.match_id
        WHERE d.bowler_id = :pid AND mi.is_super_over = FALSE AND {mf} {opp_bowl}
        GROUP BY d.innings_id, d.over_number
    ), wk AS (
        SELECT d.innings_id, COUNT(*) AS wickets FROM wickets w JOIN deliveries d ON d.id = w.delivery_id
        WHERE d.bowler_id = :pid AND w.is_bowler_wicket = TRUE GROUP BY d.innings_id
    )
    SELECT sp.innings_id, mi.match_id, m.start_date, m.season, m.match_format,
           opp.canonical_name AS opponent, opp.id AS opponent_id, v.canonical_name AS venue, v.id AS venue_id,
           SUM(sp.legal) AS legal_balls, SUM(sp.runs) AS runs, SUM(sp.dots) AS dots,
           SUM(sp.boundaries) AS boundaries, SUM(sp.fours) AS fours, SUM(sp.sixes) AS sixes,
           SUM(CASE WHEN sp.legal = 6 AND sp.runs = 0 THEN 1 ELSE 0 END) AS maidens,
           COALESCE(MAX(wk.wickets), 0) AS wickets
    FROM spells sp JOIN match_innings mi ON mi.id = sp.innings_id JOIN matches m ON m.id = mi.match_id
    LEFT JOIN wk ON wk.innings_id = sp.innings_id
    LEFT JOIN teams opp ON opp.id = mi.batting_team_id
    LEFT JOIN venues v ON v.id = m.venue_id
    GROUP BY sp.innings_id, mi.match_id, m.start_date, m.season, m.match_format, opp.canonical_name, opp.id, v.canonical_name, v.id
    ORDER BY m.start_date, mi.match_id
    """, params)

    bowl_dismissals = _rows(db, f"""
    SELECT w.dismissal_type, COUNT(*) AS wickets
    FROM wickets w JOIN deliveries d ON d.id = w.delivery_id JOIN match_innings mi ON mi.id = d.innings_id
    JOIN matches m ON m.id = mi.match_id
    WHERE d.bowler_id = :pid AND w.is_bowler_wicket = TRUE AND mi.is_super_over = FALSE AND {mf} {opp_bowl}
    GROUP BY 1 ORDER BY 2 DESC
    """, params)

    return {
        "player_id": player_id,
        "filters": {"format": format, "gender": gender, "competition": competition, "start_year": start_year,
                    "end_year": end_year, "season": season, "venue_id": venue_id, "vs_team_id": vs_team_id},
        "ignored_filters_note": "Innings-level logs ignore phase and bowling-style filters because they would split innings.",
        "batting": _batting_section(batting, scoring, style_split, format),
        "bowling": _bowling_section(bowling, bowl_dismissals, format),
    }


def _batting_section(rows: List[dict], scoring: List[dict], style_split: List[dict], fmt: Optional[str]) -> dict:
    for r in rows:
        r["start_date"] = str(r["start_date"])
        r["dismissed"] = r["dismissal_type"] is not None
        r["strike_rate"] = ratio(r["runs"], r["balls"], 100)
    runs = [r["runs"] for r in rows]
    dismissed = [r["dismissed"] for r in rows]
    roll5 = rolling_average_by_dismissal(runs, dismissed, 5)
    roll10 = rolling_average_by_dismissal(runs, dismissed, 10)
    cum = 0
    for i, r in enumerate(rows):
        cum += r["runs"]
        r["cumulative_runs"] = cum
        r["innings_index"] = i + 1
        r["rolling_avg_5"] = roll5[i]
        r["rolling_avg_10"] = roll10[i]
        cum_out = sum(1 for x in dismissed[:i + 1] if x)
        r["career_average_to_date"] = ratio(cum, cum_out)
    totals = {k: sum(r[k] for r in rows) for k in ("runs", "balls", "fours", "sixes", "dots")}
    outs = sum(dismissed)
    summary = {
        "innings": len(rows), "not_outs": len(rows) - outs, "dismissals": outs, **totals,
        "highest_score": max(rows, key=lambda r: (r["runs"], not r["dismissed"]), default=None),
        "hundreds": sum(1 for x in runs if x >= 100), "fifties": sum(1 for x in runs if 50 <= x < 100),
        "runs_per_dismissal": ratio(totals["runs"], outs),
        **batting_rates(totals["runs"], totals["balls"], outs, totals["fours"], totals["sixes"], totals["dots"]),
        "boundary_runs_percentage": ratio(totals["fours"] * 4 + totals["sixes"] * 6, totals["runs"], 100),
    }
    if summary["highest_score"]:
        hs = summary["highest_score"]
        summary["highest_score"] = {"runs": hs["runs"], "not_out": not hs["dismissed"], "match_id": hs["match_id"],
                                    "opponent": hs["opponent"], "date": hs["start_date"]}

    seasons: Dict[str, dict] = {}
    for r in rows:
        s = seasons.setdefault(r["season"], {"season": r["season"], "innings": 0, "runs": 0, "balls": 0, "dismissals": 0,
                                             "fifties": 0, "hundreds": 0, "fours": 0, "sixes": 0})
        s["innings"] += 1; s["runs"] += r["runs"]; s["balls"] += r["balls"]; s["dismissals"] += int(r["dismissed"])
        s["fours"] += r["fours"]; s["sixes"] += r["sixes"]
        s["fifties"] += int(50 <= r["runs"] < 100); s["hundreds"] += int(r["runs"] >= 100)
    season_rows = []
    for s in sorted(seasons.values(), key=lambda x: x["season"]):
        season_rows.append({**s, "average": ratio(s["runs"], s["dismissals"]), "strike_rate": ratio(s["runs"], s["balls"], 100)})

    dismissal_counts: Dict[str, int] = defaultdict(int)
    for r in rows:
        if r["dismissal_type"]:
            dismissal_counts[r["dismissal_type"]] += 1
    pos_counts: Dict[int, dict] = {}
    for r in rows:
        if r["position"] is None:
            continue
        p = pos_counts.setdefault(int(r["position"]), {"position": int(r["position"]), "innings": 0, "runs": 0, "balls": 0, "dismissals": 0})
        p["innings"] += 1; p["runs"] += r["runs"]; p["balls"] += r["balls"]; p["dismissals"] += int(r["dismissed"])
    positions = [{**p, "average": ratio(p["runs"], p["dismissals"]), "strike_rate": ratio(p["runs"], p["balls"], 100)}
                 for p in sorted(pos_counts.values(), key=lambda x: x["position"])]

    faced = sum(int(s["balls"]) for s in scoring)
    dist = []
    for s in scoring:
        label = {0: "Dot", 1: "1", 2: "2", 3: "3", 4: "4", 5: "5", 6: "6+"}[int(s["runs_off_ball"])]
        dist.append({"outcome": label, "balls": int(s["balls"]), "percentage": ratio(int(s["balls"]), faced, 100),
                     "runs": int(s["runs_off_ball"]) * int(s["balls"]) if int(s["runs_off_ball"]) < 6 else None,
                     "boundary_fours": int(s["boundary_fours"]), "boundary_sixes": int(s["boundary_sixes"])})

    styles = []
    unclassified_balls = 0
    merged: Dict[str, dict] = {}
    for s in style_split:
        name = normalise_bowling_style(s["style"])
        if not name:
            unclassified_balls += int(s["balls"] or 0)
            continue
        m = merged.setdefault(name, {"style": name, "runs": 0, "balls": 0, "fours": 0, "sixes": 0, "dots": 0, "dismissals": 0})
        for k in ("runs", "balls", "fours", "sixes", "dots", "dismissals"):
            m[k] += int(s[k] or 0)
    for m in sorted(merged.values(), key=lambda x: -x["balls"]):
        styles.append({**m, **batting_rates(m["runs"], m["balls"], m["dismissals"], m["fours"], m["sixes"], m["dots"])})
    classified = sum(m["balls"] for m in merged.values())

    bin_width = 10 if (fmt or "").upper() in {"T20", "T20I"} else 10 if (fmt or "").upper() in {"ODI", "ODM"} else 20
    return {
        "summary": summary,
        "consistency": consistency_summary(runs, dismissed),
        "innings": rows,
        "seasons": season_rows,
        "scoring_distribution": {"balls_faced": faced, "outcomes": dist,
                                 "note": "Runs off the bat per faced ball. '4'/'6+' include all-run fours and fives/sevens; boundary counts are reported separately."},
        "dismissals": [{"type": k, "count": v, "percentage": ratio(v, outs, 100)} for k, v in sorted(dismissal_counts.items(), key=lambda x: -x[1])],
        "batting_positions": positions,
        "runs_histogram": histogram(runs, bin_width),
        "vs_bowling_style": {"styles": styles, "classified_balls": classified, "unclassified_balls": unclassified_balls,
                             "coverage_percentage": ratio(classified, classified + unclassified_balls, 100, 1),
                             "note": "Detailed styles come from CPI's stored bowler classifications. Deliveries from bowlers without a stored style are excluded and counted as unclassified. Dismissals count bowler-credited wickets only."},
    }


def _bowling_section(rows: List[dict], dismissals: List[dict], fmt: Optional[str]) -> dict:
    for r in rows:
        r["start_date"] = str(r["start_date"])
        for k in ("legal_balls", "runs", "dots", "boundaries", "fours", "sixes", "maidens", "wickets"):
            r[k] = int(r[k] or 0)
        r["overs"] = overs_display(r["legal_balls"])
        r["economy"] = ratio(r["runs"], r["legal_balls"], 6)
        r["figures"] = f"{r['wickets']}/{r['runs']}"
    economies = [r["economy"] for r in rows]
    roll_econ = rolling_mean(economies, 5)
    cum_w = 0
    for i, r in enumerate(rows):
        cum_w += r["wickets"]
        r["cumulative_wickets"] = cum_w
        r["innings_index"] = i + 1
        r["rolling_economy_5"] = roll_econ[i]
    t = {k: sum(r[k] for r in rows) for k in ("legal_balls", "runs", "dots", "boundaries", "fours", "sixes", "maidens", "wickets")}
    best = max(rows, key=lambda r: (r["wickets"], -r["runs"]), default=None)
    summary = {"innings": len(rows), **t, "overs": overs_display(t["legal_balls"]),
               **bowling_rates(t["runs"], t["legal_balls"], t["wickets"], t["dots"], t["boundaries"]),
               "wickets_per_innings": ratio(t["wickets"], len(rows)),
               "four_wicket_hauls": sum(1 for r in rows if r["wickets"] == 4),
               "five_wicket_hauls": sum(1 for r in rows if r["wickets"] >= 5),
               "best_figures": {"figures": best["figures"], "match_id": best["match_id"], "opponent": best["opponent"],
                                "date": best["start_date"]} if best and best["legal_balls"] else None}
    seasons: Dict[str, dict] = {}
    for r in rows:
        s = seasons.setdefault(r["season"], {"season": r["season"], "innings": 0, "legal_balls": 0, "runs": 0, "wickets": 0, "dots": 0, "boundaries": 0})
        s["innings"] += 1
        for k in ("legal_balls", "runs", "wickets", "dots", "boundaries"):
            s[k] += r[k]
    season_rows = [{**s, "overs": overs_display(s["legal_balls"]), **bowling_rates(s["runs"], s["legal_balls"], s["wickets"], s["dots"], s["boundaries"])}
                   for s in sorted(seasons.values(), key=lambda x: x["season"])]
    venues: Dict[str, dict] = {}
    for r in rows:
        if not r["venue_id"]:
            continue
        v = venues.setdefault(r["venue_id"], {"venue_id": r["venue_id"], "venue": r["venue"], "innings": 0, "legal_balls": 0, "runs": 0, "wickets": 0, "dots": 0, "boundaries": 0})
        v["innings"] += 1
        for k in ("legal_balls", "runs", "wickets", "dots", "boundaries"):
            v[k] += r[k]
    venue_rows = sorted(({**v, "overs": overs_display(v["legal_balls"]), **bowling_rates(v["runs"], v["legal_balls"], v["wickets"], v["dots"], v["boundaries"])}
                         for v in venues.values()), key=lambda x: -x["legal_balls"])[:15]
    wkt_dist: Dict[str, int] = defaultdict(int)
    for r in rows:
        wkt_dist["5+" if r["wickets"] >= 5 else str(r["wickets"])] += 1
    total_w = sum(int(d["wickets"]) for d in dismissals)
    width = 10 if (fmt or "").upper() in {"T20", "T20I", "ODI", "ODM"} else 20
    econ_valid = [e for e in economies if e is not None]
    return {
        "summary": summary,
        "innings": rows,
        "seasons": season_rows,
        "venues": venue_rows,
        "dismissal_types": [{"type": d["dismissal_type"], "count": int(d["wickets"]), "percentage": ratio(int(d["wickets"]), total_w, 100)} for d in dismissals],
        "wickets_per_innings_distribution": [{"wickets": k, "innings": wkt_dist.get(k, 0)} for k in ("0", "1", "2", "3", "4", "5+")] if rows else [],
        "runs_conceded_histogram": histogram([r["runs"] for r in rows], width),
        "consistency": {
            "innings": len(econ_valid),
            "economy_std_dev": consistency_summary(econ_valid).get("std_dev") if econ_valid else None,
            "innings_with_wicket_percentage": ratio(sum(1 for r in rows if r["wickets"] > 0), len(rows), 100, 1),
            "economy_under_6_percentage": ratio(sum(1 for e in econ_valid if e < 6), len(econ_valid), 100, 1),
            "economy_over_9_percentage": ratio(sum(1 for e in econ_valid if e > 9), len(econ_valid), 100, 1),
        },
        "note": "Bowling runs exclude byes and leg-byes. Maidens are overs of six legal balls by the bowler conceding no bowling runs.",
    }


# ------------------------------------------------------------------ player comparison

def _bat_cohort(db: Session, mf: str, params: dict) -> List[dict]:
    return _rows(db, f"""
    SELECT d.batter_id AS player_id, SUM(d.batter_runs) AS runs,
           SUM(CASE WHEN d.is_ball_faced_by_batter THEN 1 ELSE 0 END) AS balls,
           SUM(CASE WHEN d.is_boundary_four OR d.is_boundary_six THEN 1 ELSE 0 END) AS boundaries,
           SUM(CASE WHEN d.is_ball_faced_by_batter AND d.batter_runs = 0 THEN 1 ELSE 0 END) AS dots
    FROM deliveries d JOIN match_innings mi ON mi.id = d.innings_id JOIN matches m ON m.id = mi.match_id
    WHERE mi.is_super_over = FALSE AND {mf} GROUP BY d.batter_id
    """, params)


def _bowl_cohort(db: Session, mf: str, params: dict) -> List[dict]:
    return _rows(db, f"""
    SELECT d.bowler_id AS player_id, SUM(d.bowling_runs) AS runs,
           SUM(CASE WHEN d.is_legal_ball THEN 1 ELSE 0 END) AS balls,
           SUM(CASE WHEN d.is_legal_ball AND d.bowling_runs = 0 THEN 1 ELSE 0 END) AS dots,
           SUM(CASE WHEN d.is_boundary_four OR d.is_boundary_six THEN 1 ELSE 0 END) AS boundaries
    FROM deliveries d JOIN match_innings mi ON mi.id = d.innings_id JOIN matches m ON m.id = mi.match_id
    WHERE mi.is_super_over = FALSE AND {mf} GROUP BY d.bowler_id
    """, params)


def _dismissal_counts(db: Session, mf: str, params: dict, credited_only: bool) -> Dict[str, int]:
    col = "d.bowler_id" if credited_only else "w.player_out_id"
    cond = "w.is_bowler_wicket = TRUE" if credited_only else "w.is_batter_dismissed = TRUE"
    return {r["pid"]: int(r["n"]) for r in _rows(db, f"""
    SELECT {col} AS pid, COUNT(*) AS n FROM wickets w JOIN deliveries d ON d.id = w.delivery_id
    JOIN match_innings mi ON mi.id = d.innings_id JOIN matches m ON m.id = mi.match_id
    WHERE {cond} AND mi.is_super_over = FALSE AND {mf} GROUP BY 1
    """, params) if r["pid"]}


@router.get("/players/compare/metrics")
def compare_players(
    ids: str = Query(..., description="Comma-separated player ids (2-4)"),
    format: str = Query("T20"),
    gender: Optional[str] = None,
    competition: Optional[str] = None,
    start_year: Optional[int] = None,
    end_year: Optional[int] = None,
    min_balls: int = Query(300, ge=30, le=5000, description="Minimum balls for the percentile cohort"),
    db: Session = Depends(get_db),
):
    """Rate-normalised batting and bowling metrics for 2-4 players with cohort percentiles.

    Percentiles rank each player against every player in the same format and
    filters with at least ``min_balls`` balls faced (batting) or bowled (bowling)."""
    pids = [p for p in dict.fromkeys(x.strip() for x in ids.split(",")) if p]
    if not 1 <= len(pids) <= 4:
        raise HTTPException(status_code=422, detail="Compare between one and four players.")
    params: dict = {}
    mf = _match_filters(params, format=format, gender=gender, competition=competition, start_year=start_year, end_year=end_year)
    key = ("compare-cohort", format, gender, competition, start_year, end_year)

    def build():
        bat = _bat_cohort(db, mf, dict(params))
        bowl = _bowl_cohort(db, mf, dict(params))
        outs = _dismissal_counts(db, mf, dict(params), credited_only=False)
        wkts = _dismissal_counts(db, mf, dict(params), credited_only=True)
        return bat, bowl, outs, wkts
    bat, bowl, outs, wkts = _cached(key, build)

    def bat_metrics(r):
        runs, balls, d = int(r["runs"]), int(r["balls"]), outs.get(r["player_id"], 0)
        return {"runs": runs, "balls": balls, "dismissals": d, "average": ratio(runs, d), "strike_rate": ratio(runs, balls, 100),
                "boundary_percentage": ratio(int(r["boundaries"]), balls, 100), "dot_percentage": ratio(int(r["dots"]), balls, 100),
                "balls_per_dismissal": ratio(balls, d, 1, 1)}

    def bowl_metrics(r):
        runs, balls, w = int(r["runs"]), int(r["balls"]), wkts.get(r["player_id"], 0)
        return {"runs": runs, "legal_balls": balls, "overs": overs_display(balls), "wickets": w, **bowling_rates(runs, balls, w, int(r["dots"]), int(r["boundaries"]))}

    bat_cohort = {r["player_id"]: bat_metrics(r) for r in bat if r["player_id"] and int(r["balls"]) >= min_balls}
    bowl_cohort = {r["player_id"]: bowl_metrics(r) for r in bowl if r["player_id"] and int(r["balls"]) >= min_balls}
    bat_by = {r["player_id"]: r for r in bat}
    bowl_by = {r["player_id"]: r for r in bowl}
    bat_keys = [("average", False), ("strike_rate", False), ("boundary_percentage", False), ("dot_percentage", True), ("balls_per_dismissal", False)]
    bowl_keys = [("economy", True), ("average", True), ("strike_rate", True), ("dot_percentage", False), ("boundary_percentage", True)]
    bat_pops = {k: [m[k] for m in bat_cohort.values()] for k, _ in bat_keys}
    bowl_pops = {k: [m[k] for m in bowl_cohort.values()] for k, _ in bowl_keys}

    names = {r["id"]: r["canonical_name"] for r in _rows(db, "SELECT id, canonical_name FROM players WHERE id = ANY(:ids)", {"ids": pids})}
    phase_rows = _rows(db, f"""
    SELECT d.batter_id AS pid, 'batting' AS side, d.phase, SUM(d.batter_runs) AS runs,
           SUM(CASE WHEN d.is_ball_faced_by_batter THEN 1 ELSE 0 END) AS balls
    FROM deliveries d JOIN match_innings mi ON mi.id = d.innings_id JOIN matches m ON m.id = mi.match_id
    WHERE d.batter_id = ANY(:ids) AND mi.is_super_over = FALSE AND {mf} AND d.phase IN ('powerplay','middle','death')
    GROUP BY 1, 2, 3
    UNION ALL
    SELECT d.bowler_id, 'bowling', d.phase, SUM(d.bowling_runs), SUM(CASE WHEN d.is_legal_ball THEN 1 ELSE 0 END)
    FROM deliveries d JOIN match_innings mi ON mi.id = d.innings_id JOIN matches m ON m.id = mi.match_id
    WHERE d.bowler_id = ANY(:ids) AND mi.is_super_over = FALSE AND {mf} AND d.phase IN ('powerplay','middle','death')
    GROUP BY 1, 2, 3
    """, {**params, "ids": pids})
    pace_rows = _rows(db, f"""
    SELECT d.batter_id AS pid, LOWER(pa.attribute_value) AS bowling_type, SUM(d.batter_runs) AS runs,
           SUM(CASE WHEN d.is_ball_faced_by_batter THEN 1 ELSE 0 END) AS balls,
           COUNT(w.id) AS dismissals
    FROM deliveries d JOIN match_innings mi ON mi.id = d.innings_id JOIN matches m ON m.id = mi.match_id
    JOIN player_attributes pa ON pa.player_id = d.bowler_id AND pa.attribute_type = 'bowling_type'
    LEFT JOIN wickets w ON w.delivery_id = d.id AND w.player_out_id = d.batter_id AND w.is_batter_dismissed = TRUE AND w.is_bowler_wicket = TRUE
    WHERE d.batter_id = ANY(:ids) AND mi.is_super_over = FALSE AND {mf}
    GROUP BY 1, 2
    """, {**params, "ids": pids})
    season_rows = _rows(db, f"""
    SELECT d.batter_id AS pid, 'batting' AS side, m.season, SUM(d.batter_runs) AS runs,
           SUM(CASE WHEN d.is_ball_faced_by_batter THEN 1 ELSE 0 END) AS balls
    FROM deliveries d JOIN match_innings mi ON mi.id = d.innings_id JOIN matches m ON m.id = mi.match_id
    WHERE d.batter_id = ANY(:ids) AND mi.is_super_over = FALSE AND {mf} GROUP BY 1, 2, 3
    UNION ALL
    SELECT d.bowler_id, 'bowling', m.season, SUM(d.bowling_runs), SUM(CASE WHEN d.is_legal_ball THEN 1 ELSE 0 END)
    FROM deliveries d JOIN match_innings mi ON mi.id = d.innings_id JOIN matches m ON m.id = mi.match_id
    WHERE d.bowler_id = ANY(:ids) AND mi.is_super_over = FALSE AND {mf} GROUP BY 1, 2, 3
    """, {**params, "ids": pids})

    players = []
    for pid in pids:
        b = bat_metrics(bat_by[pid]) if pid in bat_by else None
        w = bowl_metrics(bowl_by[pid]) if pid in bowl_by else None
        players.append({
            "player_id": pid, "player_name": names.get(pid, "Unknown player"),
            "batting": b, "bowling": w,
            # Percentiles are only meaningful for players who meet the cohort minimum themselves.
            "batting_percentiles": {k: percentile_rank(b[k], bat_pops[k], low) for k, low in bat_keys} if b and b["balls"] >= min_balls else None,
            "bowling_percentiles": {k: percentile_rank(w[k], bowl_pops[k], low) for k, low in bowl_keys} if w and w["legal_balls"] >= min_balls else None,
            "batting_below_cohort_minimum": bool(b and b["balls"] < min_balls),
            "bowling_below_cohort_minimum": bool(w and w["legal_balls"] < min_balls),
            "phases": [{"side": r["side"], "phase": r["phase"], "runs": int(r["runs"]), "balls": int(r["balls"]),
                        "rate": ratio(int(r["runs"]), int(r["balls"]), 100 if r["side"] == "batting" else 6)}
                       for r in phase_rows if r["pid"] == pid],
            "pace_spin": [{"bowling_type": r["bowling_type"].capitalize(), "runs": int(r["runs"]), "balls": int(r["balls"]),
                           "dismissals": int(r["dismissals"]), "strike_rate": ratio(int(r["runs"]), int(r["balls"]), 100),
                           "average": ratio(int(r["runs"]), int(r["dismissals"]))}
                          for r in pace_rows if r["pid"] == pid and r["bowling_type"] in ("pace", "spin")],
            "seasons": sorted([{"side": r["side"], "season": r["season"], "runs": int(r["runs"]), "balls": int(r["balls"]),
                                "rate": ratio(int(r["runs"]), int(r["balls"]), 100 if r["side"] == "batting" else 6)}
                               for r in season_rows if r["pid"] == pid], key=lambda x: x["season"]),
        })
    return {
        "format": format,
        "filters": {"gender": gender, "competition": competition, "start_year": start_year, "end_year": end_year},
        "cohort": {"min_balls": min_balls, "batters": len(bat_cohort), "bowlers": len(bowl_cohort)},
        "players": players,
        "scatter": {
            "batting": [{"player_id": pid, "average": m["average"], "strike_rate": m["strike_rate"], "balls": m["balls"]}
                        for pid, m in bat_cohort.items() if m["average"] is not None],
            "bowling": [{"player_id": pid, "economy": m["economy"], "strike_rate": m["strike_rate"], "legal_balls": m["legal_balls"]}
                        for pid, m in bowl_cohort.items() if m["strike_rate"] is not None],
        },
        "method": "Percentile = share of the cohort the player beats (ties count half). Lower-is-better metrics (economy, bowling average/strike rate, batting dot %, boundary % conceded) are inverted so 100 is always best. Phase and season rates: batting = runs per 100 balls; bowling = runs per over.",
    }


# ------------------------------------------------------------------------- teams

def _innings_totals_sql(mf: str) -> str:
    return f"""
    SELECT mi.id AS innings_id, mi.match_id, mi.innings_number, mi.batting_team_id, mi.target_overs,
           m.season, m.start_date, m.match_format, m.winner_id, m.result_type, m.team1_id, m.team2_id, m.venue_id,
           m.result_margin_runs, m.result_margin_wickets,
           SUM(d.total_runs) AS runs,
           SUM(CASE WHEN d.is_legal_ball THEN 1 ELSE 0 END) AS legal_balls,
           (SELECT COUNT(*) FROM wickets w JOIN deliveries d2 ON d2.id = w.delivery_id
             WHERE d2.innings_id = mi.id AND w.is_batter_dismissed = TRUE) AS wickets
    FROM matches m JOIN match_innings mi ON mi.match_id = m.id JOIN deliveries d ON d.innings_id = mi.id
    WHERE mi.is_super_over = FALSE AND {mf}
    GROUP BY mi.id, m.id
    """


@router.get("/teams/{team_id}/analytics")
def team_analytics(
    team_id: str,
    format: str = Query("T20"),
    gender: Optional[str] = None,
    competition: Optional[str] = None,
    start_year: Optional[int] = None,
    end_year: Optional[int] = None,
    vs_team_id: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Innings scoring, phase batting/bowling and season trends for one team in one format."""
    team = db.execute(text("SELECT id, canonical_name FROM teams WHERE id = :t"), {"t": team_id}).first()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    params: dict = {"tid": team_id}
    mf = _match_filters(params, format=format, gender=gender, competition=competition, start_year=start_year,
                        end_year=end_year, vs_team_id=vs_team_id)
    mf += " AND (:tid IN (m.team1_id, m.team2_id))"
    innings = _rows(db, _innings_totals_sql(mf), params)
    quota = FORMAT_INNINGS_BALLS.get(format)
    by_match: Dict[str, List[dict]] = defaultdict(list)
    for r in innings:
        r["runs"], r["legal_balls"], r["wickets"] = int(r["runs"]), int(r["legal_balls"]), int(r["wickets"])
        by_match[r["match_id"]].append(r)
    batting_first, chasing, conceded = [], [], []
    seasons: Dict[str, dict] = {}
    margins = {"won_by_runs": [], "won_by_wickets": [], "lost_by_runs": [], "lost_by_wickets": []}
    for mid, rows in by_match.items():
        rows.sort(key=lambda r: r["innings_number"])
        first = rows[0]
        ours = [r for r in rows if r["batting_team_id"] == team_id]
        theirs = [r for r in rows if r["batting_team_id"] != team_id]
        s = seasons.setdefault(first["season"], {"season": first["season"], "matches": 0, "won": 0, "lost": 0, "other": 0,
                                                 "runs_for": 0, "balls_for": 0, "wkts_lost": 0, "runs_against": 0, "balls_against": 0, "wkts_taken": 0})
        s["matches"] += 1
        if first["winner_id"] == team_id:
            s["won"] += 1
        elif first["winner_id"]:
            s["lost"] += 1
        else:
            s["other"] += 1
        for r in ours:
            s["runs_for"] += r["runs"]; s["balls_for"] += r["legal_balls"]; s["wkts_lost"] += r["wickets"]
        for r in theirs:
            s["runs_against"] += r["runs"]; s["balls_against"] += r["legal_balls"]; s["wkts_taken"] += r["wickets"]
            conceded.append(r["runs"])
        if format in FORMAT_INNINGS_BALLS:  # first/chasing split is only meaningful in two-innings limited-overs games
            for r in ours:
                (batting_first if r["innings_number"] == 1 else chasing if r["innings_number"] == 2 else []).append(r)
        won = first["winner_id"] == team_id
        lost = first["winner_id"] and not won
        if won or lost:
            pre = "won" if won else "lost"
            if first["result_margin_runs"]:
                margins[f"{pre}_by_runs"].append(int(first["result_margin_runs"]))
            elif first["result_margin_wickets"]:
                margins[f"{pre}_by_wickets"].append(int(first["result_margin_wickets"]))

    def avg(rows):
        return ratio(sum(r["runs"] for r in rows), len(rows), 1, 1)
    ours_all = [r for r in innings if r["batting_team_id"] == team_id]
    theirs_all = [r for r in innings if r["batting_team_id"] != team_id]
    tot = lambda rows, k: sum(r[k] for r in rows)
    decided_first = [r for r in batting_first if r["winner_id"]]
    decided_chase = [r for r in chasing if r["winner_id"]]
    summary = {
        "matches": len(by_match),
        "won": sum(s["won"] for s in seasons.values()), "lost": sum(s["lost"] for s in seasons.values()),
        "no_decision": sum(s["other"] for s in seasons.values()),
        "batting_average": ratio(tot(ours_all, "runs"), tot(ours_all, "wickets")),
        "bowling_average": ratio(tot(theirs_all, "runs"), tot(theirs_all, "wickets")),
        "run_rate": ratio(tot(ours_all, "runs"), tot(ours_all, "legal_balls"), 6),
        "economy": ratio(tot(theirs_all, "runs"), tot(theirs_all, "legal_balls"), 6),
        "average_first_innings_score": avg(batting_first), "first_innings_sample": len(batting_first),
        "average_chasing_score": avg(chasing), "chasing_sample": len(chasing),
        "batting_first_win_percentage": ratio(sum(1 for r in decided_first if r["winner_id"] == team_id), len(decided_first), 100, 1),
        "chasing_win_percentage": ratio(sum(1 for r in decided_chase if r["winner_id"] == team_id), len(decided_chase), 100, 1),
        "highest_total": max((r["runs"] for r in ours_all), default=None),
        "lowest_all_out_total": min((r["runs"] for r in ours_all if r["wickets"] >= 10), default=None),
    }
    summary["win_percentage"] = ratio(summary["won"], summary["won"] + summary["lost"], 100, 1)

    phase = _rows(db, f"""
    SELECT CASE WHEN mi.batting_team_id = :tid THEN 'batting' ELSE 'bowling' END AS side, d.phase,
           SUM(d.total_runs) AS runs, SUM(CASE WHEN d.is_legal_ball THEN 1 ELSE 0 END) AS balls,
           SUM(CASE WHEN d.is_legal_ball AND d.total_runs = 0 THEN 1 ELSE 0 END) AS dots,
           SUM(CASE WHEN d.is_boundary_four OR d.is_boundary_six THEN 1 ELSE 0 END) AS boundaries,
           COUNT(w.id) AS wickets, COUNT(DISTINCT mi.id) AS innings
    FROM matches m JOIN match_innings mi ON mi.match_id = m.id JOIN deliveries d ON d.innings_id = mi.id
    LEFT JOIN wickets w ON w.delivery_id = d.id AND w.is_batter_dismissed = TRUE
    WHERE mi.is_super_over = FALSE AND d.phase IN ('powerplay','middle','death') AND {mf}
    GROUP BY 1, 2
    """, params)
    base_params: dict = {}
    base_mf = _match_filters(base_params, format=format, gender=gender, competition=competition, start_year=start_year, end_year=end_year)
    baseline = _cached(("phase-baseline", format, gender, competition, start_year, end_year), lambda: _rows(db, f"""
    SELECT d.phase, SUM(d.total_runs) AS runs, SUM(CASE WHEN d.is_legal_ball THEN 1 ELSE 0 END) AS balls,
           COUNT(w.id) AS wickets
    FROM matches m JOIN match_innings mi ON mi.match_id = m.id JOIN deliveries d ON d.innings_id = mi.id
    LEFT JOIN wickets w ON w.delivery_id = d.id AND w.is_batter_dismissed = TRUE
    WHERE mi.is_super_over = FALSE AND d.phase IN ('powerplay','middle','death') AND {base_mf}
    GROUP BY 1
    """, base_params))
    base_by = {b["phase"]: b for b in baseline}
    phases = []
    for r in phase:
        runs, balls, wk = int(r["runs"]), int(r["balls"]), int(r["wickets"])
        b = base_by.get(r["phase"])
        base_rr = ratio(int(b["runs"]), int(b["balls"]), 6) if b else None
        rr = ratio(runs, balls, 6)
        phases.append({"side": r["side"], "phase": r["phase"], "innings": int(r["innings"]), "runs": runs, "legal_balls": balls,
                       "overs": overs_display(balls), "wickets": wk, "run_rate": rr,
                       "runs_per_wicket": ratio(runs, wk), "balls_per_wicket": ratio(balls, wk, 1, 1),
                       "dot_percentage": ratio(int(r["dots"]), balls, 100), "boundary_percentage": ratio(int(r["boundaries"]), balls, 100),
                       "format_run_rate": base_rr,
                       "run_rate_delta": round(rr - base_rr, 2) if rr is not None and base_rr is not None else None})
    order = {"powerplay": 0, "middle": 1, "death": 2}
    phases.sort(key=lambda p: (p["side"], order.get(p["phase"], 9)))
    strengths, weaknesses = [], []
    for p in phases:
        if p["run_rate_delta"] is None or p["legal_balls"] < 300:
            continue
        good = p["run_rate_delta"] > 0 if p["side"] == "batting" else p["run_rate_delta"] < 0
        if abs(p["run_rate_delta"]) < 0.25:
            continue
        text_ = (f"{p['side'].capitalize()} in the {p['phase']} overs: {p['run_rate']:.2f} runs/over vs "
                 f"{p['format_run_rate']:.2f} across all {format} sides in the same filters ({p['overs']} overs sample).")
        (strengths if good else weaknesses).append(text_)

    season_rows = []
    for s in sorted(seasons.values(), key=lambda x: x["season"]):
        season_rows.append({"season": s["season"], "matches": s["matches"], "won": s["won"], "lost": s["lost"], "no_decision": s["other"],
                            "win_percentage": ratio(s["won"], s["won"] + s["lost"], 100, 1),
                            "run_rate": ratio(s["runs_for"], s["balls_for"], 6), "economy": ratio(s["runs_against"], s["balls_against"], 6),
                            "batting_average": ratio(s["runs_for"], s["wkts_lost"]), "bowling_average": ratio(s["runs_against"], s["wkts_taken"])})
    width = 20 if format in ("T20", "T20I") else 25 if format in ("ODI", "ODM") else 50
    return {
        "team_id": team_id, "team_name": team.canonical_name, "format": format,
        "filters": {"gender": gender, "competition": competition, "start_year": start_year, "end_year": end_year, "vs_team_id": vs_team_id},
        "summary": summary,
        "phases": phases,
        "strengths": strengths, "weaknesses": weaknesses,
        "seasons": season_rows,
        "score_distribution": {"bin_width": width, "scored": histogram([r["runs"] for r in ours_all], width),
                               "conceded": histogram(conceded, width), "innings_sample": len(ours_all), "conceded_sample": len(conceded)},
        "margins": {k: histogram(v, 10 if "runs" in k else 1, 0 if "runs" in k else 1) for k, v in margins.items()},
        "margin_samples": {k: len(v) for k, v in margins.items()},
        "notes": [
            "Totals are reconstructed from deliveries; super overs are excluded.",
            "Batting/bowling averages are team runs per wicket lost/taken (all dismissals that end a batter's innings).",
            "Phase comparisons use the same format and filters across all teams; a phase needs 50+ overs to be listed as a strength or weakness and a gap of at least 0.25 runs/over.",
            "Shortened (rain-affected) innings are included in averages and distributions.",
        ],
    }


# -------------------------------------------------------------------- tournaments

@router.get("/tournaments")
def list_tournaments(gender: Optional[str] = None, format: Optional[str] = None, db: Session = Depends(get_db)):
    params: dict = {}
    conds = ["1=1"]
    if gender:
        conds.append("LOWER(m.gender) = :gender"); params["gender"] = gender.lower()
    if format:
        conds.append("m.match_format = :format"); params["format"] = format
    rows = _rows(db, f"""
    SELECT t.name, LOWER(m.gender) AS gender, m.match_format AS format, COUNT(*) AS matches,
           MIN(m.start_date) AS first_match, MAX(m.start_date) AS last_match,
           (ARRAY_AGG(m.id ORDER BY m.start_date DESC, m.id))[1] AS last_match_id,
           ARRAY_AGG(DISTINCT m.season) AS seasons
    FROM matches m JOIN tournaments t ON t.id = m.tournament_id
    WHERE {' AND '.join(conds)}
    GROUP BY t.name, LOWER(m.gender), m.match_format
    HAVING COUNT(*) >= 5
    ORDER BY COUNT(*) DESC
    """, params)
    for r in rows:
        r["seasons"] = sorted(r["seasons"], reverse=True)
        r["first_match"], r["last_match"] = str(r["first_match"]), str(r["last_match"])
    return {"tournaments": rows}


@router.get("/tournaments/detail")
def tournament_detail(
    name: str = Query(..., max_length=200),
    format: str = Query(...),
    gender: str = Query("male"),
    season: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Season standings, leaders, venue breakdown and season-by-season scoring for one competition."""
    params: dict = {"tname": name, "format": format, "gender": gender.lower()}
    base = "m.tournament_id IN (SELECT id FROM tournaments WHERE name = :tname) AND m.match_format = :format AND LOWER(m.gender) = :gender"
    seasons = [r["season"] for r in _rows(db, f"SELECT DISTINCT m.season FROM matches m WHERE {base} ORDER BY 1 DESC", params)]
    if not seasons:
        raise HTTPException(status_code=404, detail="No matches stored for this competition.")
    season = season or seasons[0]
    if season not in seasons:
        raise HTTPException(status_code=404, detail="Season not found for this competition.")

    def compute_overview():
        return _rows(db, f"""
        WITH inn AS (
            SELECT m.id AS match_id, m.season, mi.innings_number, SUM(d.total_runs) AS runs,
                   SUM(CASE WHEN d.is_legal_ball THEN 1 ELSE 0 END) AS balls,
                   SUM(CASE WHEN d.is_boundary_six THEN 1 ELSE 0 END) AS sixes,
                   SUM(CASE WHEN d.is_boundary_four THEN 1 ELSE 0 END) AS fours
            FROM matches m JOIN match_innings mi ON mi.match_id = m.id JOIN deliveries d ON d.innings_id = mi.id
            WHERE {base} AND mi.is_super_over = FALSE GROUP BY m.id, m.season, mi.innings_number
        ), wk AS (
            SELECT m.season, COUNT(*) AS wickets FROM matches m JOIN match_innings mi ON mi.match_id = m.id
            JOIN deliveries d ON d.innings_id = mi.id JOIN wickets w ON w.delivery_id = d.id
            WHERE {base} AND mi.is_super_over = FALSE AND w.is_batter_dismissed = TRUE GROUP BY m.season
        )
        SELECT inn.season, COUNT(DISTINCT inn.match_id) AS matches,
               AVG(CASE WHEN innings_number = 1 THEN runs END) AS avg_first_innings,
               AVG(CASE WHEN innings_number = 2 THEN runs END) AS avg_second_innings,
               SUM(runs) AS runs, SUM(balls) AS balls, SUM(sixes) AS sixes, SUM(fours) AS fours,
               MAX(wk.wickets) AS wickets, MAX(runs) AS highest_total,
               (ARRAY_AGG(inn.match_id ORDER BY runs DESC))[1] AS highest_total_match_id
        FROM inn LEFT JOIN wk ON wk.season = inn.season GROUP BY inn.season ORDER BY inn.season
        """, params)
    overview = _cached(("tournament-overview", name, format, gender.lower()), compute_overview)
    season_trends = [{"season": r["season"], "matches": int(r["matches"]),
                      "average_first_innings": round(float(r["avg_first_innings"]), 1) if r["avg_first_innings"] is not None else None,
                      "average_second_innings": round(float(r["avg_second_innings"]), 1) if r["avg_second_innings"] is not None else None,
                      "run_rate": ratio(int(r["runs"]), int(r["balls"]), 6),
                      "sixes_per_match": ratio(int(r["sixes"]), int(r["matches"]), 1, 1),
                      "fours_per_match": ratio(int(r["fours"]), int(r["matches"]), 1, 1),
                      "wickets_per_match": ratio(int(r["wickets"] or 0), int(r["matches"]), 1, 1),
                      "highest_total": int(r["highest_total"]) if r["highest_total"] is not None else None,
                      "highest_total_match_id": r.get("highest_total_match_id")} for r in overview]

    sp = {**params, "season": season}
    sbase = base + " AND m.season = :season"
    innings = _rows(db, _innings_totals_sql(sbase), sp)
    team_names = {r["id"]: r["canonical_name"] for r in _rows(db, f"""
        SELECT t.id, t.canonical_name FROM teams t WHERE t.id IN (
          SELECT team1_id FROM matches m WHERE {sbase} UNION SELECT team2_id FROM matches m WHERE {sbase})""", sp)}
    quota = FORMAT_INNINGS_BALLS.get(format)
    by_match: Dict[str, List[dict]] = defaultdict(list)
    for r in innings:
        by_match[r["match_id"]].append(r)
    results, matches_out = [], []
    h2h: Dict[tuple, dict] = {}
    match_meta = {r["id"]: r for r in _rows(db, f"""
        SELECT m.id, m.start_date, m.team1_id, m.team2_id, m.winner_id, m.result_type, m.result_margin_runs,
               m.result_margin_wickets, v.canonical_name AS venue, v.id AS venue_id
        FROM matches m LEFT JOIN venues v ON v.id = m.venue_id WHERE {sbase} ORDER BY m.start_date""", sp)}
    for mid, meta in match_meta.items():
        rows = sorted(by_match.get(mid, []), key=lambda r: r["innings_number"])
        teams = [t for t in (meta["team1_id"], meta["team2_id"]) if t]
        rt = (meta["result_type"] or "").lower()
        for t in teams:
            opp = next((o for o in teams if o != t), None)
            mine = [r for r in rows if r["batting_team_id"] == t]
            theirs = [r for r in rows if r["batting_team_id"] == opp]
            outcome = ("won" if meta["winner_id"] == t else "lost") if meta["winner_id"] else "tied" if rt == "tie" else "no_result"
            # Limited-overs NRR: all-out innings count as the full quota (DLS-revised quota when stored for the chase).
            def balls_for(rs):
                return sum(nrr_balls(int(r["legal_balls"]), int(r["wickets"]), (int(r["target_overs"]) * 6 if r["target_overs"] else quota)) for r in rs)
            results.append({"team_id": t, "team": team_names.get(t, "Unknown"), "outcome": outcome,
                            "runs_for": sum(int(r["runs"]) for r in mine), "balls_for": balls_for(mine),
                            "runs_against": sum(int(r["runs"]) for r in theirs), "balls_against": balls_for(theirs)})
            if opp:
                cell = h2h.setdefault((t, opp), {"team_id": t, "opponent_id": opp, "won": 0, "lost": 0, "other": 0})
                cell["won" if outcome == "won" else "lost" if outcome == "lost" else "other"] += 1
        matches_out.append({
            "match_id": mid, "date": str(meta["start_date"]), "venue": meta["venue"],
            "team1": team_names.get(meta["team1_id"]), "team2": team_names.get(meta["team2_id"]),
            "winner": team_names.get(meta["winner_id"]), "result_type": meta["result_type"],
            "margin": f"{meta['result_margin_runs']} runs" if meta["result_margin_runs"] else f"{meta['result_margin_wickets']} wickets" if meta["result_margin_wickets"] else None,
            "innings": [{"team": team_names.get(r["batting_team_id"]), "runs": int(r["runs"]), "wickets": int(r["wickets"]),
                         "overs": overs_display(int(r["legal_balls"]))} for r in rows],
        })
    standings = build_standings(results)

    batters = _rows(db, f"""
    WITH per_inn AS (
        SELECT d.batter_id, d.innings_id, MIN(mi.match_id) AS match_id, SUM(d.batter_runs) AS runs,
               SUM(CASE WHEN d.is_ball_faced_by_batter THEN 1 ELSE 0 END) AS balls,
               SUM(CASE WHEN d.is_boundary_four THEN 1 ELSE 0 END) AS fours,
               SUM(CASE WHEN d.is_boundary_six THEN 1 ELSE 0 END) AS sixes
        FROM matches m JOIN match_innings mi ON mi.match_id = m.id JOIN deliveries d ON d.innings_id = mi.id
        WHERE {sbase} AND mi.is_super_over = FALSE GROUP BY d.batter_id, d.innings_id
    ), outs AS (
        SELECT w.player_out_id AS pid, COUNT(*) AS n FROM matches m JOIN match_innings mi ON mi.match_id = m.id
        JOIN deliveries d ON d.innings_id = mi.id JOIN wickets w ON w.delivery_id = d.id
        WHERE {sbase} AND mi.is_super_over = FALSE AND w.is_batter_dismissed = TRUE GROUP BY 1
    )
    SELECT p.id AS player_id, p.canonical_name AS player, COUNT(*) AS innings, SUM(runs) AS runs, SUM(balls) AS balls,
           SUM(fours) AS fours, SUM(sixes) AS sixes, MAX(runs) AS highest,
           (ARRAY_AGG(per_inn.match_id ORDER BY runs DESC))[1] AS highest_match_id, SUM(CASE WHEN runs >= 50 AND runs < 100 THEN 1 ELSE 0 END) AS fifties,
           SUM(CASE WHEN runs >= 100 THEN 1 ELSE 0 END) AS hundreds, COALESCE(MAX(o.n), 0) AS dismissals
    FROM per_inn JOIN players p ON p.id = per_inn.batter_id LEFT JOIN outs o ON o.pid = p.id
    GROUP BY p.id, p.canonical_name ORDER BY SUM(runs) DESC LIMIT 20
    """, sp)
    for b in batters:
        for k in ("innings", "runs", "balls", "fours", "sixes", "highest", "fifties", "hundreds", "dismissals"):
            b[k] = int(b[k])
        b["average"] = ratio(b["runs"], b["dismissals"]); b["strike_rate"] = ratio(b["runs"], b["balls"], 100)

    bowlers = _rows(db, f"""
    WITH per_inn AS (
        SELECT d.bowler_id, d.innings_id, MIN(mi.match_id) AS match_id, SUM(d.bowling_runs) AS runs,
               SUM(CASE WHEN d.is_legal_ball THEN 1 ELSE 0 END) AS balls,
               SUM(CASE WHEN d.is_legal_ball AND d.bowling_runs = 0 THEN 1 ELSE 0 END) AS dots
        FROM matches m JOIN match_innings mi ON mi.match_id = m.id JOIN deliveries d ON d.innings_id = mi.id
        WHERE {sbase} AND mi.is_super_over = FALSE GROUP BY d.bowler_id, d.innings_id
    ), wk AS (
        SELECT d.bowler_id, d.innings_id, COUNT(*) AS wickets FROM matches m JOIN match_innings mi ON mi.match_id = m.id
        JOIN deliveries d ON d.innings_id = mi.id JOIN wickets w ON w.delivery_id = d.id
        WHERE {sbase} AND mi.is_super_over = FALSE AND w.is_bowler_wicket = TRUE GROUP BY 1, 2
    ), joined AS (
        SELECT pi.*, COALESCE(wk.wickets, 0) AS wickets FROM per_inn pi
        LEFT JOIN wk ON wk.bowler_id = pi.bowler_id AND wk.innings_id = pi.innings_id
    )
    SELECT p.id AS player_id, p.canonical_name AS player, COUNT(*) AS innings, SUM(wickets) AS wickets, SUM(runs) AS runs,
           SUM(balls) AS balls, SUM(dots) AS dots,
           (ARRAY_AGG(wickets || '/' || runs ORDER BY wickets DESC, runs ASC))[1] AS best,
           (ARRAY_AGG(joined.match_id ORDER BY wickets DESC, runs ASC))[1] AS best_match_id
    FROM joined JOIN players p ON p.id = joined.bowler_id
    GROUP BY p.id, p.canonical_name ORDER BY SUM(wickets) DESC, SUM(runs) * 1.0 / NULLIF(SUM(balls), 0) ASC LIMIT 20
    """, sp)
    for b in bowlers:
        for k in ("innings", "wickets", "runs", "balls", "dots"):
            b[k] = int(b[k])
        b["overs"] = overs_display(b["balls"])
        b.update({k: v for k, v in bowling_rates(b["runs"], b["balls"], b["wickets"], b["dots"]).items() if k != "boundary_percentage"})

    venues: Dict[str, dict] = {}
    first_bat = {mid: sorted(rows, key=lambda r: r["innings_number"])[0] for mid, rows in by_match.items() if rows}
    for mid, meta in match_meta.items():
        if not meta["venue_id"]:
            continue
        v = venues.setdefault(meta["venue_id"], {"venue_id": meta["venue_id"], "venue": meta["venue"], "matches": 0, "first_totals": [], "bat_first_wins": 0, "decided": 0})
        v["matches"] += 1
        f = first_bat.get(mid)
        if f:
            v["first_totals"].append(int(f["runs"]))
            if meta["winner_id"]:
                v["decided"] += 1
                v["bat_first_wins"] += int(meta["winner_id"] == f["batting_team_id"])
    venue_rows = sorted(({"venue_id": v["venue_id"], "venue": v["venue"], "matches": v["matches"],
                          "average_first_innings": ratio(sum(v["first_totals"]), len(v["first_totals"]), 1, 1),
                          "batting_first_win_percentage": ratio(v["bat_first_wins"], v["decided"], 100, 1), "decided": v["decided"]}
                         for v in venues.values()), key=lambda x: -x["matches"])

    team_ids = sorted({r["team_id"] for r in standings}, key=lambda t: next(s["position"] for s in standings if s["team_id"] == t))
    return {
        "name": name, "format": format, "gender": gender.lower(), "season": season, "seasons": seasons,
        "standings": standings,
        "standings_note": "Results table from every stored match in the season, including any knockout games (Cricsheet stage data is not stored). Points use 2 per win and 1 per tie/no result; NRR treats all-out innings as the full quota of overs. Official tables may differ.",
        "matches": matches_out,
        "leading_batters": batters, "leading_bowlers": bowlers,
        "venues": venue_rows,
        "head_to_head": {"teams": [{"team_id": t, "team": team_names.get(t)} for t in team_ids],
                         "cells": list(h2h.values())},
        "season_trends": season_trends,
    }
