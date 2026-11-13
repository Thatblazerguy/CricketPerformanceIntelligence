"""Match Simulator orchestration: XI validation, single-match runs and Monte Carlo jobs.

The engine itself (``app.ml.match_simulator``) is pure Python and DB-free; this
module loads calibration and player data once per request, validates the two
Playing XIs against the CPI player database, and runs simulations in background
jobs so API calls never block.
"""
from __future__ import annotations

import logging
import math
import random
import threading
import time
import uuid
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.analytics.scorecard import build_innings_scorecard
from app.ml import sim_calibration as cal
from app.ml.match_simulator import (
    GENUINE_BOWLER_BALLS, MAX_SIMULATIONS, PART_TIME_BALLS, FormatRules, SimModel, TeamSetup, win_probability_path,
    aggregate_monte_carlo, bowling_options, impact_scores, is_frontline, player_match_lines, player_of_match,
    result_text, rules_for, run_batch, simulate_match,
)

logger = logging.getLogger(__name__)
WP_ARTIFACTS_DIR = Path(__file__).resolve().parents[2] / "artifacts" / "win_probability"
PITCHES = ("balanced", "batting", "bowling", "spin", "seam")
WEATHER = ("clear", "overcast", "dew")
MIN_SIMULATIONS = 10


class SetupError(ValueError):
    """Raised when the match setup fails validation; carries the full report."""

    def __init__(self, report: dict):
        super().__init__("; ".join(report.get("errors", [])) or "Invalid match setup")
        self.report = report


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _role(profile: dict) -> str:
    bat, bowl = profile.get("bat_balls", 0), profile.get("bowl_balls", 0)
    if bat >= 120 and bowl >= 120:
        # Workload balance decides: a frontline bowler who bats a little is still a bowler.
        if bowl > 3 * bat:
            return "Bowler"
        if bat > 4 * bowl:
            return "Batter"
        return "All-Rounder"
    if bowl >= 120:
        return "Bowler"
    if bat >= 120:
        return "Batter"
    return "Limited data"


def validate_payload_shape(payload: dict) -> List[str]:
    """Cheap structural checks that need no database."""
    errors = []
    fmt = payload.get("format", "T20")
    try:
        rules_for(fmt, overs=payload.get("overs"))
    except ValueError as exc:
        errors.append(str(exc))
    teams = payload.get("teams") or {}
    seen_in: Dict[str, str] = {}
    for key in ("A", "B"):
        team = teams.get(key) or {}
        label = team.get("name") or f"Team {key}"
        players = team.get("players") or []
        if len(players) != 11:
            errors.append(f"{label}: a Playing XI needs exactly 11 players (has {len(players)})")
        unmatched = [p.get("input_name") or p.get("name") or "?" for p in players if not p.get("id")]
        if unmatched:
            errors.append(f"{label}: not found in the CPI player database: {', '.join(unmatched)}. Swap or remove them.")
        counts = defaultdict(int)
        for p in players:
            if p.get("id"):
                counts[p["id"]] += 1
        dups = [next((p.get("name") for p in players if p.get("id") == pid), pid) for pid, c in counts.items() if c > 1]
        if dups:
            errors.append(f"{label}: duplicate player(s) {', '.join(dups)}")
        for pid in counts:
            if pid in seen_in and seen_in[pid] != key:
                name = next((p.get("name") for p in players if p.get("id") == pid), pid)
                errors.append(f"{name} is in both XIs; a player can only play for one side")
            seen_in[pid] = key
    names = [(teams.get(k) or {}).get("name", "").strip().casefold() for k in ("A", "B")]
    if names[0] and names[0] == names[1]:
        errors.append("Both teams have the same name; rename one so results are unambiguous")
    cond = payload.get("conditions") or {}
    if cond.get("pitch", "balanced") not in PITCHES:
        errors.append(f"Unknown pitch type {cond.get('pitch')!r}")
    if cond.get("weather", "clear") not in WEATHER:
        errors.append(f"Unknown weather {cond.get('weather')!r}")
    if cond.get("toss_winner", "random") not in ("A", "B", "random"):
        errors.append("Toss winner must be A, B or random")
    if cond.get("toss_decision", "auto") not in ("bat", "field", "auto"):
        errors.append("Toss decision must be bat, field or auto")
    return errors


def build_context(db, payload: dict, *, require_valid: bool = True) -> dict:
    """Validate the setup and prepare the engine model. Returns a context dict.

    Raises :class:`SetupError` (with the validation report) on blocking errors
    when ``require_valid`` is set.
    """
    errors = validate_payload_shape(payload)
    warnings: List[str] = []
    fmt = payload.get("format", "T20")
    cond = payload.get("conditions") or {}
    report: Dict[str, Any] = {"errors": errors, "warnings": warnings, "teams": {}, "format": fmt}
    try:
        rules = rules_for(fmt, overs=payload.get("overs"), super_over=bool(cond.get("super_over", True)))
    except ValueError:
        report["valid"] = False
        if require_valid:
            raise SetupError(report)
        return {"report": report}
    teams_in = payload.get("teams") or {}
    all_ids = [p["id"] for k in ("A", "B") for p in (teams_in.get(k) or {}).get("players", []) if p.get("id")]
    meta = cal.load_player_meta(db, all_ids)
    missing = [pid for pid in all_ids if pid not in meta]
    if missing:
        errors.append(f"Unknown player id(s): {', '.join(missing[:5])}")
    family = rules.family
    gender = payload.get("gender") or cal.infer_gender(db, all_ids)
    # Mixed men's/women's selections are not a valid fixture.
    if all_ids:
        from sqlalchemy import bindparam, text
        rows = db.execute(text("""SELECT x.pid, ARRAY_AGG(DISTINCT m.gender) FROM (
              SELECT DISTINCT ON (d.batter_id) d.batter_id AS pid, d.innings_id FROM deliveries d WHERE d.batter_id IN :ids
              UNION SELECT DISTINCT ON (d.bowler_id) d.bowler_id, d.innings_id FROM deliveries d WHERE d.bowler_id IN :ids) x
            JOIN match_innings mi ON mi.id = x.innings_id JOIN matches m ON m.id = mi.match_id GROUP BY x.pid""")
            .bindparams(bindparam("ids", expanding=True)), {"ids": all_ids}).all()
        other = [meta.get(pid, {}).get("name", pid) for pid, genders in rows if genders and gender not in genders]
        if other:
            errors.append(f"Mixed men's and women's players: {', '.join(other[:6])} have no {gender} matches")
    calibration = cal.load_format_calibration(db, family)
    if gender not in calibration["genders"]:
        errors.append(f"No {gender} {family} history in CPI to calibrate the simulation")
    profiles = cal.load_player_profiles(db, family, gender, all_ids) if all_ids else {}
    venue = None
    if cond.get("venue_id"):
        venue = cal.load_venue_profile(db, family, gender, cond["venue_id"])
        if not venue or not venue.get("name"):
            errors.append("Selected venue was not found")
        elif venue.get("deliveries", 0) == 0:
            warnings.append(f"No {gender} {family} history at {venue['name']}; venue effect is neutral")
        elif venue.get("deliveries", 0) < 3000:
            warnings.append(f"Only {venue['matches']} {family} matches at {venue['name']}; venue effect is heavily smoothed")
    teams: Dict[str, TeamSetup] = {}
    positions: Dict[str, int] = {}
    keepers = set()
    for key in ("A", "B"):
        t = teams_in.get(key) or {}
        players = [p for p in t.get("players", []) if p.get("id")]
        order = [p["id"] for p in players]
        keeper_ids = [p["id"] for p in players if p.get("is_wicketkeeper")]
        captain_ids = [p["id"] for p in players if p.get("is_captain")]
        label = t.get("name") or f"Team {key}"
        if not keeper_ids:
            warnings.append(f"{label}: no wicketkeeper marked; stumpings will be recorded as catches")
        elif len(keeper_ids) > 1:
            warnings.append(f"{label}: {len(keeper_ids)} wicketkeepers marked; {meta.get(keeper_ids[0], {}).get('name', keeper_ids[0])} keeps")
        if len(captain_ids) > 1:
            warnings.append(f"{label}: more than one captain marked")
        for i, pid in enumerate(order):
            positions[pid] = i + 1
        keeper = keeper_ids[0] if keeper_ids else None
        if keeper:
            keepers.add(keeper)
        teams[key] = TeamSetup(key, label, order, keeper=keeper, captain=captain_ids[0] if captain_ids else None,
                               team_id=t.get("team_id"))
    model = SimModel(calibration, family, gender, profiles, meta, venue=venue,
                     pitch=cond.get("pitch", "balanced"), weather=cond.get("weather", "clear"),
                     positions=positions, keepers=keepers)
    for key, team in teams.items():
        label = team.name
        players_out = []
        for i, pid in enumerate(team.order):
            prof = profiles.get(pid) or {}
            m = meta.get(pid, {})
            role = _role(prof)
            outs = prof.get("bat_outs", 0)
            players_out.append({
                "id": pid, "name": m.get("name", pid), "position": i + 1, "role": role,
                "bowling_type": m.get("bowling_type"), "bowling_style": m.get("bowling_style"),
                "is_wicketkeeper": pid == team.keeper, "is_captain": pid == team.captain,
                "batting_balls": prof.get("bat_balls", 0), "bowling_balls": prof.get("bowl_balls", 0),
                "batting_average": round(prof.get("bat_runs", 0) / outs, 1) if outs else None,
                "strike_rate": round(100 * prof.get("bat_runs", 0) / prof["bat_balls"], 1) if prof.get("bat_balls") else None,
                "economy": round(6 * prof.get("bowl_runs", 0) / prof["bowl_balls"], 2) if prof.get("bowl_balls") else None,
                "bowling_wickets": prof.get("bowl_wkts", 0),
            })
            if not prof.get("bat_balls") and not prof.get("bowl_balls"):
                warnings.append(f"{label}: {m.get('name', pid)} has no {gender} {family} record since {cal.FAMILY_SINCE[family].year}; a batting-position prior is used")
            elif role == "Bowler" and i < 4:
                warnings.append(f"{label}: {m.get('name', pid)} is a specialist bowler batting at No. {i + 1}")
            elif role == "Batter" and i >= 8 and prof.get("bat_balls", 0) >= 600:
                warnings.append(f"{label}: {m.get('name', pid)} is a frontline batter listed at No. {i + 1}")
            if pid == team.keeper and prof.get("bowl_balls", 0) >= GENUINE_BOWLER_BALLS:
                warnings.append(f"{label}: wicketkeeper {m.get('name', pid)} is also a frontline bowler and will not bowl")
        if len(team.order) == 11:
            opts = bowling_options(model, team, rules)
            genuine = [p for p in opts if is_frontline(model, p)]
            needed = math.ceil((rules.overs or 90) / (rules.max_bowler_overs or 25))
            if rules.limited and len(genuine) < needed:
                part = len(opts) - len(genuine)
                warnings.append(f"{label}: only {len(genuine)} frontline bowler(s); {part} part-timer(s) will share the remaining overs")
            if not rules.limited and len(genuine) < 4:
                warnings.append(f"{label}: only {len(genuine)} frontline bowler(s) for a Test attack")
            team.bowling_options = opts
            bowl_list = [{"id": p, "name": meta.get(p, {}).get("name", p), "bowling_type": meta.get(p, {}).get("bowling_type"),
                          "frontline": p in genuine, "balls": (profiles.get(p) or {}).get("bowl_balls", 0)} for p in opts]
        else:
            bowl_list = []
        report["teams"][key] = {"name": label, "players": players_out, "bowling_options": bowl_list,
                                "keeper": team.keeper, "captain": team.captain}
    report.update({
        "valid": not errors, "family": family, "gender": gender, "rules": _rules_dict(rules),
        "venue": {k: venue.get(k) for k in ("venue_id", "name", "city", "country", "matches", "deliveries")} if venue else None,
        "calibration": model.calibration_meta,
        "max_simulations": MAX_SIMULATIONS[family],
        "toss_field_probability": round(model.toss_field_p, 3),
    })
    if errors and require_valid:
        raise SetupError(report)
    return {"report": report, "model": model, "rules": rules, "teams": teams, "meta": meta, "gender": gender,
            "conditions": cond}


def _rules_dict(rules: FormatRules) -> dict:
    return {"format": rules.fmt, "family": rules.family, "overs": rules.overs, "max_bowler_overs": rules.max_bowler_overs,
            "innings": rules.innings, "free_hit": rules.free_hit, "super_over": rules.super_over,
            "match_overs": rules.match_overs}


# ---------------------------------------------------------------------------
# Single detailed match
# ---------------------------------------------------------------------------

def _wp_model(family: str):
    try:
        import joblib
        path = WP_ARTIFACTS_DIR / f"{family.lower()}.joblib"
        if not path.exists():
            return None, None
        art = joblib.load(str(path))
        pipe = art["model"] if isinstance(art, dict) else art
        version = art.get("version") if isinstance(art, dict) else None
        return pipe, version
    except Exception:  # pragma: no cover - optional dependency path
        logger.warning("Win-probability model unavailable", exc_info=True)
        return None, None


# ~±1.5 percentage points of Monte Carlo error per point by default; up to 5,000 on request.
WP_DEFAULT_SIMS = {"T20": 500, "ODI": 250}
WP_MAX_SIMS = 5000


def win_probability_curve(result: dict, rules: FormatRules, gender: str, ctx: Optional[dict] = None, seed: int = 0,
                          sims: Optional[int] = None, progress=None) -> dict:
    """Team-A win probability before the match and after each over.

    Limited overs: re-simulated from each over's state with the actual XIs (so
    player strength counts). Tests: CPI's trained state-based WP model."""
    if rules.limited and ctx is not None:
        sims = max(100, min(int(sims or WP_DEFAULT_SIMS[rules.family]), WP_MAX_SIMS))
        step = 1 if rules.family == "T20" else 2
        points = win_probability_path(ctx["model"], rules, ctx["teams"], result, sims=sims, seed=seed, step=step, progress=progress)
        if points:
            w = result.get("winner")
            last = points[-1]
            points.append({**last, "label": "result", "team_a": 1.0 if w == "A" else 0.0, "team_b": 1.0 if w == "B" else 0.0,
                           "draw_or_tie": 1.0 if w is None else 0.0, "exact": True, "simulations": 0,
                           "ci_low": 1.0 if w == "A" else 0.0, "ci_high": 1.0 if w == "A" else 0.0})
            teams = ctx["teams"]
            return {"available": True, "method": "simulation", "simulations_per_point": sims,
                    "team": "A", "team_name": teams["A"].name,
                    "estimator": "Jeffreys posterior mean (wins + 1/2)/(n + 1) with 95% interval; ties count half; decided states exact",
                    "conditions": ctx["model"].condition_info,
                    "model_version": "cpi-sim-engine", "points": points}
    import numpy as np
    from app.ml.win_probability import FEATURES, match_state_features
    pipe, version = _wp_model(rules.family)
    if pipe is None:
        return {"available": False, "reason": f"No trained {rules.family} win-probability model", "points": []}
    # (Tests) state-based model trained on CPI history; does not know the XIs.
    rows, points = [], []
    prior = {"A": 0, "B": 0}
    for inn in result["innings"]:
        if inn.super_over:
            continue
        a_batting = inn.batting == "A"
        score = wk = legal = 0
        recent: List[tuple] = []
        def add(label, over_label):
            rr = sum(r for r, _ in recent[-12:])
            rw = sum(w for _, w in recent[-12:])
            feats = match_state_features(
                rules.family, match_format=rules.fmt if rules.family != "Test" else "Test", gender=gender,
                team1_batting=a_batting, is_super_over=False, innings_number=inn.number, innings_runs=score,
                wickets_lost=wk, legal_balls=legal, batting_team_prior_runs=prior[inn.batting],
                opposition_prior_runs=prior[inn.bowling], target_runs=inn.target, target_overs=rules.overs,
                recent_runs=rr, recent_wickets=rw)
            rows.append([np.nan if feats.get(f) is None else feats.get(f) for f in FEATURES[rules.family]])
            points.append({"innings": inn.number, "batting": inn.batting, "over": over_label, "score": score, "wickets": wk, "label": label})
        add("start", 0)
        last_over = -1
        for d in inn.deliveries:
            score += d["total_runs"]
            wk += 1 if d["wicket"] else 0
            if d["legal"]:
                legal += 1
                recent.append((d["total_runs"], 1 if d["wicket"] else 0))
            if d["legal"] and legal % 6 == 0 and legal // 6 != last_over:
                last_over = legal // 6
                add("over", legal // 6)
        if legal % 6:
            add("end", round(legal // 6 + (legal % 6) / 10, 1))
        prior[inn.batting] += inn.runs
    if not rows:
        return {"available": False, "reason": "No deliveries", "points": []}
    try:
        proba = pipe.predict_proba(np.array(rows, dtype=np.float32))
    except Exception as exc:  # pragma: no cover
        return {"available": False, "reason": f"Prediction failed: {exc}", "points": []}
    for p, pr in zip(points, proba):
        p["team_a"] = round(float(pr[0]), 4)
        p["team_b"] = round(float(pr[1]), 4)
        p["draw_or_tie"] = round(float(pr[2]) if len(pr) > 2 else 0.0, 4)
    # Final state: the actual result.
    w = result.get("winner")
    points.append({"innings": points[-1]["innings"], "batting": points[-1]["batting"], "over": points[-1]["over"], "label": "result",
                   "score": points[-1]["score"], "wickets": points[-1]["wickets"],
                   "team_a": 1.0 if w == "A" else 0.0, "team_b": 1.0 if w == "B" else 0.0,
                   "draw_or_tie": 1.0 if w is None else 0.0})
    return {"available": True, "method": "trained_model", "model_version": version, "points": points}


def _turning_points(curve: dict, result: dict, names: Dict[str, str], teams) -> List[dict]:
    pts = curve.get("points") or []
    swings = []
    by_inn = {i.number: i for i in result["innings"]}
    for prev, cur in zip(pts, pts[1:]):
        if cur["label"] in ("start", "result"):
            continue
        delta = cur["team_a"] - prev["team_a"]
        inn = by_inn.get(cur["innings"])
        over_no = int(cur["over"]) if cur["label"] == "over" else math.ceil(cur["over"])
        first_over = int(prev["over"]) if prev["innings"] == cur["innings"] else 0
        events = []
        if inn:
            over_balls = [d for d in inn.deliveries if first_over <= d["over_index"] < over_no]
            runs = sum(d["total_runs"] for d in over_balls)
            for d in over_balls:
                if d["wicket"]:
                    events.append(f"{names.get(d['wicket']['player_out'], '?')} out ({d['wicket']['kind']})")
            sixes = sum(1 for d in over_balls if d["batter_runs"] == 6)
            fours = sum(1 for d in over_balls if d["batter_runs"] == 4)
            bowler = names.get(over_balls[0]["bowler_id"], "?") if over_balls else None
            summary = f"{runs} run{'s' if runs != 1 else ''} off {bowler}" + (f", {fours}x4" if fours else "") + (f", {sixes}x6" if sixes else "")
        else:
            summary = ""
        swings.append({"innings": cur["innings"], "over": over_no, "from_over": first_over, "batting": cur["batting"],
                       "batting_team": teams[cur["batting"]].name, "delta_team_a": round(delta, 4),
                       "team_a_before": prev["team_a"], "team_a_after": cur["team_a"],
                       "score": f"{cur['score']}/{cur['wickets']}", "events": events, "summary": summary})
    swings.sort(key=lambda s: -abs(s["delta_team_a"]))
    return swings[:5]


def _scorecard_rows(inn, names: Dict[str, str], rules: FormatRules) -> List[dict]:
    rows = []
    for d in inn.deliveries:
        w = d["wicket"]
        extras = [{"type": t, "runs": r} for t, r in d["extras"].items()]
        ball_label = d["ball"]
        rows.append({
            "batter_id": d["batter_id"], "batter": names.get(d["batter_id"]), "non_striker": names.get(d["non_striker_id"]),
            "bowler_id": d["bowler_id"], "bowler": names.get(d["bowler_id"]),
            "batter_runs": d["batter_runs"], "total_runs": d["total_runs"],
            "bowling_runs": d["batter_runs"] + sum(r for t, r in d["extras"].items() if t in ("wides", "noballs")),
            "legal": d["legal"], "over_index": d["over_index"], "over_display": f"{d['over_index']}.{ball_label}",
            "faced": "wides" not in d["extras"], "four": d["batter_runs"] == 4, "six": d["batter_runs"] == 6,
            "extra_types": extras,
            "wickets": [{"player_out_id": w["player_out"], "player_out": names.get(w["player_out"]), "kind": w["kind"],
                         "fielder": names.get(w["fielder"]) if w.get("fielder") else None,
                         "batter_dismissed": True, "bowler_credited": w["bowler_credited"]}] if w else [],
        })
    return rows


def _phase_analysis(inn, rules: FormatRules) -> List[dict]:
    from app.ml.sim_calibration import phase_of
    phases: Dict[str, dict] = {}
    for d in inn.deliveries:
        p = "super_over" if inn.super_over else phase_of(rules.family, d["over_index"])
        row = phases.setdefault(p, {"phase": p, "runs": 0, "legal_balls": 0, "wickets": 0, "fours": 0, "sixes": 0, "dots": 0, "extras": 0})
        row["runs"] += d["total_runs"]
        row["legal_balls"] += int(d["legal"])
        row["wickets"] += int(bool(d["wicket"]))
        row["fours"] += int(d["batter_runs"] == 4)
        row["sixes"] += int(d["batter_runs"] == 6)
        row["dots"] += int(d["legal"] and d["total_runs"] == 0)
        row["extras"] += sum(d["extras"].values())
    out = []
    for p in list(cal.PHASES[rules.family]) + ["super_over"]:
        if p in phases:
            r = phases[p]
            r["run_rate"] = round(6 * r["runs"] / r["legal_balls"], 2) if r["legal_balls"] else None
            r["dot_pct"] = round(100 * r["dots"] / r["legal_balls"], 1) if r["legal_balls"] else None
            out.append(r)
    return out


def detailed_match(ctx: dict, seed: int, wp_sims: Optional[int] = None, progress=None) -> dict:
    model, rules, teams, meta, cond = ctx["model"], ctx["rules"], ctx["teams"], ctx["meta"], ctx["conditions"]
    rng = random.Random(f"{seed}:detail")
    result = simulate_match(model, rules, teams, rng, toss_winner=cond.get("toss_winner", "random"),
                            toss_decision=cond.get("toss_decision", "auto"), detailed=True)
    names = {pid: m.get("name", pid) for pid, m in meta.items()}
    innings_out = []
    for inn in result["innings"]:
        card = build_innings_scorecard({"deliveries": _scorecard_rows(inn, names, rules), "is_super_over": inn.super_over}, rules.fmt)
        for p in card["partnerships"]:
            p.pop("delivery_breakdown", None)
        # Batting card in batting order, including not-out non-strikers and those who did not bat.
        by_id = {r["player_id"]: r for r in card["batting"]}
        order = inn.batting_order_used if inn.super_over else teams[inn.batting].order
        batting = []
        for pid in order:
            r = by_id.get(pid)
            if r is None and pid in inn.batting_order_used:
                r = {"player_id": pid, "player": names.get(pid), "runs": 0, "balls": 0, "fours": 0, "sixes": 0, "dismissal": "not out", "strike_rate": None}
            if r is None:
                if inn.super_over:
                    continue
                r = {"player_id": pid, "player": names.get(pid), "runs": None, "balls": None, "fours": None, "sixes": None, "dismissal": "did not bat", "strike_rate": None}
            batting.append(r)
        card["batting"] = batting
        bowl_order = []
        for d in inn.deliveries:
            if d["bowler_id"] not in bowl_order:
                bowl_order.append(d["bowler_id"])
        card["bowling"].sort(key=lambda r: bowl_order.index(r["player_id"]) if r["player_id"] in bowl_order else 99)
        card["phases"] = _phase_analysis(inn, rules)
        # Reconciliation (also asserted in tests).
        bat_total = sum(r["runs"] or 0 for r in batting)
        extras_total = sum(inn.extras.values())
        bowl_total = sum(r["runs"] for r in card["bowling"]) + inn.extras["byes"] + inn.extras["legbyes"]
        card["reconciliation"] = {"batting_plus_extras": bat_total + extras_total, "bowling_plus_byes": bowl_total,
                                  "total": inn.runs, "balanced": bat_total + extras_total == inn.runs == bowl_total}
        innings_out.append({
            "number": inn.number, "batting": inn.batting, "batting_team": teams[inn.batting].name,
            "bowling": inn.bowling, "bowling_team": teams[inn.bowling].name, "runs": inn.runs, "wickets": inn.wickets,
            "legal_balls": inn.legal_balls, "overs": f"{inn.legal_balls // 6}.{inn.legal_balls % 6}", "target": inn.target,
            "declared": inn.declared, "all_out": inn.all_out, "super_over": inn.super_over, "follow_on": inn.follow_on,
            "extras_detail": dict(inn.extras), "scorecard": card,
            "balls": [{"over": d["over_index"], "ball": d["ball"], "batter": names.get(d["batter_id"]), "bowler": names.get(d["bowler_id"]),
                       "outcome": d["outcome"], "runs": d["total_runs"], "batter_runs": d["batter_runs"], "extras": d["extras"],
                       "wicket": ({**d["wicket"], "player_out_name": names.get(d["wicket"]["player_out"]),
                                   "fielder_name": names.get(d["wicket"].get("fielder"))} if d["wicket"] else None),
                       "free_hit": d["free_hit"], "score": d["score"], "wickets": d["wickets"]} for d in inn.deliveries]
                     if rules.limited else [],
        })
    scores = impact_scores(result, rules, teams)
    potm = player_of_match(result, rules, teams, scores)
    curve = win_probability_curve(result, rules, ctx["gender"], ctx, seed, wp_sims, progress)
    lines = player_match_lines(result)
    owner = {pid: k for k, t in teams.items() for pid in t.order}
    top = sorted(scores.items(), key=lambda kv: -kv[1])
    impacts = [{"player_id": pid, "name": names.get(pid), "team": owner.get(pid), "impact": s, **lines.get(pid, {})} for pid, s in top]
    return {
        "seed": seed,
        "result": result_text(result, teams),
        "winner": result.get("winner"), "method": result.get("method"), "tie": bool(result.get("tie")),
        "margin_runs": result.get("margin_runs"), "margin_wickets": result.get("margin_wickets"),
        "toss": {**result["toss"], "winner_name": teams[result["toss"]["winner"]].name},
        "batting_first": result["batting_first"],
        "innings": innings_out,
        "player_of_match": {"player_id": potm, "name": names.get(potm), "team": owner.get(potm), "impact": scores.get(potm),
                            **lines.get(potm, {})} if potm else None,
        "impact": impacts,
        "win_probability": curve,
        "turning_points": _turning_points(curve, result, names, teams) if curve.get("available") else [],
        "summary": _summary(result, innings_out, teams, potm, names, lines),
    }


def _summary(result, innings_out, teams, potm, names, lines) -> List[str]:
    out = [result_text(result, teams) + "."]
    toss = result["toss"]
    out.append(f"{teams[toss['winner']].name} won the toss and chose to {toss['decision']}.")
    for inn in innings_out:
        if inn["super_over"]:
            continue
        card = inn["scorecard"]
        bats = sorted([b for b in card["batting"] if b.get("runs") is not None], key=lambda b: -(b["runs"] or 0))[:2]
        bowls = sorted(card["bowling"], key=lambda b: (-b["wickets"], b["runs"]))[:1]
        part = max(card["partnerships"], key=lambda p: p["runs"], default=None)
        line = f"{inn['batting_team']} {inn['runs']}/{inn['wickets']} ({inn['overs']} ov)"
        if bats:
            line += ": " + ", ".join(f"{b['player']} {b['runs']}({b['balls']})" for b in bats)
        if bowls:
            b = bowls[0]
            line += f"; best bowling {b['player']} {b['wickets']}/{b['runs']}"
        if part and part["runs"] >= 40:
            line += f"; top stand {part['runs']} for wicket {part['number']}"
        out.append(line + ".")
    if potm:
        ln = lines.get(potm, {})
        bits = []
        if ln.get("balls") or ln.get("runs"):
            bits.append(f"{ln['runs']} off {ln['balls']}")
        if ln.get("bowled"):
            bits.append(f"{ln['wickets']}/{ln['conceded']}")
        out.append(f"Player of the match: {names.get(potm)}" + (f" ({', '.join(bits)})" if bits else "") + ".")
    return out


# ---------------------------------------------------------------------------
# Monte Carlo
# ---------------------------------------------------------------------------

def _batch_worker(args):
    model, rules, teams, seed, start, count, tw, td = args
    return start, run_batch(model, rules, teams, seed, start, count, tw, td)


def monte_carlo(ctx: dict, simulations: int, seed: int, progress=None) -> dict:
    """Run ``simulations`` matches in parallel batches and aggregate the actual outcomes."""
    rules, model, teams, cond, meta = ctx["rules"], ctx["model"], ctx["teams"], ctx["conditions"], ctx["meta"]
    limit = MAX_SIMULATIONS[rules.family]
    n = max(MIN_SIMULATIONS, min(int(simulations), limit))
    batch = 50 if rules.family != "Test" else 10
    jobs = [(model, rules, teams, seed, s, min(batch, n - s), cond.get("toss_winner", "random"), cond.get("toss_decision", "auto"))
            for s in range(0, n, batch)]
    # Batches run sequentially in this background thread. A process pool was
    # measured ~6x slower here (spawn start-up plus re-warming each worker's
    # probability cache), and results are identical either way because every
    # simulation is seeded independently of batching.
    results: Dict[int, List[dict]] = {}
    done = 0
    started = time.time()
    for j in jobs:
        start, out = _batch_worker(j)
        results[start] = out
        done += len(out)
        if progress:
            progress(done, n)
    summaries = [s for k in sorted(results) for s in results[k]]
    names = {pid: m.get("name", pid) for pid, m in meta.items()}
    agg = aggregate_monte_carlo(summaries, teams, rules, names)
    agg.update({"seed": seed, "requested": int(simulations), "capped_at": limit, "elapsed_seconds": round(time.time() - started, 2),
                "teams": {k: {"name": t.name, "team_id": t.team_id} for k, t in teams.items()}})
    return agg


# ---------------------------------------------------------------------------
# Background jobs
# ---------------------------------------------------------------------------

_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="cpi-sim")
_JOBS: Dict[str, dict] = {}
_JOBS_LOCK = threading.Lock()
MAX_JOBS = 50


def submit_job(kind: str, fn, *args) -> dict:
    job_id = uuid.uuid4().hex[:12]
    job = {"id": job_id, "kind": kind, "status": "queued", "progress": 0.0, "message": "Queued",
           "created_at": time.time(), "result": None, "error": None, "report": None}
    with _JOBS_LOCK:
        _JOBS[job_id] = job
        if len(_JOBS) > MAX_JOBS:
            for old in sorted(_JOBS.values(), key=lambda j: j["created_at"])[: len(_JOBS) - MAX_JOBS]:
                if old["status"] in ("done", "error"):
                    _JOBS.pop(old["id"], None)

    def update(**kw):
        with _JOBS_LOCK:
            job.update(kw)

    def runner():
        update(status="running", message="Preparing simulation")
        try:
            result = fn(update, *args)
            update(status="done", progress=1.0, message="Complete", result=result, finished_at=time.time())
        except SetupError as exc:
            update(status="error", error=str(exc), report=exc.report, finished_at=time.time())
        except Exception as exc:  # pragma: no cover - surfaced to the client
            logger.exception("Simulation job %s failed", job_id)
            update(status="error", error=str(exc) or exc.__class__.__name__, finished_at=time.time())

    _EXECUTOR.submit(runner)
    return public_job(job)


def get_job(job_id: str) -> Optional[dict]:
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        return public_job(job) if job else None


def public_job(job: dict) -> dict:
    return {k: job.get(k) for k in ("id", "kind", "status", "progress", "message", "result", "error", "report")}


def run_single_job(update, payload: dict, seed: int):
    from app.db.session import SessionLocal
    if not cal.calibration_available(rules_for(payload.get("format", "T20")).family):
        update(message="Calibrating format baselines from CPI deliveries (first run only, ~1 minute)")
    db = SessionLocal()
    try:
        update(message="Loading player histories", progress=0.1)
        ctx = build_context(db, payload)
    finally:
        db.close()
    update(message="Simulating ball by ball and win probability", progress=0.4, report=ctx["report"])
    def progress(frac):
        update(progress=0.4 + 0.58 * frac, message=f"Win probability: re-simulating from each over ({int(frac * 100)}%)")
    out = detailed_match(ctx, seed, payload.get("wp_simulations"), progress)
    out["validation"] = ctx["report"]
    return out


def run_monte_carlo_job(update, payload: dict, simulations: int, seed: int):
    from app.db.session import SessionLocal
    if not cal.calibration_available(rules_for(payload.get("format", "T20")).family):
        update(message="Calibrating format baselines from CPI deliveries (first run only, ~1 minute)")
    db = SessionLocal()
    try:
        update(message="Loading player histories", progress=0.02)
        ctx = build_context(db, payload)
    finally:
        db.close()
    update(message=f"Simulating {simulations} matches", progress=0.05, report=ctx["report"])

    def progress(done, total):
        update(progress=0.05 + 0.93 * done / total, message=f"Simulated {done} of {total} matches")
    out = monte_carlo(ctx, simulations, seed, progress)
    out["validation"] = ctx["report"]
    return out
