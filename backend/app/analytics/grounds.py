"""Ground-level match analytics, scoped to a selected venue and format."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, date
from threading import RLock

from sqlalchemy import text
from sqlalchemy import bindparam
from sqlalchemy.orm import Session


FORMAT_BUCKETS = {
    "ODI": ("ODI", "ODM"),
    "T20": ("T20", "T20I"),
    "Test": ("Test", "MDM"),
}
_CACHE: dict[tuple[str, str], tuple[datetime, dict]] = {}
_CACHE_LOCK = RLock()
_CACHE_TTL = timedelta(minutes=5)


def classify_bowling_style(style: str | None) -> str:
    """Classify only explicitly recognizable pace/spin styles; leave the rest unknown."""
    value = (style or "").strip().casefold()
    if not value:
        return "unknown"
    if value in {"pace", "fast", "fast-medium", "fast medium", "medium-fast", "medium fast", "medium"}:
        return "pace"
    if value == "spin":
        return "spin"
    spin_terms = ("spin", "off break", "offbreak", "leg break", "legbreak", "orthodox",
                  "chinaman", "left arm slow", "slow left", "slow right", "wrist spin", "finger spin")
    pace_terms = ("fast", "seam", "medium", "pace")
    if any(term in value for term in spin_terms):
        return "spin"
    if any(term in value for term in pace_terms):
        return "pace"
    return "unknown"


def format_phase_case(alias: str = "m") -> str:
    """One-based over labels from Cricsheet's zero-based over_number."""
    return f"""CASE
      WHEN {alias}.match_format IN ('T20','T20I') AND d.over_number BETWEEN 0 AND 5 THEN 'Powerplay'
      WHEN {alias}.match_format IN ('T20','T20I') AND d.over_number BETWEEN 6 AND 14 THEN 'Middle'
      WHEN {alias}.match_format IN ('T20','T20I') AND d.over_number BETWEEN 15 AND 19 THEN 'Death'
      WHEN {alias}.match_format IN ('ODI','ODM') AND d.over_number BETWEEN 0 AND 9 THEN 'Powerplay'
      WHEN {alias}.match_format IN ('ODI','ODM') AND d.over_number BETWEEN 10 AND 39 THEN 'Middle'
      WHEN {alias}.match_format IN ('ODI','ODM') AND d.over_number BETWEEN 40 AND 49 THEN 'Death'
      WHEN {alias}.match_format IN ('Test','MDM') THEN
        'Overs ' || (floor(d.over_number / 20.0)::int * 20 + 1)::text || '-' ||
        (floor(d.over_number / 20.0)::int * 20 + 20)::text
      ELSE 'Outside standard phase ranges'
    END"""


def _pct(numerator: int | float, denominator: int | float):
    return round(100 * numerator / denominator, 1) if denominator else None


def _round(value, digits=1):
    return round(float(value), digits) if value is not None else None


def _cache_get(key):
    with _CACHE_LOCK:
        hit = _CACHE.get(key)
        if hit and datetime.utcnow() - hit[0] < _CACHE_TTL:
            return hit[1]
        _CACHE.pop(key, None)
    return None


def _cache_set(key, value):
    with _CACHE_LOCK:
        _CACHE[key] = (datetime.utcnow(), value)


def get_ground_analytics(db: Session, venue_id: str, format_bucket: str, start_date=None, end_date=None, recent_matches=10, period="all") -> dict:
    if format_bucket not in FORMAT_BUCKETS:
        raise ValueError("format must be one of ODI, T20, or Test")
    if recent_matches not in (10, 20):
        raise ValueError("recent_matches must be 10 or 20")
    if period not in {"all", "1", "3", "5", "10", "custom"}:
        raise ValueError("period must be all, 1, 3, 5, 10, or custom")
    if period not in {"all", "custom"} and not (start_date or end_date):
        today = date.today()
        try:
            start_date = today.replace(year=today.year - int(period))
        except ValueError:
            start_date = today.replace(year=today.year - int(period), day=28)
    if start_date and end_date and start_date > end_date:
        raise ValueError("start_date must be on or before end_date")
    key = (venue_id, format_bucket, str(start_date or ""), str(end_date or ""), recent_matches, period)
    cached = _cache_get(key)
    if cached is not None:
        return cached

    formats = FORMAT_BUCKETS[format_bucket]
    fmt_sql = ",".join("'" + value.replace("'", "''") + "'" for value in formats)
    # Avoid nullable untyped bind parameters in raw SQL. PostgreSQL cannot infer
    # a type for `:start_date IS NULL` when the value is None, which made the
    # default All time ground request fail with AmbiguousParameter (500).
    date_parts = []
    params = {"venue_id": venue_id}
    if start_date is not None:
        date_parts.append("m.start_date >= :start_date")
        params["start_date"] = start_date
    if end_date is not None:
        date_parts.append("m.start_date <= :end_date")
        params["end_date"] = end_date
    date_clause = "".join(" AND " + part for part in date_parts)
    venue = db.execute(text("SELECT id, canonical_name, city, country FROM venues WHERE id=:id"),
                       {"id": venue_id}).mappings().first()
    if not venue:
        return None

    match_rows = db.execute(text(f"""
      SELECT m.id, m.match_format, m.start_date, m.winner_id, m.team1_id, m.team2_id,
             t1.canonical_name AS team1_name, t2.canonical_name AS team2_name, m.toss_winner_id,
             lower(coalesce(m.toss_decision,'')) AS toss_decision,
             m.result_type, first_inn.batting_team_id AS first_batting_team_id
      FROM matches m
      LEFT JOIN teams t1 ON t1.id=m.team1_id LEFT JOIN teams t2 ON t2.id=m.team2_id
      LEFT JOIN match_innings first_inn ON first_inn.match_id=m.id
        AND first_inn.innings_number=1 AND first_inn.is_super_over=FALSE
      WHERE m.venue_id=:venue_id AND m.match_format IN ({fmt_sql}) {date_clause}
    """), params).mappings().all()
    match_ids = {r["id"] for r in match_rows}
    if not match_rows:
        result = _empty_result(venue, format_bucket, formats, start_date, end_date, recent_matches, period)
        _cache_set(key, result)
        return result

    innings_rows = db.execute(text(f"""
      SELECT m.id AS match_id, m.match_format, m.start_date, i.id AS innings_id,
             i.innings_number, i.batting_team_id, COUNT(d.id) AS delivery_count,
             COUNT(d.id) FILTER (WHERE d.is_legal_ball) AS legal_balls,
             COALESCE(SUM(d.total_runs),0) AS runs
      FROM matches m JOIN match_innings i ON i.match_id=m.id AND i.is_super_over=FALSE
      LEFT JOIN deliveries d ON d.innings_id=i.id
      WHERE m.venue_id=:venue_id AND m.match_format IN ({fmt_sql}) {date_clause}
      GROUP BY m.id,m.match_format,m.start_date,i.id,i.innings_number,i.batting_team_id
      ORDER BY m.start_date,i.innings_number
    """), params).mappings().all()
    scored_innings = [dict(r) for r in innings_rows if r["delivery_count"]]
    recent_match_rows = sorted(match_rows, key=lambda r: r["start_date"], reverse=True)[:recent_matches]
    recent_ids = [r["id"] for r in recent_match_rows]
    recent_innings = []
    if recent_ids:
        recent_innings = [dict(r) for r in db.execute(text("""
          SELECT i.match_id,i.innings_number,COUNT(d.id) AS delivery_count,
                 COALESCE(SUM(d.total_runs),0) AS runs
          FROM match_innings i LEFT JOIN deliveries d ON d.innings_id=i.id
          WHERE i.is_super_over=FALSE AND i.match_id IN :match_ids
          GROUP BY i.match_id,i.innings_number
        """).bindparams(bindparam("match_ids", expanding=True)), {"match_ids": recent_ids}).mappings().all()
            if r["delivery_count"]]
    recent_by_innings = defaultdict(list)
    for row in recent_innings:
        recent_by_innings[row["innings_number"]].append(row["runs"])
    recent_result_rows = []
    for m in recent_match_rows:
        recent_result_rows.append({"date": str(m["start_date"]), "match_id": m["id"],
            "format": m["match_format"], "winner_id": m["winner_id"],
            "result_type": m["result_type"], "team1": m["team1_name"], "team2": m["team2_name"],
            "winner": m["team1_name"] if m["winner_id"] == m["team1_id"] else m["team2_name"] if m["winner_id"] == m["team2_id"] else None})
    by_innings = defaultdict(list)
    for row in scored_innings:
        by_innings[row["innings_number"]].append(row)
    innings_summary = []
    for num in sorted(by_innings):
        rows = by_innings[num]
        innings_summary.append({
            "innings": num,
            "average_score": _round(sum(r["runs"] for r in rows) / len(rows)),
            "average_legal_balls": _round(sum(r["legal_balls"] for r in rows) / len(rows)),
            "sample_innings": len(rows),
        })
    first_rows = by_innings.get(1, [])
    second_rows = by_innings.get(2, [])
    totals = [r["runs"] for r in scored_innings]
    wickets_rows = db.execute(text(f"""
      SELECT i.innings_number, COUNT(w.id) FILTER (WHERE w.is_batter_dismissed) AS wickets
      FROM matches m JOIN match_innings i ON i.match_id=m.id AND i.is_super_over=FALSE
      LEFT JOIN deliveries d ON d.innings_id=i.id
      LEFT JOIN wickets w ON w.delivery_id=d.id
      WHERE m.venue_id=:venue_id AND m.match_format IN ({fmt_sql}) {date_clause}
      GROUP BY i.id,i.innings_number
    """), params).mappings().all()
    wicket_by_innings = defaultdict(list)
    for row in wickets_rows:
        wicket_by_innings[row["innings_number"]].append(int(row["wickets"] or 0))
    average_wickets = [{"innings": n, "average_wickets_lost": _round(sum(vals)/len(vals)),
                        "sample_innings": len(vals)} for n, vals in sorted(wicket_by_innings.items())]

    phase_case = format_phase_case("m")
    phase_rows = db.execute(text(f"""
      WITH phase_innings AS (
        SELECT m.id AS match_id, m.match_format, i.id AS innings_id, {phase_case} AS phase,
               SUM(d.total_runs) AS runs, COUNT(DISTINCT d.over_number) AS overs_observed
        FROM matches m JOIN match_innings i ON i.match_id=m.id AND i.is_super_over=FALSE
        JOIN deliveries d ON d.innings_id=i.id
        WHERE m.venue_id=:venue_id AND m.match_format IN ({fmt_sql}) {date_clause}
        GROUP BY 1,2,3,4
      )
      SELECT match_format,phase,COUNT(*) AS sample_innings,AVG(runs) AS average_phase_runs,
             SUM(runs) AS total_runs,SUM(overs_observed) AS observed_innings_overs
      FROM phase_innings GROUP BY match_format,phase
      ORDER BY match_format, CASE phase WHEN 'Powerplay' THEN 1 WHEN 'Middle' THEN 2 WHEN 'Death' THEN 3 ELSE 4 END,phase
    """), params).mappings().all()
    phase_analytics = [{"format": r["match_format"], "phase": r["phase"],
        "sample_innings": int(r["sample_innings"]), "average_runs": _round(r["average_phase_runs"]),
        "total_runs": int(r["total_runs"] or 0), "observed_innings_overs": int(r["observed_innings_overs"] or 0)}
        for r in phase_rows]

    # Choose one most reliable style value per bowler via LATERAL to avoid duplicate delivery joins.
    style_case = """CASE
      WHEN style.value IN ('pace','fast','fast-medium','fast medium','medium-fast','medium fast','medium')
        OR style.value LIKE '%fast%' OR style.value LIKE '%seam%' OR style.value LIKE '%medium%' THEN 'pace'
      WHEN style.value IN ('spin','slow') OR style.value LIKE '%spin%' OR style.value LIKE '%break%'
        OR style.value LIKE '%orthodox%' OR style.value LIKE '%chinaman%'
        OR style.value LIKE '%slow left%' OR style.value LIKE '%slow right%' THEN 'spin'
      ELSE 'unknown' END"""
    bowling_rows = db.execute(text(f"""
      WITH wickets_per_delivery AS (
        SELECT delivery_id,COUNT(*) FILTER (WHERE is_bowler_wicket) AS wickets
        FROM wickets GROUP BY delivery_id
      ), classified AS (
        SELECT m.match_format,i.id AS innings_id,i.innings_number,d.id AS delivery_id,
          {phase_case} AS phase,{style_case} AS style_group,
          d.is_legal_ball,d.bowling_runs,d.is_boundary_four,d.is_boundary_six,
          COALESCE(wpd.wickets,0) AS wickets
        FROM matches m JOIN match_innings i ON i.match_id=m.id AND i.is_super_over=FALSE
        JOIN deliveries d ON d.innings_id=i.id
        LEFT JOIN LATERAL (
          SELECT COALESCE(
            (SELECT lower(trim(category.attribute_value)) FROM player_attributes category
             WHERE category.player_id=d.bowler_id AND category.attribute_type='bowling_type'
               AND lower(trim(category.attribute_value)) IN ('pace','spin')
             ORDER BY CASE lower(category.confidence) WHEN 'high' THEN 3 WHEN 'medium' THEN 2 ELSE 1 END DESC,
                      category.updated_at DESC LIMIT 1),
            (SELECT lower(trim(style.attribute_value)) FROM player_attributes style
             WHERE style.player_id=d.bowler_id AND style.attribute_type='bowling_style'
             ORDER BY CASE lower(style.confidence) WHEN 'high' THEN 3 WHEN 'medium' THEN 2 ELSE 1 END DESC,
                      style.updated_at DESC LIMIT 1)
          ) AS value
        ) style ON TRUE
        LEFT JOIN wickets_per_delivery wpd ON wpd.delivery_id=d.id
        WHERE m.venue_id=:venue_id AND m.match_format IN ({fmt_sql}) {date_clause}
      )
      SELECT match_format,style_group,phase,COUNT(*) AS deliveries,
        COUNT(*) FILTER (WHERE is_legal_ball) AS legal_balls,
        SUM(bowling_runs) AS runs_conceded,
        COUNT(*) FILTER (WHERE is_legal_ball AND bowling_runs=0) AS dot_balls,
        COUNT(*) FILTER (WHERE is_legal_ball AND (is_boundary_four OR is_boundary_six)) AS boundaries,
        SUM(wickets) AS wickets,COUNT(DISTINCT innings_id) AS innings_count,
        COUNT(DISTINCT innings_number) AS innings_numbers,
        ARRAY_AGG(DISTINCT innings_id) AS innings_ids
      FROM classified GROUP BY 1,2,3
    """), params).mappings().all()
    bowling_by_style = defaultdict(lambda: {"wickets":0,"runs_conceded":0,"legal_balls":0,"dot_balls":0,
        "boundaries":0,"deliveries":0,"innings":set(),"formats":defaultdict(lambda: {"wickets":0,"runs":0,"legal":0,"dots":0,"boundaries":0,"innings":set()}),"phases":[]})
    unknown = {"deliveries":0,"wickets":0,"legal_balls":0}
    for row in bowling_rows:
        style = row["style_group"]
        legal = int(row["legal_balls"] or 0); wickets = int(row["wickets"] or 0)
        runs = int(row["runs_conceded"] or 0); dots = int(row["dot_balls"] or 0)
        boundaries = int(row["boundaries"] or 0); deliveries = int(row["deliveries"] or 0)
        if style == "unknown":
            unknown["deliveries"] += deliveries; unknown["wickets"] += wickets; unknown["legal_balls"] += legal
            continue
        obj = bowling_by_style[style]
        obj["wickets"] += wickets; obj["runs_conceded"] += runs; obj["legal_balls"] += legal
        obj["dot_balls"] += dots; obj["boundaries"] += boundaries; obj["deliveries"] += deliveries
        obj["innings"].update(row["innings_ids"] or [])
        fmt = obj["formats"][row["match_format"]]
        fmt["wickets"] += wickets; fmt["runs"] += runs; fmt["legal"] += legal
        fmt["dots"] += dots; fmt["boundaries"] += boundaries
        fmt["innings"].add((row["innings_numbers"], row["phase"]))
        overs = legal / 6
        obj["phases"].append({"format":row["match_format"],"phase":row["phase"],"sample_innings":int(row["innings_count"]),
            "wickets":wickets,"runs_conceded":runs,"legal_balls":legal,"economy":_round(runs / overs if overs else None),
            "bowling_average":_round(runs / wickets if wickets else None),
            "bowling_strike_rate":_round(legal / wickets if wickets else None),
            "dot_ball_percentage":_pct(dots,legal),"boundary_percentage_conceded":_pct(boundaries,legal)})
    pace_spin = []
    for style in ("pace","spin"):
        x = bowling_by_style[style]
        overs = x["legal_balls"] / 6
        pace_spin.append({"style":style,"wickets":x["wickets"],"wickets_per_innings":_round(x["wickets"]/len(x["innings"]) if x["innings"] else None),
            "runs_conceded":x["runs_conceded"],"legal_balls":x["legal_balls"],"innings_with_bowling":len(x["innings"]),
            "economy":_round(x["runs_conceded"]/overs if overs else None),
            "bowling_average":_round(x["runs_conceded"]/x["wickets"] if x["wickets"] else None),
            "bowling_strike_rate":_round(x["legal_balls"]/x["wickets"] if x["wickets"] else None),
            "dot_ball_percentage":_pct(x["dot_balls"],x["legal_balls"]),
            "boundary_percentage_conceded":_pct(x["boundaries"],x["legal_balls"]),
            "wicket_share_percentage":_pct(x["wickets"],sum(bowling_by_style[s]["wickets"] for s in ("pace","spin"))),
            "by_format":[{"format":fmt,"wickets":v["wickets"],"economy":_round(v["runs"]/(v["legal"]/6) if v["legal"] else None),
                "bowling_average":_round(v["runs"]/v["wickets"] if v["wickets"] else None),
                "bowling_strike_rate":_round(v["legal"]/v["wickets"] if v["wickets"] else None),
                "dot_ball_percentage":_pct(v["dots"],v["legal"]),"boundary_percentage_conceded":_pct(v["boundaries"],v["legal"])}
                for fmt,v in sorted(x["formats"].items())]})
    phase_bowling = []
    for style in ("pace","spin"):
        for p in bowling_by_style[style]["phases"]:
            p["style"] = style
            phase_bowling.append(p)
    innings_phase_wickets = db.execute(text(f"""
      WITH wickets_per_delivery AS (
        SELECT delivery_id,COUNT(*) FILTER (WHERE is_bowler_wicket) AS wickets
        FROM wickets GROUP BY delivery_id
      )
      SELECT m.match_format,i.innings_number,{phase_case} AS phase,{style_case} AS style_group,
             COALESCE(SUM(wpd.wickets),0) AS wickets
      FROM matches m JOIN match_innings i ON i.match_id=m.id AND i.is_super_over=FALSE
      JOIN deliveries d ON d.innings_id=i.id
      LEFT JOIN LATERAL (
        SELECT COALESCE(
          (SELECT lower(trim(category.attribute_value)) FROM player_attributes category
           WHERE category.player_id=d.bowler_id AND category.attribute_type='bowling_type'
             AND lower(trim(category.attribute_value)) IN ('pace','spin')
           ORDER BY CASE lower(category.confidence) WHEN 'high' THEN 3 WHEN 'medium' THEN 2 ELSE 1 END DESC,
                    category.updated_at DESC LIMIT 1),
          (SELECT lower(trim(style.attribute_value)) FROM player_attributes style
           WHERE style.player_id=d.bowler_id AND style.attribute_type='bowling_style'
           ORDER BY CASE lower(style.confidence) WHEN 'high' THEN 3 WHEN 'medium' THEN 2 ELSE 1 END DESC,
                    style.updated_at DESC LIMIT 1)
        ) AS value
      ) style ON TRUE
      LEFT JOIN wickets_per_delivery wpd ON wpd.delivery_id=d.id
      WHERE m.venue_id=:venue_id AND m.match_format IN ({fmt_sql}) {date_clause}
      GROUP BY 1,2,3,4
    """), params).mappings().all()
    wickets_by_innings_phase = [{"format":r["match_format"],"innings":r["innings_number"],"phase":r["phase"],
        "style":r["style_group"],"bowler_credit_wickets":int(r["wickets"] or 0)} for r in innings_phase_wickets]

    outcome_rows = db.execute(text(f"""
      SELECT COUNT(*) AS matches,
        COUNT(*) FILTER (WHERE m.winner_id IS NOT NULL) AS decided,
        COUNT(*) FILTER (WHERE m.winner_id IS NULL AND lower(coalesce(m.result_type,'')) IN ('no result','abandoned')) AS no_result,
        COUNT(*) FILTER (WHERE m.winner_id=first_inn.batting_team_id AND first_inn.batting_team_id IS NOT NULL) AS batting_first_wins,
        COUNT(*) FILTER (WHERE m.winner_id IS NOT NULL AND first_inn.batting_team_id IS NOT NULL
                         AND m.winner_id<>first_inn.batting_team_id) AS chasing_wins,
        COUNT(*) FILTER (WHERE m.winner_id IS NOT NULL AND first_inn.batting_team_id IS NOT NULL) AS decided_with_first_innings,
        COUNT(*) FILTER (WHERE m.toss_decision IS NOT NULL AND m.winner_id IS NOT NULL) AS toss_decided,
        COUNT(*) FILTER (WHERE m.toss_decision='bat' AND m.winner_id=m.toss_winner_id) AS bat_toss_winner_wins,
        COUNT(*) FILTER (WHERE m.toss_decision='bat' AND m.winner_id IS NOT NULL) AS bat_toss_matches,
        COUNT(*) FILTER (WHERE m.toss_decision='field' AND m.winner_id=m.toss_winner_id) AS field_toss_winner_wins,
        COUNT(*) FILTER (WHERE m.toss_decision='field' AND m.winner_id IS NOT NULL) AS field_toss_matches
      FROM matches m LEFT JOIN match_innings first_inn ON first_inn.match_id=m.id
        AND first_inn.innings_number=1 AND first_inn.is_super_over=FALSE
      WHERE m.venue_id=:venue_id AND m.match_format IN ({fmt_sql}) {date_clause}
    """), params).mappings().one()
    outcomes = dict(outcome_rows)
    outcomes.update({
        "batting_first_win_percentage":_pct(outcomes["batting_first_wins"],outcomes["decided_with_first_innings"]),
        "chasing_win_percentage":_pct(outcomes["chasing_wins"],outcomes["decided_with_first_innings"]),
        "toss_decision": [
            {"decision":"bat","matches":outcomes["bat_toss_matches"],"toss_winner_wins":outcomes["bat_toss_winner_wins"],
             "toss_winner_win_percentage":_pct(outcomes["bat_toss_winner_wins"],outcomes["bat_toss_matches"])},
            {"decision":"field","matches":outcomes["field_toss_matches"],"toss_winner_wins":outcomes["field_toss_winner_wins"],
             "toss_winner_win_percentage":_pct(outcomes["field_toss_winner_wins"],outcomes["field_toss_matches"])},
        ]})

    format_counts = defaultdict(int)
    for m in match_rows: format_counts[m["match_format"]] += 1
    super_over_innings = db.execute(text(f"""
      SELECT COUNT(*) FROM matches m JOIN match_innings i ON i.match_id=m.id
      WHERE m.venue_id=:venue_id AND m.match_format IN ({fmt_sql}) {date_clause} AND i.is_super_over=TRUE
    """), params).scalar() or 0
    year_scores = defaultdict(lambda: {"matches":set(),"runs":[]})
    for r in scored_innings:
        if r["innings_number"] == 1:
            key_year = r["start_date"].year
            year_scores[key_year]["matches"].add(r["match_id"])
            year_scores[key_year]["runs"].append(r["runs"])
    year_trends = [{"year":year,"matches":len(v["matches"]),"average_first_innings_score":_round(sum(v["runs"])/len(v["runs"]) if v["runs"] else None),
                    "sample_innings":len(v["runs"])} for year,v in sorted(year_scores.items())]
    format_comparison = []
    for exact_format in formats:
        f_innings = [r for r in scored_innings if r["match_format"] == exact_format]
        f_first = [r for r in f_innings if r["innings_number"] == 1]
        f_second = [r for r in f_innings if r["innings_number"] == 2]
        f_matches = [r for r in match_rows if r["match_format"] == exact_format]
        f_first_team = {r["match_id"]:r["batting_team_id"] for r in f_first}
        f_decided = [r for r in f_matches if r["winner_id"] and f_first_team.get(r["id"])]
        f_first_wins = sum(1 for r in f_decided if r["winner_id"] == f_first_team[r["id"]])
        f_chase_wins = len(f_decided) - f_first_wins
        format_comparison.append({"format":exact_format,"matches":len(f_matches),
            "average_first_innings_score":_round(sum(r["runs"] for r in f_first)/len(f_first) if f_first else None),
            "first_innings_sample":len(f_first),
            "average_second_innings_score":_round(sum(r["runs"] for r in f_second)/len(f_second) if f_second else None),
            "second_innings_sample":len(f_second),"decided_matches":len(f_decided),
            "innings_one_side_win_percentage":_pct(f_first_wins,len(f_decided)),
            "other_side_win_percentage":_pct(f_chase_wins,len(f_decided))})

    phase_wide = {}
    for row in phase_analytics:
        if row["phase"] in ("Powerplay","Middle","Death"):
            phase_wide.setdefault(row["phase"],[]).append(row)
    summary = _build_insights(format_bucket, outcomes, pace_spin, phase_analytics, len(match_rows))
    recent_first = recent_by_innings[1]
    if len(recent_first) >= 5 and first_rows:
        delta = sum(recent_first) / len(recent_first) - sum(r["runs"] for r in first_rows) / len(first_rows)
        if abs(delta) >= 10:
            summary.append(f"Recent first-innings scoring is {'up' if delta > 0 else 'down'} {abs(delta):.1f} runs versus the selected-period average (n={len(recent_first)} recent innings).")
    result = {
        "venue":{"id":venue["id"],"name":venue["canonical_name"],"city":venue["city"],"country":venue["country"]},
        "format":format_bucket,"included_formats":list(formats),"matches":len(match_rows),
        "filters":{"period":period,"start_date":str(start_date) if start_date else None,"end_date":str(end_date) if end_date else None,"recent_matches":recent_matches},
        "format_match_counts":[{"format":k,"matches":v} for k,v in sorted(format_counts.items())],
        "format_comparison":format_comparison,
        "innings":innings_summary,
        "batting":{"average_first_innings_score":_round(sum(r["runs"] for r in first_rows)/len(first_rows) if first_rows else None),
            "first_innings_sample":len(first_rows),
            "average_second_innings_score":_round(sum(r["runs"] for r in second_rows)/len(second_rows) if second_rows else None),
            "second_innings_sample":len(second_rows),"average_wickets_lost":average_wickets,
            "highest_team_total":max(totals) if totals else None,"lowest_team_total":min(totals) if totals else None,
            "team_total_innings_sample":len(totals),"phase_scoring":phase_analytics},
        "bowling":{"pace_spin":pace_spin,"unknown_style":unknown,"by_phase":phase_bowling,
            "wickets_by_innings_phase":wickets_by_innings_phase},
        "match_conditions":{"outcomes":outcomes,"year_trends":year_trends,
            "excluded_super_over_innings":int(super_over_innings),
            "recent":{"sample_matches":len(recent_match_rows),"requested_matches":recent_matches,
                "results":recent_result_rows,
                "average_first_innings_score":_round(sum(recent_by_innings[1])/len(recent_by_innings[1]) if recent_by_innings[1] else None),
                "first_innings_sample":len(recent_by_innings[1]),
                "average_second_innings_score":_round(sum(recent_by_innings[2])/len(recent_by_innings[2]) if recent_by_innings[2] else None),
                "second_innings_sample":len(recent_by_innings[2]),
                "first_innings_delta_vs_period":_round((sum(recent_by_innings[1])/len(recent_by_innings[1]) - sum(r["runs"] for r in first_rows)/len(first_rows)) if recent_by_innings[1] and first_rows else None)}},
        "insights":summary,
        "limitations":{"phase_rules":"T20/T20I: overs 1-6/7-15/16-20; ODI/ODM: 1-10/11-40/41-50; Test/MDM: innings progression bands of 20 overs.",
            "shortened_matches":"Only deliveries in observed overs contribute; unbowled phase overs are not imputed.",
            "bowling_style_unknown_deliveries":unknown["deliveries"],"super_overs":"Excluded from standard innings and phase metrics; count shown separately."},
    }
    _cache_set(key,result)
    return result


def _build_insights(format_bucket, outcomes, pace_spin, phases, matches):
    result=[]
    if matches >= 10:
        result.append(f"Scoring profile is based on {matches:,} {format_bucket} group matches across {len(FORMAT_BUCKETS[format_bucket])} stored formats.")
    else:
        result.append(f"Limited ground sample ({matches} matches); scoring and result patterns are descriptive only.")
    decided = outcomes["decided_with_first_innings"]
    if decided >= 10:
        if outcomes["chasing_win_percentage"] is not None and outcomes["batting_first_win_percentage"] is not None:
            diff = outcomes["chasing_win_percentage"] - outcomes["batting_first_win_percentage"]
            if abs(diff) >= 10:
                if format_bucket == "Test":
                    trend = "the opposition to the innings-one side" if diff > 0 else "the innings-one side"
                    result.append(f"Results lean toward {trend}: {abs(diff):.1f} percentage points higher win rate ({decided} decided matches).")
                else:
                    trend = "chasing" if diff > 0 else "batting first"
                    result.append(f"Results lean toward {trend}: {abs(diff):.1f} percentage points higher win rate ({decided} decided matches with an innings-one record).")
            else:
                result.append(f"Batting-first and chasing win rates are close ({decided} decided matches).")
    known_wickets = sum(x["wickets"] for x in pace_spin)
    if known_wickets >= 30:
        leader=max(pace_spin,key=lambda x:x["wickets"])
        gap=abs(pace_spin[0]["wickets"]-pace_spin[1]["wickets"])
        if gap/max(known_wickets,1) >= .15:
            result.append(f"{leader['style'].title()} has taken the larger share of classified bowler-credit wickets ({leader['wicket_share_percentage']}% of {known_wickets}); unknown styles are excluded.")
        else:
            result.append(f"Pace and spin wicket counts are broadly balanced ({known_wickets} classified bowler-credit wickets).")
    return result


def _empty_result(venue, format_bucket, formats, start_date=None, end_date=None, recent_matches=10, period="all"):
    return {"venue":{"id":venue["id"],"name":venue["canonical_name"],"city":venue["city"],"country":venue["country"]},
        "format":format_bucket,"included_formats":list(formats),"matches":0,"filters":{"period":period,"start_date":str(start_date) if start_date else None,"end_date":str(end_date) if end_date else None,"recent_matches":recent_matches},"format_match_counts":[],"format_comparison":[],"innings":[],
        "batting":{"average_first_innings_score":None,"first_innings_sample":0,"average_second_innings_score":None,
            "second_innings_sample":0,"average_wickets_lost":[],"highest_team_total":None,"lowest_team_total":None,
            "team_total_innings_sample":0,"phase_scoring":[]},
        "bowling":{"pace_spin":[],"unknown_style":{"deliveries":0,"wickets":0,"legal_balls":0},"by_phase":[],"wickets_by_innings_phase":[]},
        "match_conditions":{"outcomes":{"matches":0,"decided":0,"no_result":0,"batting_first_wins":0,"chasing_wins":0,
            "decided_with_first_innings":0,"batting_first_win_percentage":None,"chasing_win_percentage":None,"toss_decision":[]},
            "year_trends":[],"excluded_super_over_innings":0,"recent":{"sample_matches":0,"requested_matches":recent_matches,"results":[],"average_first_innings_score":None,"first_innings_sample":0,"average_second_innings_score":None,"second_innings_sample":0,"first_innings_delta_vs_period":None}},"insights":["No matches are available for this ground and format."],
        "limitations":{"phase_rules":"Format-specific over bands; Tests use innings progression.",
            "shortened_matches":"Only observed deliveries are included.","bowling_style_unknown_deliveries":0,
            "super_overs":"Excluded from standard metrics."}}
