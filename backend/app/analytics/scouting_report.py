"""Evidence-backed scouting reports and side-by-side candidate comparisons.

Every conclusion in a report is generated from the numbers beside it: percentiles
against a named comparison group, sample sizes, and match references from the
per-innings aggregates. Nothing is asserted without a figure.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Sequence

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.analytics import scouting_stats as st
from app.analytics.scouting_engine import (
    FORMATS, ROLES, Requirements, Scope, _role_weights, build_cohort, evaluate_candidate, evaluate_player,
    load_scope, meets_baseline, narrative, percentile_for, player_identity, primary_positions, role_fit,
)
from app.analytics.scouting_roles import LIMITED, METRICS, thresholds

_BAT_LOG = """
SELECT b.match_id, b.innings_id, b.start_date, b.season, b.innings_number, b.batting_position, b.entry_wickets, b.entry_over,
       b.runs, b.balls, b.fours, b.sixes, b.dots, b.dismissed, b.dismissal_type, b.is_chase, b.team_won,
       b.pp_runs, b.pp_balls, b.mid_runs, b.mid_balls, b.death_runs, b.death_balls,
       opp.name AS opponent, team.name AS team, v.name AS venue, v.country AS venue_country, t.name AS tournament
FROM scouting_bat_innings b
LEFT JOIN teams opp ON opp.id = b.opponent_id
LEFT JOIN teams team ON team.id = b.team_id
LEFT JOIN venues v ON v.id = b.venue_id
LEFT JOIN tournaments t ON t.id = b.tournament_id
WHERE b.player_id = ANY(:pids) AND {scope}
ORDER BY b.player_id, b.start_date, b.innings_number
"""

_BOWL_LOG = """
SELECT b.player_id, b.match_id, b.innings_id, b.start_date, b.season, b.innings_number, b.legal_balls, b.runs, b.wickets,
       b.dots, b.fours, b.sixes, b.wides, b.noballs, b.is_defending, b.team_won,
       b.pp_balls, b.pp_runs, b.pp_wkts, b.mid_balls, b.mid_runs, b.mid_wkts, b.death_balls, b.death_runs, b.death_wkts,
       opp.name AS opponent, v.name AS venue, v.country AS venue_country, t.name AS tournament
FROM scouting_bowl_innings b
LEFT JOIN teams opp ON opp.id = b.opponent_id
LEFT JOIN venues v ON v.id = b.venue_id
LEFT JOIN tournaments t ON t.id = b.tournament_id
WHERE b.player_id = ANY(:pids) AND {scope}
ORDER BY b.player_id, b.start_date, b.innings_number
"""

_VS_STYLE = """
SELECT s.bowling_style, SUM(s.runs) AS runs, SUM(s.balls) AS balls, SUM(s.dots) AS dots, SUM(s.bnd) AS bnd, SUM(s.outs) AS outs
FROM scouting_bat_vs_style s JOIN scouting_bat_innings b ON b.innings_id = s.innings_id AND b.player_id = s.player_id
WHERE s.player_id = :pid AND {scope}
GROUP BY s.bowling_style ORDER BY SUM(s.balls) DESC
"""

_BAT_LOG_ALL = _BAT_LOG.replace("SELECT b.match_id", "SELECT b.player_id, b.match_id")


def _r(v, d=1):
    return round(v, d) if v is not None else None


def _match_ref(row: dict) -> dict:
    return {"match_id": row["match_id"], "date": row["start_date"].isoformat() if row.get("start_date") else None,
            "opponent": row.get("opponent"), "venue": row.get("venue"), "tournament": row.get("tournament")}


def _bat_line(rows: Sequence[dict]) -> dict:
    runs = sum(r["runs"] for r in rows)
    balls = sum(r["balls"] for r in rows)
    outs = sum(1 for r in rows if r["dismissed"])
    return {"innings": len(rows), "runs": runs, "balls": balls, "dismissals": outs,
            "average": _r(st.ratio(runs, outs), 2), "strike_rate": _r(st.ratio(runs, balls, 100), 1),
            "boundary_pct": _r(st.ratio(sum(r["fours"] + r["sixes"] for r in rows), balls, 100), 1),
            "dot_pct": _r(st.ratio(sum(r["dots"] for r in rows), balls, 100), 1)}


def _bowl_line(rows: Sequence[dict]) -> dict:
    balls = sum(r["legal_balls"] for r in rows)
    runs = sum(r["runs"] for r in rows)
    wkts = sum(r["wickets"] for r in rows)
    return {"innings": len(rows), "legal_balls": balls, "overs": f"{balls // 6}.{balls % 6}", "runs": runs, "wickets": wkts,
            "economy": _r(st.ratio(runs, balls, 6), 2), "average": _r(st.ratio(runs, wkts), 2),
            "strike_rate": _r(st.ratio(balls, wkts), 1),
            "dot_pct": _r(st.ratio(sum(r["dots"] for r in rows), balls, 100), 1)}


def _batting_section(db: Session, data, pid: str, scope: Scope, cohort) -> Optional[dict]:
    row = data.bat.get(pid)
    if not row:
        return None
    scope_sql, params = scope.sql("b")
    log = [dict(r) for r in db.execute(text(_BAT_LOG.format(scope=scope_sql)), {**params, "pids": [pid]}).mappings()]
    th = data.thresholds
    limited = scope.match_format in LIMITED
    metrics = cohort.evaluated.get(pid) or evaluate_player(row, cohort.priors, "bat")

    def pct(key):
        return percentile_for(METRICS[key], cohort, metrics[key]["rank_value"])

    def metric(key):
        m = metrics[key]
        return {**{k: m.get(k) for k in ("value", "adjusted", "n", "unit", "ci", "environment")},
                "reliability": _r(m.get("reliability"), 3), "percentile": pct(key), "label": METRICS[key].label}

    phases = []
    if limited:
        for ph, label in (("pp", "Powerplay"), ("mid", "Middle overs"), ("death", "Death overs")):
            phases.append({"phase": label, "runs": row[f"{ph}_runs"], "balls": row[f"{ph}_balls"], "dismissals": row[f"{ph}_outs"],
                           "strike_rate": metric(f"{ph}_sr"), "average": metric(f"{ph}_avg"),
                           "dot_pct": _r(st.ratio(row[f"{ph}_dots"], row[f"{ph}_balls"], 100)),
                           "boundary_pct": _r(st.ratio(row[f"{ph}_bnd"], row[f"{ph}_balls"], 100)),
                           "share_of_balls": _r(st.ratio(row[f"{ph}_balls"], row["balls"], 100))})

    styles = [dict(r) for r in db.execute(text(_VS_STYLE.format(scope=scope_sql)), {**params, "pid": pid}).mappings()]
    style_rows = [{"style": s["bowling_style"], "balls": int(s["balls"]), "runs": int(s["runs"]), "dismissals": int(s["outs"]),
                   "strike_rate": _r(st.ratio(s["runs"], s["balls"], 100)), "average": _r(st.ratio(s["runs"], s["outs"]), 1),
                   "dot_pct": _r(st.ratio(s["dots"], s["balls"], 100)), "boundary_pct": _r(st.ratio(s["bnd"], s["balls"], 100)),
                   "sr_ci": [_r(x * 100) for x in st.mean_interval(s["runs"], s["balls"], cohort.priors["strike_rate"].unit_variance)]
                   if s["balls"] and cohort.priors.get("strike_rate") else None,
                   "sample_warning": "limited matchup sample" if s["balls"] < 60 else None} for s in styles]

    runs_list = [r["runs"] for r in log]
    cons = st.consistency_summary(runs_list, th["sig"], th["poor"])
    window = 10 if len(log) >= 20 else 5 if len(log) >= 10 else None
    rolling_series = []
    if window:
        roll_runs = st.rolling(runs_list, window)
        for i, r in enumerate(log):
            if roll_runs[i] is None:
                continue
            chunk = log[i - window + 1:i + 1]
            balls = sum(c["balls"] for c in chunk)
            rolling_series.append({"index": i + 1, "date": r["start_date"].isoformat(), "runs_per_innings": roll_runs[i],
                                   "strike_rate": _r(st.ratio(sum(c["runs"] for c in chunk), balls, 100))})
    buckets = [("0–9", 0, 9), ("10–19", 10, 19), ("20–29", 20, 29), ("30–49", 30, 49), ("50–99", 50, 99), ("100+", 100, 10**6)]
    distribution = [{"bucket": b, "innings": sum(1 for x in runs_list if lo <= x <= hi)} for b, lo, hi in buckets]

    bands = [("1–2", (1, 2)), ("3", (3,)), ("4–5", (4, 5)), ("6–7", (6, 7)), ("8+", tuple(range(8, 13)))]
    by_position = []
    for label, pos in bands:
        rows = [r for r in log if r["batting_position"] in pos]
        if rows:
            by_position.append({"positions": label, **_bat_line(rows)})

    by_season = []
    for season in sorted({r["season"] for r in log}):
        rows = [r for r in log if r["season"] == season]
        by_season.append({"season": season, **_bat_line(rows)})

    by_country = {}
    for r in log:
        by_country.setdefault(r.get("venue_country") or "Unknown", []).append(r)
    conditions = sorted(({"country": k, **_bat_line(v)} for k, v in by_country.items()), key=lambda x: -x["balls"])[:8]

    recent = log[-10:]
    situations = []
    if limited:
        first = [r for r in log if r["innings_number"] == 1]
        chase = [r for r in log if r["is_chase"]]
        won = [r for r in chase if r["team_won"]]
        lost = [r for r in chase if r["team_won"] is False]
        situations = [{"situation": "Batting first", **_bat_line(first)}, {"situation": "Chasing", **_bat_line(chase)},
                      {"situation": "Successful chases", **_bat_line(won),
                       "not_out_pct": _r(st.ratio(sum(1 for r in won if not r["dismissed"]), len(won), 100))},
                      {"situation": "Unsuccessful chases", **_bat_line(lost)},
                      {"situation": "Entered after early collapse", **_bat_line(
                          [r for r in log if r["entry_wickets"] >= 2 and r["entry_over"] < th["pp_end"] and r["batting_position"] >= 3])}]

    dismissal_total = row["outs"] or 0
    dismissals = [{"type": label, "count": int(row[key]), "share": _r(st.ratio(row[key], dismissal_total, 100))}
                  for key, label in (("out_caught", "Caught"), ("out_bowled", "Bowled"), ("out_lbw", "LBW"),
                                     ("out_run_out", "Run out"), ("out_stumped", "Stumped"),
                                     ("out_caught_and_bowled", "Caught & bowled"), ("out_other", "Other")) if row[key]]
    runs_from_fours, runs_from_sixes = 4 * row["fours"], 6 * row["sixes"]
    scoring = {"runs": row["runs"], "from_fours_pct": _r(st.ratio(runs_from_fours, row["runs"], 100)),
               "from_sixes_pct": _r(st.ratio(runs_from_sixes, row["runs"], 100)),
               "from_running_pct": _r(st.ratio(row["runs"] - runs_from_fours - runs_from_sixes, row["runs"], 100)),
               "dot_pct": metric("dot_pct"), "boundary_pct": metric("boundary_pct"), "rotation_pct": metric("rotation_pct")}

    top = sorted(log, key=lambda r: (-r["runs"], r["balls"]))[:5]
    return {
        "summary": {"matches": row["matches"], "innings": row["innings"], "runs": row["runs"], "balls": row["balls"],
                    "dismissals": row["outs"], "not_outs": row["innings"] - row["outs"],
                    "fifties": sum(1 for x in runs_list if 50 <= x < 100), "hundreds": sum(1 for x in runs_list if x >= 100),
                    "highest": max(runs_list) if runs_list else None,
                    "highest_match_id": top[0].get("match_id") if top else None,
                    "average": metric("average"), "strike_rate": metric("strike_rate"), "sr_index": metric("sr_index"),
                    "balls_per_dismissal": metric("balls_per_dismissal"),
                    "first_date": row["first_date"].isoformat() if row.get("first_date") else None,
                    "last_date": row["last_date"].isoformat() if row.get("last_date") else None},
        "recent_form": {"innings": len(recent), "recent": _bat_line(recent), "career": _bat_line(log),
                        "log": [{**_match_ref(r), "runs": r["runs"], "balls": r["balls"], "position": r["batting_position"],
                                 "dismissal": r["dismissal_type"] if r["dismissed"] else "not out"} for r in reversed(recent)]},
        "phases": phases,
        "matchups": {
            "pace": {"balls": row["pace_balls"], "runs": row["pace_runs"], "dismissals": row["pace_outs"],
                     "strike_rate": metric("pace_sr"), "average": metric("pace_avg"),
                     "dot_pct": _r(st.ratio(row["pace_dots"], row["pace_balls"], 100))},
            "spin": {"balls": row["spin_balls"], "runs": row["spin_runs"], "dismissals": row["spin_outs"],
                     "strike_rate": metric("spin_sr"), "average": metric("spin_avg"),
                     "dot_pct": _r(st.ratio(row["spin_dots"], row["spin_balls"], 100))},
            "unclassified_balls": row["balls"] - row["pace_balls"] - row["spin_balls"],
            "classified_share": _r(st.ratio(row["pace_balls"] + row["spin_balls"], row["balls"], 100)),
            "by_style": style_rows,
            "handedness": "Left- vs right-arm bowling is covered by the detailed-style table (arm is part of each sourced style).",
        },
        "consistency": {**cons, "distribution": distribution, "rolling_window": window, "rolling": rolling_series,
                        "significant_threshold": th["sig"], "poor_threshold": th["poor"],
                        "early_out_pct": metric("early_out_pct")},
        "positions": {"primary": primary_positions(row), "by_position": by_position},
        "situations": situations,
        "dismissals": dismissals,
        "scoring": scoring,
        "seasons": by_season,
        "conditions": conditions,
        "evidence": {"top_innings": [{**_match_ref(r), "runs": r["runs"], "balls": r["balls"], "fours": r["fours"],
                                      "sixes": r["sixes"], "position": r["batting_position"],
                                      "not_out": not r["dismissed"], "chase": r["is_chase"], "won": r["team_won"]} for r in top]},
    }


def _bowling_section(db: Session, data, pid: str, scope: Scope, cohort) -> Optional[dict]:
    row = data.bowl.get(pid)
    if not row:
        return None
    scope_sql, params = scope.sql("b")
    log = [dict(r) for r in db.execute(text(_BOWL_LOG.format(scope=scope_sql)), {**params, "pids": [pid]}).mappings()]
    th = data.thresholds
    limited = scope.match_format in LIMITED
    metrics = cohort.evaluated.get(pid) or evaluate_player(row, cohort.priors, "bowl")

    def metric(key):
        m = metrics[key]
        return {**{k: m.get(k) for k in ("value", "adjusted", "n", "unit", "ci", "environment")},
                "reliability": _r(m.get("reliability"), 3),
                "percentile": percentile_for(METRICS[key], cohort, m["rank_value"]), "label": METRICS[key].label}

    phases = []
    if limited:
        for ph, label in (("pp", "Powerplay"), ("mid", "Middle overs"), ("death", "Death overs")):
            balls = row[f"{ph}_balls"]
            phases.append({"phase": label, "legal_balls": balls, "runs": row[f"{ph}_runs"], "wickets": row[f"{ph}_wkts"],
                           "economy": metric(f"{ph}_economy"), "balls_per_wicket": metric(f"{ph}_strike_rate"),
                           "dot_pct": _r(st.ratio(row[f"{ph}_dots"], balls, 100)),
                           "boundary_pct": _r(st.ratio(row[f"{ph}_bnd"], balls, 100)),
                           "share_of_balls": _r(st.ratio(balls, row["legal_balls"], 100))})
    spells = [r for r in log if r["legal_balls"] >= th["spell_min"]]
    econ_list = [r["runs"] * 6 / r["legal_balls"] for r in spells]
    wkts_list = [r["wickets"] for r in log]
    window = 10 if len(log) >= 20 else 5 if len(log) >= 10 else None
    rolling_series = []
    if window:
        for i in range(window - 1, len(log)):
            chunk = log[i - window + 1:i + 1]
            balls = sum(c["legal_balls"] for c in chunk)
            rolling_series.append({"index": i + 1, "date": log[i]["start_date"].isoformat(),
                                   "economy": _r(st.ratio(sum(c["runs"] for c in chunk), balls, 6), 2),
                                   "wickets_per_innings": _r(sum(c["wickets"] for c in chunk) / window, 2)})
    wk_total = row["wickets"] or 0
    dismissals = [{"type": label, "count": int(row[key]), "share": _r(st.ratio(row[key], wk_total, 100))}
                  for key, label in (("wk_caught", "Caught (incl. c&b)"), ("wk_bowled", "Bowled"), ("wk_lbw", "LBW"),
                                     ("wk_stumped", "Stumped"), ("wk_other", "Other")) if row[key]]
    by_country = {}
    for r in log:
        by_country.setdefault(r.get("venue_country") or "Unknown", []).append(r)
    conditions = sorted(({"country": k, **_bowl_line(v)} for k, v in by_country.items()), key=lambda x: -x["legal_balls"])[:8]
    situations = []
    if limited:
        defend = [r for r in log if r["is_defending"]]
        situations = [{"situation": "Bowling first", **_bowl_line([r for r in log if r["innings_number"] == 1])},
                      {"situation": "Defending a target", **_bowl_line(defend)},
                      {"situation": "Successful defences", **_bowl_line([r for r in defend if r["team_won"]])},
                      {"situation": "Unsuccessful defences", **_bowl_line([r for r in defend if r["team_won"] is False])}]
    best = sorted(log, key=lambda r: (-r["wickets"], r["runs"]))[:5]
    recent = log[-10:]
    by_season = [{"season": s, **_bowl_line([r for r in log if r["season"] == s])} for s in sorted({r["season"] for r in log})]
    return {
        "summary": {"matches": row["matches"], "innings": row["innings"], "legal_balls": row["legal_balls"],
                    "overs": f"{int(row['legal_balls']) // 6}.{int(row['legal_balls']) % 6}", "runs": row["runs"],
                    "wickets": row["wickets"], "economy": metric("economy"), "econ_index": metric("econ_index"),
                    "average": metric("bowling_average"), "strike_rate": metric("bowling_strike_rate"),
                    "dot_pct": metric("bowl_dot_pct"), "boundary_pct_conceded": metric("boundary_pct_conceded"),
                    "wides_noballs_per_over": _r(st.ratio(row["wides"] + row["noballs"], row["legal_balls"], 6), 2),
                    "hauls": row["hauls"], "haul_threshold": th["haul"]},
        "recent_form": {"recent": _bowl_line(recent), "career": _bowl_line(log),
                        "log": [{**_match_ref(r), "overs": f"{r['legal_balls'] // 6}.{r['legal_balls'] % 6}", "runs": r["runs"],
                                 "wickets": r["wickets"]} for r in reversed(recent)]},
        "phases": phases,
        "consistency": {"spells": len(spells), "spell_min_balls": th["spell_min"],
                        "economy_median": _r(st.quantile(econ_list, 0.5), 2), "economy_sd": _r(st.consistency_summary(econ_list, 0, 0).get("sd"), 2),
                        "good_spell_pct": metric("good_spell_pct"), "wicketless_pct": metric("wicketless_pct"),
                        "haul_pct": metric("haul_pct"),
                        "par_economy": _r((row.get("par_rpb") or 0) * 6, 2),
                        "wickets_distribution": [{"wickets": w if w < 4 else "4+", "innings": sum(1 for x in wkts_list if (x == w if w < 4 else x >= 4))}
                                                 for w in range(0, 5)],
                        "rolling_window": window, "rolling": rolling_series},
        "dismissals": dismissals,
        "situations": situations,
        "conditions": conditions,
        "seasons": by_season,
        "matchups": {"handedness": "Not available: batting hand is sourced for too few players (5) to split by left/right-handed batters."},
        "evidence": {"best_figures": [{**_match_ref(r), "wickets": r["wickets"], "runs": r["runs"],
                                       "overs": f"{r['legal_balls'] // 6}.{r['legal_balls'] % 6}"} for r in best]},
    }


def _format_suitability(db: Session, pid: str, scope: Scope) -> List[dict]:
    out = []
    for fmt in FORMATS:
        fscope = Scope(fmt, scope.gender)
        exists = db.execute(text(
            "SELECT (SELECT COUNT(*) FROM scouting_bat_innings WHERE player_id=:p AND match_format=:f) + "
            "(SELECT COUNT(*) FROM scouting_bowl_innings WHERE player_id=:p AND match_format=:f)"), {"p": pid, "f": fmt}).scalar()
        if not exists:
            continue
        data = load_scope(db, fscope)
        entry = {"format": fmt, "batting": None, "bowling": None}
        if data.bat.get(pid):
            row = data.bat[pid]
            cohort = build_cohort(data, ROLES["batter"], "bat")
            ev = cohort.evaluated.get(pid) or evaluate_player(row, cohort.priors, "bat")
            entry["batting"] = {"innings": row["innings"], "runs": row["runs"],
                                "average": ev["average"]["value"], "strike_rate": ev["strike_rate"]["value"],
                                "average_pct": percentile_for(METRICS["average"], cohort, ev["average"]["rank_value"]),
                                "sr_index": ev["sr_index"]["adjusted"],
                                "sr_index_pct": percentile_for(METRICS["sr_index"], cohort, ev["sr_index"]["rank_value"]),
                                "regular": meets_baseline(row, "bat", data.thresholds), "comparison_group": len(cohort.members)}
        if data.bowl.get(pid):
            row = data.bowl[pid]
            cohort = build_cohort(data, ROLES["bowler"], "bowl")
            ev = cohort.evaluated.get(pid) or evaluate_player(row, cohort.priors, "bowl")
            entry["bowling"] = {"innings": row["innings"], "wickets": row["wickets"],
                                "economy": ev["economy"]["value"], "bowling_strike_rate": ev["bowling_strike_rate"]["value"],
                                "econ_index": ev["econ_index"]["adjusted"],
                                "econ_index_pct": percentile_for(METRICS["econ_index"], cohort, ev["econ_index"]["rank_value"]),
                                "strike_rate_pct": percentile_for(METRICS["bowling_strike_rate"], cohort, ev["bowling_strike_rate"]["rank_value"]),
                                "regular": meets_baseline(row, "bowl", data.thresholds), "comparison_group": len(cohort.members)}
        out.append(entry)
    return out


def default_role(data, pid: str) -> str:
    fits = []
    bat, bowl = data.bat.get(pid), data.bowl.get(pid)
    th = data.thresholds
    bat_reg, bowl_reg = meets_baseline(bat, "bat", th), meets_baseline(bowl, "bowl", th)
    if bat_reg and bowl_reg:
        return "all_rounder"
    if bowl_reg or (bowl and not bat_reg and (bowl["legal_balls"] > (bat or {}).get("balls", 0))):
        cls = (data.attrs.get(pid, {}).get("bowling_type") or "").lower()
        return "pace_bowler" if cls == "pace" else "spin_bowler" if cls == "spin" else "bowler"
    return "batter"


def format_suitability(db: Session, scope: Scope, pid: str) -> dict:
    return {"player_id": pid, "gender": scope.gender, "formats": _format_suitability(db, pid, scope),
            "note": "Each format is compared only with regular batters/bowlers of that format; formats are never merged."}


def build_report(db: Session, scope: Scope, pid: str, role_key: Optional[str] = None) -> dict:
    data = load_scope(db, scope)
    if pid not in data.bat and pid not in data.bowl:
        return {"player_id": pid, "available": False, "scope": scope.describe(),
                "player_name": _name(db, pid),
                "message": "No batting or bowling innings for this player in the selected scope."}
    if role_key in ROLES and ROLES[role_key].limited_only and scope.match_format not in LIMITED:
        role_key = None
    role_key = role_key if role_key in ROLES else default_role(data, pid)
    role = ROLES[role_key]
    discs = ("bat", "bowl") if role.disc == "allround" else (role.disc,)
    cohorts = {d: build_cohort(data, role, d) for d in discs}
    weights = _role_weights(role, scope.match_format, None)
    evaluation = evaluate_candidate(pid, data, role, Requirements(role=role_key), cohorts, weights)
    size = len(cohorts[discs[0]].members)
    label = f"{role.label.lower()}s" if role.disc != "allround" else "regulars"
    strengths, weaknesses = narrative(evaluation["metrics"], label, size)

    bat_cohort = cohorts.get("bat") or build_cohort(data, ROLES["batter"], "bat")
    bowl_cohort = cohorts.get("bowl") or build_cohort(data, ROLES["bowler"], "bowl")
    batting = _batting_section(db, data, pid, scope, bat_cohort)
    bowling = _bowling_section(db, data, pid, scope, bowl_cohort)
    identity = player_identity(pid, data)

    reliability_rows = [{"metric": m["label"], "n": m["n"], "unit": m["unit"], "reliability": m["reliability"],
                         "ci": m["ci"], "value": m["value"], "adjusted": m["adjusted"]} for m in evaluation["metrics"]]
    limited_matchups = []
    if batting:
        for s in batting["matchups"]["by_style"]:
            if s["sample_warning"]:
                limited_matchups.append(f"{s['style']}: only {s['balls']} balls")
        share = batting["matchups"]["classified_share"]
        if share is not None and share < 50:
            limited_matchups.append(f"Only {share}% of balls faced came from bowlers with a sourced pace/spin classification.")

    return {
        "player_id": pid, "available": True, "scope": scope.describe(),
        "overview": identity,
        "role": {"evaluated_as": role.label, "role_key": role.key, "rationale": role.rationale,
                 "observed_role": identity["observed_role"], "observed_basis": identity["observed_role_basis"],
                 "metadata_role": identity["metadata_role"], "primary_position": identity["primary_position"],
                 "allrounder_type": evaluation.get("allrounder_type"), "dual_matches": data.dual.get(pid, 0)},
        "batting": batting,
        "bowling": bowling,
        "strengths": strengths,
        "weaknesses": weaknesses,
        "reliability": {"overall": evaluation["reliability"], "tier": evaluation["tier"], "metrics": reliability_rows,
                        "limited_matchups": limited_matchups,
                        "explanation": "Reliability = n / (n + m): the share of each shrunk estimate that comes from the "
                                       "player's own data, where m is the cohort-estimated prior strength."},
        "recruitment": {"role": role.label, "score": evaluation["score"], "comparison_group": size,
                        "comparison_note": cohorts[discs[0]].fallback_note,
                        "metrics": evaluation["metrics"], "role_fit": role_fit(db, scope, pid),
                        "batting_score": (evaluation.get("batting") or {}).get("score"),
                        "bowling_score": (evaluation.get("bowling") or {}).get("score")},
    }


def compare(db: Session, scope: Scope, pids: Sequence[str], role_key: str) -> dict:
    if role_key not in ROLES:
        raise ValueError(f"Unknown role model '{role_key}'")
    role = ROLES[role_key]
    data = load_scope(db, scope)
    discs = ("bat", "bowl") if role.disc == "allround" else (role.disc,)
    cohorts = {d: build_cohort(data, role, d) for d in discs}
    weights = _role_weights(role, scope.match_format, None)
    scope_sql, params = scope.sql("b")
    bat_logs: Dict[str, List[dict]] = {}
    for r in db.execute(text(_BAT_LOG_ALL.format(scope=scope_sql)), {**params, "pids": list(pids)}).mappings():
        bat_logs.setdefault(r["player_id"], []).append(dict(r))
    bowl_logs: Dict[str, List[dict]] = {}
    for r in db.execute(text(_BOWL_LOG.format(scope=scope_sql)), {**params, "pids": list(pids)}).mappings():
        bowl_logs.setdefault(r["player_id"], []).append(dict(r))
    th = data.thresholds
    players = []
    for pid in pids:
        if pid not in data.bat and pid not in data.bowl:
            players.append({"player_id": pid, "available": False, "identity": {"player_id": pid,
                            "player_name": data.attrs.get(pid, {}).get("name") or _name(db, pid)}})
            continue
        ev = evaluate_candidate(pid, data, role, Requirements(role=role_key), cohorts, weights)
        entry = {"player_id": pid, "available": True, "identity": ev["identity"], "score": ev["score"],
                 "reliability": ev["reliability"], "tier": ev["tier"], "metrics": ev["metrics"],
                 "allrounder_type": ev.get("allrounder_type"), "dual_matches": data.dual.get(pid, 0)}
        bat = data.bat.get(pid)
        if bat:
            log = bat_logs.get(pid, [])
            bat_ev = (cohorts.get("bat") or build_cohort(data, ROLES["batter"], "bat"))
            m = bat_ev.evaluated.get(pid) or evaluate_player(bat, bat_ev.priors, "bat")
            entry["batting"] = {
                "career": _bat_line(log), "recent": _bat_line(log[-10:]),
                "phases": {ph: {"strike_rate": m[f"{ph}_sr"]["value"], "balls": int(bat[f"{ph}_balls"]),
                                "average": m[f"{ph}_avg"]["value"]} for ph in ("pp", "mid", "death")} if scope.match_format in LIMITED else None,
                "pace": {"strike_rate": m["pace_sr"]["value"], "average": m["pace_avg"]["value"], "balls": int(bat["pace_balls"])},
                "spin": {"strike_rate": m["spin_sr"]["value"], "average": m["spin_avg"]["value"], "balls": int(bat["spin_balls"])},
                "consistency": st.consistency_summary([r["runs"] for r in log], th["sig"], th["poor"]),
                "primary_position": primary_positions(bat),
            }
        bowl = data.bowl.get(pid)
        if bowl:
            log = bowl_logs.get(pid, [])
            bowl_ev = (cohorts.get("bowl") or build_cohort(data, ROLES["bowler"], "bowl"))
            m = bowl_ev.evaluated.get(pid) or evaluate_player(bowl, bowl_ev.priors, "bowl")
            spells = [r for r in log if r["legal_balls"] >= th["spell_min"]]
            econs = [r["runs"] * 6 / r["legal_balls"] for r in spells]
            entry["bowling"] = {
                "career": _bowl_line(log), "recent": _bowl_line(log[-10:]),
                "phases": {ph: {"economy": m[f"{ph}_economy"]["value"], "balls": int(bowl[f"{ph}_balls"]),
                                "balls_per_wicket": m[f"{ph}_strike_rate"]["value"]} for ph in ("pp", "mid", "death")} if scope.match_format in LIMITED else None,
                "consistency": {"spells": len(spells), "economy_median": _r(st.quantile(econs, 0.5), 2),
                                "economy_sd": _r(st.consistency_summary(econs, 0, 0).get("sd"), 2),
                                "good_spell_pct": m["good_spell_pct"]["value"], "wicketless_pct": m["wicketless_pct"]["value"]},
            }
        players.append(entry)
    return {"scope": scope.describe(), "role": {"key": role.key, "label": role.label},
            "comparison_group": {d: len(cohorts[d].members) for d in discs},
            "weights": {d: weights[d] for d in discs}, "players": players}


def _name(db: Session, pid: str) -> str:
    return db.execute(text("SELECT canonical_name FROM players WHERE id=:p"), {"p": pid}).scalar() or "Unknown"
