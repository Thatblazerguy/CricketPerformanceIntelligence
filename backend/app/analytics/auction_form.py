"""Leakage-safe, role-specific recent performance features for auction prices."""
from collections import defaultdict
from datetime import date
import time

import numpy as np
from sqlalchemy import bindparam, text


FORM_FEATURES = [
    "form_bat_runs_per_match", "form_bat_average", "form_bat_strike_rate",
    "form_bat_consistency", "form_bat_high_score", "form_bowl_wickets_per_match",
    "form_bowl_economy", "form_bowl_average", "form_bowl_strike_rate",
    "form_bowl_consistency", "form_sample_matches", "form_recent_trend",
    "form_opposition_strength",
    "form_keeper_stumpings_per_match",
]

_PERFORMANCE_SQL = text("""
WITH batter_wickets AS (
  SELECT d.batter_id AS player_id, mi.match_id, COUNT(*) AS dismissals
  FROM wickets w JOIN deliveries d ON d.id=w.delivery_id
  JOIN match_innings mi ON mi.id=d.innings_id
  WHERE d.batter_id IN :player_ids AND w.player_out_id=d.batter_id
    AND w.is_batter_dismissed=TRUE
  GROUP BY d.batter_id,mi.match_id
), team_matches AS (
  SELECT id AS match_id,start_date,team1_id AS team_id,
         CASE WHEN winner_id=team1_id THEN 1.0 WHEN winner_id IS NULL THEN NULL ELSE 0.0 END AS win
  FROM matches WHERE team1_id IS NOT NULL
  UNION ALL
  SELECT id,start_date,team2_id,
         CASE WHEN winner_id=team2_id THEN 1.0 WHEN winner_id IS NULL THEN NULL ELSE 0.0 END
  FROM matches WHERE team2_id IS NOT NULL
), team_strength AS (
  SELECT match_id,team_id,
         CASE WHEN COUNT(win) OVER prior_matches >= 5
              THEN SUM(win) OVER prior_matches / NULLIF(COUNT(win) OVER prior_matches,0)
              ELSE NULL END AS strength
  FROM team_matches
  WINDOW prior_matches AS (PARTITION BY team_id ORDER BY start_date,match_id
                           ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING)
), batting AS (
  WITH batter_high AS (
    SELECT q.player_id,q.match_id,MAX(q.innings_runs) AS high_score
    FROM (SELECT d.batter_id AS player_id,mi.match_id,mi.id AS innings_id,
                 SUM(d.batter_runs) AS innings_runs
          FROM deliveries d JOIN match_innings mi ON mi.id=d.innings_id
          WHERE d.batter_id IN :player_ids AND mi.is_super_over=FALSE
          GROUP BY d.batter_id,mi.match_id,mi.id) q
    GROUP BY q.player_id,q.match_id
  ), keeper_stumpings AS (
    SELECT w.fielder_id AS player_id,mi.match_id,COUNT(*) AS stumpings
    FROM wickets w JOIN deliveries d ON d.id=w.delivery_id
    JOIN match_innings mi ON mi.id=d.innings_id
    WHERE w.fielder_id IN :player_ids AND lower(w.dismissal_type)='stumped'
    GROUP BY w.fielder_id,mi.match_id
  )
  SELECT d.batter_id AS player_id, mi.match_id, m.start_date, m.match_format,
         t.name AS tournament_name,
         SUM(d.batter_runs) AS runs,
         SUM(CASE WHEN d.is_ball_faced_by_batter THEN 1 ELSE 0 END) AS balls,
         COALESCE(MAX(bw.dismissals),0) AS dismissals,
         COALESCE(MAX(bh.high_score),0) AS high_score,
         MAX(ts.strength) AS opposition_strength,
         COALESCE(MAX(ks.stumpings),0) AS keeper_stumpings
  FROM deliveries d JOIN match_innings mi ON mi.id=d.innings_id
  JOIN matches m ON m.id=mi.match_id
  LEFT JOIN tournaments t ON t.id=m.tournament_id
  LEFT JOIN team_strength ts ON ts.match_id=mi.match_id
       AND ts.team_id=CASE WHEN mi.batting_team_id=m.team1_id THEN m.team2_id ELSE m.team1_id END
  LEFT JOIN batter_wickets bw ON bw.player_id=d.batter_id AND bw.match_id=mi.match_id
  LEFT JOIN batter_high bh ON bh.player_id=d.batter_id AND bh.match_id=mi.match_id
  LEFT JOIN keeper_stumpings ks ON ks.player_id=d.batter_id AND ks.match_id=mi.match_id
  WHERE d.batter_id IN :player_ids AND mi.is_super_over=FALSE
  GROUP BY d.batter_id,mi.match_id,m.start_date,m.match_format,t.name
), bowler_wickets AS (
  SELECT d.bowler_id AS player_id, mi.match_id, COUNT(*) AS wickets
  FROM wickets w JOIN deliveries d ON d.id=w.delivery_id
  JOIN match_innings mi ON mi.id=d.innings_id
  WHERE d.bowler_id IN :player_ids AND w.is_bowler_wicket=TRUE
  GROUP BY d.bowler_id,mi.match_id
), bowling AS (
  SELECT d.bowler_id AS player_id, mi.match_id, m.start_date, m.match_format,
         t.name AS tournament_name,
         SUM(d.bowling_runs) AS conceded,
         SUM(CASE WHEN d.is_legal_ball THEN 1 ELSE 0 END) AS legal_balls,
         COALESCE(MAX(bw.wickets),0) AS wickets,
         MAX(ts.strength) AS opposition_strength
  FROM deliveries d JOIN match_innings mi ON mi.id=d.innings_id
  JOIN matches m ON m.id=mi.match_id
  LEFT JOIN tournaments t ON t.id=m.tournament_id
  LEFT JOIN team_strength ts ON ts.match_id=mi.match_id AND ts.team_id=mi.batting_team_id
  LEFT JOIN bowler_wickets bw ON bw.player_id=d.bowler_id AND bw.match_id=mi.match_id
  WHERE d.bowler_id IN :player_ids AND mi.is_super_over=FALSE
  GROUP BY d.bowler_id,mi.match_id,m.start_date,m.match_format,t.name
)
SELECT 'bat' AS discipline,player_id,match_id,start_date,match_format,tournament_name,
       runs,balls,dismissals,high_score,0 AS conceded,0 AS legal_balls,0 AS wickets,opposition_strength,keeper_stumpings FROM batting
UNION ALL
SELECT 'bowl',player_id,match_id,start_date,match_format,tournament_name,
       0,0,0,0,conceded,legal_balls,wickets,opposition_strength,0 FROM bowling
ORDER BY start_date DESC
""").bindparams(bindparam("player_ids", expanding=True))

_CURRENT_FORM_CACHE = {}
_CURRENT_FORM_TTL_SECONDS = 900


def _format_weight(match_format, tournament_name=None):
    # Franchise/domestic T20 is the closest auction signal; other formats
    # contribute progressively less, without being treated as T20 performance.
    if match_format == "T20":
        tournament = str(tournament_name or "").casefold()
        franchise_markers = ("premier league", "big bash", "t20 blast", "caribbean premier league",
                             "super smash", "super league", "the hundred", "ipl", "sa20", "ilt20")
        return 1.2 if any(marker in tournament for marker in franchise_markers) else 0.8
    return {"T20I": 1.0, "ODI": 0.55, "ODM": 0.5,
            "Test": 0.25, "MDM": 0.22}.get(match_format, 0.0)


def _weighted_mean(values, weights):
    valid = []
    for value, weight in zip(values, weights):
        if value is None or weight <= 0:
            continue
        try:
            value = float(value)
            if np.isfinite(value):
                valid.append((value, float(weight)))
        except (TypeError, ValueError):
            continue
    return float(np.average([x[0] for x in valid], weights=[x[1] for x in valid])) if valid else None


def _discipline_form(rows, discipline, reference_date=None):
    """Summarise a player's latest appearances. Each row is one match."""
    values, weights = [], []
    for row in rows:
        fw = _format_weight(row["match_format"], row.get("tournament_name"))
        if fw <= 0:
            continue
        days_old = max(0, ((reference_date or date.today()) - row["start_date"]).days)
        recency = 0.5 ** (days_old / 365.0)
        values.append(row)
        weights.append(fw * recency)
    if not values:
        return {}
    if discipline == "bat":
        runs = [int(r["runs"] or 0) for r in values]
        balls = [int(r["balls"] or 0) for r in values]
        dismissals = [int(r["dismissals"] or 0) for r in values]
        avgs = [r / d if d else None for r, d in zip(runs, dismissals)]
        srs = [r * 100 / b if b else None for r, b in zip(runs, balls)]
        per_match = [r for r in runs]
        avg_runs = _weighted_mean(per_match, weights)
        selected = [(v, w) for v, w in zip(per_match, weights) if w > 0]
        dispersion = (float(np.average(np.abs(np.array([v for v, _ in selected]) - avg_runs),
                                      weights=[w for _, w in selected]))
                      if selected and avg_runs else None)
        return {"form_bat_runs_per_match": avg_runs,
                "form_bat_average": _weighted_mean(avgs, weights),
                "form_bat_strike_rate": _weighted_mean(srs, weights),
                "form_bat_consistency": dispersion,
                "form_bat_high_score": max((int(r["high_score"] or 0) for r in values), default=None),
                "form_opposition_strength": _weighted_mean([r.get("opposition_strength") for r in values], weights),
                "form_keeper_stumpings_per_match": _weighted_mean([r.get("keeper_stumpings", 0) for r in values], weights)}
    wickets = [int(r["wickets"] or 0) for r in values]
    balls = [int(r["legal_balls"] or 0) for r in values]
    runs = [int(r["conceded"] or 0) for r in values]
    avgs = [r / w if w else None for r, w in zip(runs, wickets)]
    economies = [r * 6 / b if b else None for r, b in zip(runs, balls)]
    srs = [b / w if w else None for b, w in zip(balls, wickets)]
    wpm = _weighted_mean(wickets, weights)
    selected = [(v, w) for v, w in zip(wickets, weights) if w > 0]
    dispersion = (float(np.average(np.abs(np.array([v for v, _ in selected]) - wpm),
                                  weights=[w for _, w in selected]))
                  if selected and wpm else None)
    return {"form_bowl_wickets_per_match": wpm,
            "form_bowl_economy": _weighted_mean(economies, weights),
            "form_bowl_average": _weighted_mean(avgs, weights),
            "form_bowl_strike_rate": _weighted_mean(srs, weights),
            "form_bowl_consistency": dispersion,
            "form_opposition_strength": _weighted_mean([r.get("opposition_strength") for r in values], weights)}


def summarize_form(rows, role, cutoff_year=None, minimum_matches=3):
    """Pure feature calculation used for tests and historical snapshots.

    Rows contain match-level aggregates with ``discipline``, date and format.
    When supplied, cutoff_year excludes every match from that season onward.
    """
    eligible = [r for r in rows if r.get("start_date") and
                (cutoff_year is None or r["start_date"].year < int(cutoff_year))]
    reference_date = date(int(cutoff_year), 1, 1) if cutoff_year is not None else date.today()
    latest_dates = sorted({r["start_date"] for r in eligible}, reverse=True)[:12]
    selected_dates = set(latest_dates)
    eligible = [r for r in eligible if r["start_date"] in selected_dates]
    bat_rows = [r for r in eligible if r["discipline"] == "bat"]
    bowl_rows = [r for r in eligible if r["discipline"] == "bowl"]
    result = dict.fromkeys(FORM_FEATURES, None)
    role_key = str(role or "").casefold()
    is_all = "all" in role_key
    is_bowl = "bowl" in role_key and not is_all
    is_bat = ("bat" in role_key or "wicket" in role_key) and not is_all
    components = []
    if not is_bowl:
        bat = _discipline_form(bat_rows, "bat", reference_date)
        result.update(bat)
        if bat_rows:
            components.append(len({r["match_id"] for r in bat_rows}))
    if is_bowl or is_all:
        bowl = _discipline_form(bowl_rows, "bowl", reference_date)
        result.update(bowl)
        if bowl_rows:
            components.append(len({r["match_id"] for r in bowl_rows}))
    sample = max(components, default=0)
    result["form_sample_matches"] = sample
    # Form remains genuinely missing until there is enough recent evidence.
    if sample < minimum_matches:
        for key in FORM_FEATURES:
            if key not in {"form_sample_matches"}:
                result[key] = None
    else:
        # Relative change over the most recent half versus the preceding half.
        # This describes form direction; the model learns its price association.
        trend_fields = (["form_bat_runs_per_match", "form_bat_strike_rate"] if is_bat else
                        ["form_bowl_wickets_per_match"] if is_bowl else
                        ["form_bat_runs_per_match", "form_bowl_wickets_per_match"])
        recent, older = eligible[:6], eligible[6:12]
        if recent and older:
            discipline = "bowl" if is_bowl else "bat"
            field = trend_fields[0]
            stats_recent = _discipline_form([r for r in recent if r["discipline"] == discipline], discipline, reference_date)
            stats_older = _discipline_form([r for r in older if r["discipline"] == discipline], discipline, reference_date)
            key = field
            a, b = stats_recent.get(key), stats_older.get(key)
            result["form_recent_trend"] = (float(a - b) if a is not None and b is not None else None)
    return result


def load_form_snapshots(db, player_year_roles):
    """Load one indexed batch and build pre-auction snapshots for player/year/role keys."""
    ids = list({pid for pid, _year, _role in player_year_roles if pid})
    if not ids:
        return {}
    by_player = defaultdict(list)
    for row in db.execute(_PERFORMANCE_SQL, {"player_ids": ids}).mappings():
        by_player[row["player_id"]].append(dict(row))
    return {(pid, int(year)): summarize_form(by_player.get(pid, []), role, int(year))
            for pid, year, role in player_year_roles}


def load_recent_form(db, player_ids, roles_by_player=None):
    """Load the current form snapshot with one indexed batch for the active pool."""
    roles_by_player = roles_by_player or {}
    ids = list({pid for pid in player_ids if pid})
    if not ids:
        return {}
    now = time.monotonic()
    cache_keys = {pid: (pid, str(roles_by_player.get(pid) or "All-Rounder")) for pid in ids}
    result = {}
    missing = []
    for pid, key in cache_keys.items():
        cached = _CURRENT_FORM_CACHE.get(key)
        if cached and now - cached[0] < _CURRENT_FORM_TTL_SECONDS:
            result[pid] = cached[1]
        else:
            missing.append(pid)
    if not missing:
        return result
    by_player = defaultdict(list)
    for row in db.execute(_PERFORMANCE_SQL, {"player_ids": missing}).mappings():
        by_player[row["player_id"]].append(dict(row))
    for pid in missing:
        snapshot = summarize_form(by_player.get(pid, []), roles_by_player.get(pid, "All-Rounder"))
        _CURRENT_FORM_CACHE[cache_keys[pid]] = (now, snapshot)
        result[pid] = snapshot
    return result
