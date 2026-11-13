"""Match simulator and screenshot-assisted tactical analysis APIs.

Every simulation endpoint uses the calibrated ball-by-ball engine in
``app.ml.match_simulator``. Full matches and Monte Carlo runs execute as
background jobs (``/simulator/jobs/{id}``) so requests never block.
"""
from __future__ import annotations

import asyncio
import difflib
import math
import random
import re
import statistics
import subprocess
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select, func, case
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.ml import sim_calibration as cal
from app.ml.match_simulator import (
    CONDITION_BINS, InningsResult, MAX_SIMULATIONS, SimModel, TeamSetup, can_cover, play_innings, rules_for,
)
from app.models.models import Player, PlayerAlias, PlayerNameAlias, Team, TeamAlias, Venue, Tournament, Delivery, MatchInnings, Match
from app.services import match_simulation as svc

router = APIRouter()
OCR_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "ocr_match_screenshot.swift"
WP_ARTIFACTS_DIR = Path(__file__).resolve().parents[3] / "artifacts" / "win_probability"


@router.get("/simulator/options")
def simulator_options(db: Session = Depends(get_db)):
    venues = db.execute(select(Venue.id, Venue.canonical_name, Venue.city, Venue.country).order_by(Venue.canonical_name)).all()
    competitions = db.execute(select(Tournament.id, Tournament.name, Tournament.format).order_by(Tournament.name)).all()
    return {"venues": [{"id": x.id, "name": x.canonical_name, "city": x.city, "country": x.country} for x in venues],
            "competitions": [{"id": x.id, "name": x.name, "format": x.format} for x in competitions]}


# ---------------------------------------------------------------------------
# Full-match simulation (Playing XIs -> conditions -> validate -> run)
# ---------------------------------------------------------------------------

class XiPlayer(BaseModel):
    id: Optional[str] = None
    name: Optional[str] = None
    input_name: Optional[str] = None
    is_captain: bool = False
    is_wicketkeeper: bool = False


class TeamXi(BaseModel):
    name: str = Field("", max_length=80)
    team_id: Optional[str] = None
    players: List[XiPlayer] = Field(default_factory=list, max_length=15)


class MatchConditions(BaseModel):
    venue_id: Optional[str] = None
    pitch: str = "balanced"
    weather: str = "clear"
    toss_winner: str = "random"
    toss_decision: str = "auto"
    super_over: bool = True


class MatchRequest(BaseModel):
    format: str = "T20"
    overs: Optional[int] = Field(None, ge=1, le=50)
    gender: Optional[str] = None
    teams: Dict[str, TeamXi]
    conditions: MatchConditions = Field(default_factory=MatchConditions)
    seed: Optional[int] = Field(None, ge=0, le=2 ** 31 - 1)
    simulations: int = Field(500, ge=svc.MIN_SIMULATIONS, le=max(MAX_SIMULATIONS.values()))
    # Re-simulations per win-probability point (single-match runs); 5,000 for accuracy checks.
    wp_simulations: Optional[int] = Field(None, ge=100, le=svc.WP_MAX_SIMS)

    def payload(self) -> dict:
        if set(self.teams) != {"A", "B"}:
            raise HTTPException(422, "Provide exactly two teams keyed 'A' and 'B'")
        data = self.model_dump()
        data["teams"] = {k: v for k, v in data["teams"].items()}
        return data


def _seed(value: Optional[int]) -> int:
    return value if value is not None else random.SystemRandom().randint(1, 2 ** 31 - 1)


@router.get("/simulator/match/options")
def match_options(format: str = Query("T20"), db: Session = Depends(get_db)):
    try:
        rules = rules_for(format)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    venues = cal.venues_for_family(db, rules.family)
    return {
        "formats": [{"value": f, "family": cal.FORMAT_TO_FAMILY[f], "overs": cal.DEFAULT_OVERS[cal.FORMAT_TO_FAMILY[f]]}
                    for f in ("T20", "T20I", "ODI", "ODM", "Test")],
        "pitches": list(svc.PITCHES), "weather": list(svc.WEATHER),
        "venues": [{"id": v["id"], "name": v["canonical_name"], "city": v["city"], "country": v["country"], "matches": v["matches"]} for v in venues],
        "limits": {"max_simulations": MAX_SIMULATIONS[rules.family], "min_simulations": svc.MIN_SIMULATIONS},
        "calibrated": cal.calibration_available(rules.family),
    }


@router.post("/simulator/match/validate")
def validate_match(req: MatchRequest, db: Session = Depends(get_db)):
    """Validate both XIs and conditions against CPI data; returns errors, warnings and team summaries."""
    payload = req.payload()
    shape = svc.validate_payload_shape(payload)
    if shape:
        return {"valid": False, "errors": shape, "warnings": [], "teams": {}}
    ctx = svc.build_context(db, payload, require_valid=False)
    return ctx["report"]


@router.post("/simulator/match/run")
def run_match(req: MatchRequest):
    """Start one detailed ball-by-ball match simulation as a background job."""
    payload = req.payload()
    errors = svc.validate_payload_shape(payload)
    if errors:
        raise HTTPException(422, {"errors": errors})
    return svc.submit_job("match", svc.run_single_job, payload, _seed(req.seed))


@router.post("/simulator/match/monte-carlo")
def run_monte_carlo(req: MatchRequest):
    """Start a Monte Carlo batch (capped per format) as a background job."""
    payload = req.payload()
    errors = svc.validate_payload_shape(payload)
    if errors:
        raise HTTPException(422, {"errors": errors})
    return svc.submit_job("monte_carlo", svc.run_monte_carlo_job, payload, req.simulations, _seed(req.seed))


@router.get("/simulator/jobs/{job_id}")
def simulation_job(job_id: str):
    job = svc.get_job(job_id)
    if not job:
        raise HTTPException(404, "Simulation job not found (jobs are kept in memory and expire on restart)")
    return job


# ---------------------------------------------------------------------------
# Innings tools: project an innings from a live state, compare orders and bowlers
# ---------------------------------------------------------------------------

class State(BaseModel):
    format: str = "T20"
    team1_name: Optional[str] = None
    team2_name: Optional[str] = None
    competition_id: Optional[str] = None
    venue_id: Optional[str] = None
    score: int = Field(0, ge=0)
    wickets: int = Field(0, ge=0, le=10)
    legal_balls: int = Field(0, ge=0, le=300)
    target_runs: Optional[int] = Field(None, ge=1)
    target_overs: Optional[int] = Field(None, ge=1, le=50)
    required_run_rate: Optional[float] = Field(None, ge=0)
    innings_number: Optional[int] = Field(None, ge=1, le=2)
    batter_id: Optional[str] = None
    non_striker_id: Optional[str] = None
    bowler_id: Optional[str] = None
    bowling_category: Optional[str] = None
    bowling_subtype: Optional[str] = None
    batter_hand: Optional[str] = None
    batting_order: list[str] = Field(default_factory=list)
    bowlers: list[str] = Field(default_factory=list)
    overs_bowled: dict[str, int] = Field(default_factory=dict)
    simulations: int = Field(1000, ge=100, le=10000)
    seed: int = 7

    def validate_format(self):
        if self.format not in {"T20", "T20I", "ODI", "ODM"}:
            raise ValueError("Innings projection supports T20 and ODI limited-overs innings; use the full-match simulator for Tests")
        limit = 120 if self.format in {"T20", "T20I"} else 300
        if self.legal_balls > limit or (self.target_overs is not None and self.target_overs * 6 < self.legal_balls):
            raise ValueError("Legal balls bowled and innings length must fit the selected format")
        if self.target_runs is not None and self.score >= self.target_runs:
            raise ValueError("The target has already been reached; the match is complete")


class SimulationRequest(BaseModel):
    state: State


class BattingOrderRequest(BaseModel):
    state: State
    batting_orders: list[list[str]] = Field(..., min_length=2, max_length=8)


class BowlingOptionsRequest(BaseModel):
    state: State
    options: list[str] = Field(..., min_length=1, max_length=20)
    overs_bowled: dict[str, int] = Field(default_factory=dict)
    over_number: Optional[int] = Field(None, ge=1, le=50)
    scenarios: int = Field(500, ge=100, le=3000)


def _innings_context(db: Session, state: dict, extra_ids=()) -> dict:
    """Prepare the engine for projecting one innings from a live state."""
    try:
        rules = rules_for(state["format"], overs=state.get("target_overs"))
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    order = [x for x in state.get("batting_order", []) if x]
    bowlers = list(dict.fromkeys(x for x in state.get("bowlers", []) if x))
    for pid in (state.get("non_striker_id"), state.get("batter_id")):
        if pid and pid not in order:
            order.insert(0, pid)
    if len(set(order)) != len(order):
        raise HTTPException(422, "Each batting order must contain unique, selected player IDs")
    if len(order) < 2:
        raise HTTPException(422, "Select both current batters or provide at least two available batters")
    if not bowlers:
        raise HTTPException(422, "Add at least one opponent bowler; a full innings requires enough options to respect over limits")
    ids = set(order) | set(bowlers) | {p for p in extra_ids if p}
    if state.get("bowler_id"):
        ids.add(state["bowler_id"])
    family = rules.family
    gender = cal.infer_gender(db, ids)
    calibration = cal.load_format_calibration(db, family)
    profiles = cal.load_player_profiles(db, family, gender, ids)
    meta = cal.load_player_meta(db, ids)
    venue = cal.load_venue_profile(db, family, gender, state.get("venue_id")) if state.get("venue_id") else None
    positions = {p: i + 1 + int(state.get("wickets", 0)) for i, p in enumerate(order)}
    model = SimModel(calibration, family, gender, profiles, meta, venue=venue, positions=positions)
    return {"rules": rules, "model": model, "order": order, "bowlers": bowlers, "meta": meta,
            "batting": TeamSetup("A", state.get("team1_name") or "Batting team", order),
            "bowling": TeamSetup("B", state.get("team2_name") or "Bowling team", bowlers, bowling_options=bowlers)}


def _start(state: dict, order: List[str]) -> dict:
    striker = state.get("batter_id") or order[0]
    non_striker = state.get("non_striker_id") or next(p for p in order if p != striker)
    nxt = max(order.index(striker), order.index(non_striker)) + 1
    return {"score": state.get("score", 0), "wickets": state.get("wickets", 0), "legal_balls": state.get("legal_balls", 0),
            "striker": striker, "non_striker": non_striker, "next_index": nxt,
            "overs_bowled": state.get("overs_bowled") or {}, "bowler": state.get("bowler_id") if state.get("legal_balls", 0) % 6 else None}


def _project(ctx: dict, state: dict, simulations: int, seed: int, order: Optional[List[str]] = None) -> dict:
    rules, model = ctx["rules"], ctx["model"]
    order = order or ctx["order"]
    cap = rules.overs * 6
    legal = int(state.get("legal_balls", 0))
    remaining = math.ceil(max(0, cap - legal) / 6) - (1 if legal % 6 else 0)
    quotas = {b: max(0, rules.max_bowler_overs - int(state.get("overs_bowled", {}).get(b, 0))) for b in ctx["bowlers"]}
    current = state.get("bowler_id") if legal % 6 else None
    if not can_cover(quotas, current, remaining):
        needed = math.ceil(max(0, cap - legal) / 6 / rules.max_bowler_overs)
        raise HTTPException(422, f"Need at least {needed} distinct bowlers with enough remaining overs to cover the innings under the {rules.max_bowler_overs}-over limit")
    if legal % 6 and not state.get("bowler_id"):
        raise HTTPException(422, "Select the current bowler to resume mid-over")
    chasing = state.get("target_runs") is not None
    base_inn = 2 if chasing else int(state.get("innings_number") or 1)
    start = _start(state, order)
    scores, wickets_dist, phase_runs = [], defaultdict(int), defaultdict(float)
    reached = 0
    for i in range(simulations):
        rng = random.Random(f"{seed}:{i}")
        inn = InningsResult(base_inn, "A", "B", target=state.get("target_runs"))
        play_innings(model, rules, ctx["batting"], ctx["bowling"], inn, rng, base_inn=base_inn, later=base_inn >= 2,
                     detailed=True, order=order, bowlers=ctx["bowlers"], start=dict(start),
                     zk=int(rng.random() * CONDITION_BINS))  # match conditions unknown: sample the prior
        scores.append(inn.runs)
        wickets_dist[inn.wickets] += 1
        reached += int(chasing and inn.runs >= state["target_runs"])
        for d in inn.deliveries:
            phase_runs[cal.phase_of(rules.family, d["over_index"])] += d["total_runs"]
    ordered = sorted(scores)
    return {
        "expected_final_score": round(sum(scores) / simulations, 2), "median_projected_score": ordered[simulations // 2],
        "distribution": scores, "score_histogram": _histogram(scores),
        "target_reach_probability": round(reached / simulations, 4) if chasing else None,
        "wicket_distribution": {str(k): round(v / simulations, 4) for k, v in sorted(wickets_dist.items())},
        "phase_projection": {p: {"expected_runs": round(v / simulations, 2)} for p, v in phase_runs.items()},
        "p10_p90": [ordered[int(0.1 * (simulations - 1))], ordered[int(0.9 * (simulations - 1))]],
    }


def _histogram(values: list[int]) -> list[dict]:
    bins = defaultdict(int)
    for n in values:
        bins[(n // 10) * 10] += 1
    return [{"range_start": k, "count": v} for k, v in sorted(bins.items())]


@router.post("/simulator/simulate")
def simulate(req: SimulationRequest, db: Session = Depends(get_db)):
    try:
        req.state.validate_format()
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    state = req.state.model_dump()
    ctx = _innings_context(db, state)
    result = _project(ctx, state, req.state.simulations, req.state.seed)
    meta = ctx["model"].calibration_meta
    result.update({"model_version": meta.get("version"), "model_trained": True, "simulations": req.state.simulations,
                   "sample_size": meta.get("deliveries", 0), "seed": req.state.seed,
                   "uncertainty_note": "Ball-by-ball Monte Carlo from smoothed CPI player, phase and match-state rates; "
                                       "ranges reflect sampled outcomes, and players with little history fall back to position priors."})
    return result


@router.post("/simulator/batting-order")
def compare_batting_orders(req: BattingOrderRequest, db: Session = Depends(get_db)):
    try:
        req.state.validate_format()
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    state = req.state.model_dump()
    for order in req.batting_orders:
        if not order or len(set(order)) != len(order):
            raise HTTPException(422, "Each batting order must contain unique, selected player IDs")
    all_ids = {p for o in req.batting_orders for p in o}
    ctx = _innings_context(db, {**state, "batting_order": req.batting_orders[0]}, extra_ids=all_ids)
    results = []
    for order in req.batting_orders:
        for i, p in enumerate(order):
            ctx["model"].ensure_player(p, i + 1 + int(state.get("wickets", 0)))
        r = _project(ctx, {**state, "batting_order": order}, req.state.simulations, req.state.seed, order=order)
        results.append({"order": order, **{k: r[k] for k in ("expected_final_score", "median_projected_score", "target_reach_probability",
                                                              "score_histogram", "phase_projection")}})
    baseline = results[0]["expected_final_score"]
    for result in results:
        result["difference_from_original"] = round(result["expected_final_score"] - baseline, 2)
    return {"model_version": ctx["model"].calibration_meta.get("version"), "original_order": results[0], "comparisons": results[1:]}


@router.post("/simulator/bowling-options")
def compare_bowling_options(req: BowlingOptionsRequest, db: Session = Depends(get_db)):
    try:
        req.state.validate_format()
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    state = req.state.model_dump()
    state["bowlers"] = list(dict.fromkeys(list(req.options) + state.get("bowlers", [])))
    ctx = _innings_context(db, state)
    rules, model = ctx["rules"], ctx["model"]
    max_overs = rules.max_bowler_overs
    batter_ids = [x for x in (state.get("batter_id"), state.get("non_striker_id")) if x]
    compatible_formats = list(cal.FAMILY_FORMATS[rules.family])
    evidence = {}
    if batter_ids:
        stats = db.execute(select(Delivery.bowler_id, func.count(Delivery.id), func.sum(Delivery.total_runs), func.sum(case((Delivery.is_legal_ball.is_(True), 1), else_=0)), func.count(func.distinct(MatchInnings.match_id)))
            .join(MatchInnings, Delivery.innings_id == MatchInnings.id).join(Match, Match.id == MatchInnings.match_id)
            .where(Delivery.batter_id.in_(batter_ids), Delivery.bowler_id.in_(req.options), Match.match_format.in_(compatible_formats))
            .group_by(Delivery.bowler_id)).all()
        for bowler_id, deliveries, runs, legal_balls, matches in stats:
            evidence[bowler_id] = {"deliveries": int(deliveries), "legal_balls": int(legal_balls or 0), "runs": int(runs or 0), "matches": int(matches),
                                   "economy": round(float(runs or 0) * 6 / int(legal_balls), 2) if legal_balls else None}
    overs_bowled = {**state.get("overs_bowled", {}), **req.overs_bowled}
    legal = int(state.get("legal_balls", 0))
    over_end = (legal // 6 + 1) * 6
    chasing = state.get("target_runs") is not None
    base_inn = 2 if chasing else int(state.get("innings_number") or 1)
    start = _start({**state, "legal_balls": legal - legal % 6}, ctx["order"])
    options = []
    for bowler in req.options:
        used = int(overs_bowled.get(bowler, 0))
        if used >= max_overs or (bowler == state.get("bowler_id") and legal % 6 == 0):
            continue
        runs_total = wickets_total = 0
        for scenario in range(req.scenarios):
            rng = random.Random(f"{state.get('seed', 7)}:{bowler}:{scenario}")
            inn = InningsResult(base_inn, "A", "B", target=state.get("target_runs"))
            play_innings(model, rules, ctx["batting"], ctx["bowling"], inn, rng, base_inn=base_inn, later=base_inn >= 2,
                         detailed=False, zk=int(rng.random() * CONDITION_BINS), order=ctx["order"], bowlers=[bowler], forced_bowler=bowler,
                         max_balls=over_end if legal % 6 == 0 else over_end, start=dict(start, legal_balls=legal - legal % 6, bowler=None))
            runs_total += inn.runs - int(state.get("score", 0))
            wickets_total += inn.wickets - int(state.get("wickets", 0))
        expected_runs = runs_total / req.scenarios
        wicket_probability = wickets_total / req.scenarios
        options.append({"bowler_id": bowler, "name": ctx["meta"].get(bowler, {}).get("name"), "overs_already_bowled": used,
                        "expected_runs_conceded": round(expected_runs, 2), "wicket_probability": round(wicket_probability, 4),
                        "estimated_impact_score": round(100 * (0.7 * min(1.0, wicket_probability) + 0.3 * max(0, 1 - expected_runs / 12)), 1),
                        "sample_size": req.scenarios, "historical_matchup_evidence": evidence.get(bowler)})
    options.sort(key=lambda x: (x["expected_runs_conceded"], -x["wicket_probability"]))
    if not options:
        raise HTTPException(422, "No eligible bowler remains under the format over limit")
    return {"model_version": model.calibration_meta.get("version"), "max_overs_per_bowler": max_overs,
            "ranking_explanation": "Ranked by expected runs conceded in the next over, then expected wickets, from ball-by-ball simulation of the current batters against each bowler. Estimated impact combines both; it is not a trained win-probability delta.",
            "options": options}


@router.post("/simulator/win-probability")
def simulator_win_probability(req: SimulationRequest):
    """Return a win-probability estimate for the given match state using the trained WP models.

    Only T20/ODI formats are supported (the simulator does not cover Test matches).
    Returns ``{"available": false, ...}`` when no model file exists for the format family.
    """
    import joblib
    import numpy as np
    from app.ml.win_probability import match_state_features, FORMAT_FAMILY, MODEL_VERSION_PREFIX, FEATURES, OUTCOMES as WP_OUTCOMES

    state = req.state
    family = FORMAT_FAMILY.get(state.format)
    if family not in {"T20", "ODI"}:
        return {"available": False, "reason": "Win probability model only supports T20 and ODI formats"}

    model_path = WP_ARTIFACTS_DIR / f"{family.lower()}.joblib"
    if not model_path.exists():
        return {"available": False, "reason": f"No trained model for this format ({family})"}

    try:
        artifact = joblib.load(str(model_path))
        pipeline = artifact["model"] if isinstance(artifact, dict) else artifact
        version = artifact.get("version", f"{MODEL_VERSION_PREFIX}-{family.lower()}") if isinstance(artifact, dict) else f"{MODEL_VERSION_PREFIX}-{family.lower()}"
    except Exception as exc:  # pragma: no cover
        return {"available": False, "reason": f"Could not load model: {exc}"}

    # Determine whether team1 is currently batting.
    if state.innings_number:
        innings_number = int(state.innings_number)
    elif state.target_runs is not None:
        innings_number = 2
    else:
        innings_number = 1
    team1_batting = (innings_number == 1)

    # In 2nd innings the team batting has accumulated score; prior runs come from innings 1.
    if innings_number == 2 and state.target_runs:
        opposition_prior_runs = max(0, int(state.target_runs) - 1)  # team1 runs in first innings
        batting_team_prior_runs = 0
    else:
        batting_team_prior_runs = 0
        opposition_prior_runs = 0

    feat_dict = match_state_features(
        family,
        match_format=state.format,
        gender="male",
        team1_batting=team1_batting,
        is_super_over=False,
        innings_number=innings_number,
        innings_runs=int(state.score),
        wickets_lost=int(state.wickets),
        legal_balls=int(state.legal_balls),
        batting_team_prior_runs=batting_team_prior_runs,
        opposition_prior_runs=opposition_prior_runs,
        target_runs=state.target_runs,
        target_overs=state.target_overs,
        recent_runs=0,
        recent_wickets=0,
    )

    feature_names = list(FEATURES[family])
    X = np.array([[np.nan if feat_dict.get(f) is None else feat_dict.get(f) for f in feature_names]], dtype=np.float32)

    try:
        proba = pipeline.predict_proba(X)[0]
    except Exception as exc:  # pragma: no cover
        return {"available": False, "reason": f"Model prediction failed: {exc}"}

    # Outputs are ordered by class label: 0=team1_win, 1=team2_win, 2=draw_or_tie
    team1_win = float(proba[0]) if len(proba) > 0 else 0.0
    team2_win = float(proba[1]) if len(proba) > 1 else 0.0
    draw_or_tie = float(proba[2]) if len(proba) > 2 else 0.0

    return {
        "available": True,
        "team1_win": round(team1_win, 4),
        "team2_win": round(team2_win, 4),
        "draw_or_tie": round(draw_or_tie, 4),
        "model_version": version,
        "team1_name": state.team1_name or ("Batting Team" if team1_batting else "Chasing Team"),
        "team2_name": state.team2_name or ("Bowling Team" if team1_batting else "Defending Team"),
    }


def _ocr(path: str) -> str:
    try:
        cache = Path("/private/tmp/cpi-swift-cache")
        cache.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(["swift", "-module-cache-path", str(cache), str(OCR_SCRIPT), path], capture_output=True, text=True, timeout=90)
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        raise HTTPException(503, "Screenshot OCR requires macOS Vision (Swift). Enter the match state manually on this server.") from exc
    if result.returncode != 0: raise HTTPException(422, "Could not read text from this screenshot")
    return result.stdout.strip()


def _candidate_names(text: str, db: Session, model):
    folded = re.sub(r"[^a-z0-9 ]", " ", text.casefold())
    rows = db.execute(select(model.id, model.canonical_name)).all()
    found = []
    for identity, name in rows:
        n = re.sub(r"[^a-z0-9 ]", " ", name.casefold()).strip()
        if n and len(n) >= 4 and re.search(rf"\b{re.escape(n)}\b", folded): found.append({"id": identity, "name": name, "confidence": "text match"})
    if model is Team:
        aliases = db.execute(select(TeamAlias.team_id, TeamAlias.source_name)).all()
    else:
        aliases = db.execute(select(PlayerNameAlias.player_id, PlayerNameAlias.alias)).all()
        aliases += db.execute(select(PlayerAlias.player_id, PlayerAlias.source_name)).all()
    name_map = {identity: name for identity, name in rows}
    candidates = []
    for identity, name in aliases:
        n = re.sub(r"[^a-z0-9 ]", " ", name.casefold()).strip()
        if not n or len(n) < 4: continue
        candidates.append((identity, name, n))
        if re.search(rf"\b{re.escape(n)}\b", folded) and not any(x["id"] == identity for x in found):
            found.append({"id": identity, "name": name_map.get(identity, name), "matched_alias": name, "confidence": "alias text match"})
    if not found:
        # OCR often confuses a single character. Return only close name candidates and require confirmation.
        lines = [re.sub(r"[^a-z0-9 ]", " ", line.casefold()).strip() for line in text.splitlines()]
        for line in lines:
            if len(line) < 5 or re.search(r"\d", line) or len(line.split()) > 5: continue
            best = []
            for identity, alias, normalized in candidates:
                if abs(len(normalized) - len(line)) > max(4, int(len(normalized) * .25)): continue
                ratio = difflib.SequenceMatcher(None, line, normalized).ratio()
                if ratio >= .90: best.append((ratio, identity, alias))
            for ratio, identity, alias in sorted(best, reverse=True)[:3]:
                if not any(x["id"] == identity for x in found):
                    found.append({"id": identity, "name": name_map.get(identity, alias), "matched_alias": alias, "confidence": "fuzzy OCR candidate; confirm"})
    return found[:30]


def parse_scoreboard_text(text: str) -> dict:
    score = re.search(r"\b(\d{1,3})\s*/\s*(\d{1,2})\b", text)
    overs = re.search(r"\b(\d{1,3})\.(\d)\b", text)
    target = re.search(r"(?:target|to win|need)\s*[:\-]?\s*(\d{1,3})", text, re.I)
    fmt = "T20I" if re.search(r"\bT20I\b", text, re.I) else "T20" if re.search(r"\bT20\b|20 overs", text, re.I) else "ODI" if re.search(r"\bODI\b|50 overs", text, re.I) else None
    rr = re.search(r"(?:required run rate|req(?:uired)?\.?\s*rr|rrr)\s*[:=]?\s*(\d+(?:\.\d+)?)", text, re.I)
    innings = re.search(r"\b([12])(?:st|nd)?\s+innings\b", text, re.I)
    return {"format": fmt, "score": int(score.group(1)) if score else None,
            "wickets": int(score.group(2)) if score else None,
            "overs_completed": int(overs.group(1)) if overs else None,
            "balls_in_over": int(overs.group(2)) if overs else None,
            "legal_balls": int(overs.group(1)) * 6 + int(overs.group(2)) if overs else None,
            "target_runs": int(target.group(1)) if target else None,
            "required_run_rate": float(rr.group(1)) if rr else None,
            "innings_number": int(innings.group(1)) if innings else None,
            "raw_text": text,
            "uncertain_fields": [field for field in ("format", "score", "wickets", "overs_completed") if (fmt if field == "format" else score if field in {"score", "wickets"} else overs) is None]}


@router.post("/simulator/analyse-live-match")
async def analyse_live_match(file: UploadFile = File(...), db: Session = Depends(get_db)):
    name = (file.filename or "").casefold()
    if Path(name).suffix not in {".png", ".jpg", ".jpeg"}: raise HTTPException(415, "Upload a PNG, JPG or JPEG screenshot")
    content = await file.read()
    if not content or len(content) > 8 * 1024 * 1024: raise HTTPException(413, "Screenshot must be under 8 MB")
    suffix = Path(name).suffix
    with tempfile.NamedTemporaryFile(suffix=suffix) as tmp:
        tmp.write(content); tmp.flush()
        text = await asyncio.to_thread(_ocr, tmp.name)
    extracted = parse_scoreboard_text(text)
    extracted["team_candidates"] = _candidate_names(text, db, Team)
    extracted["player_candidates"] = _candidate_names(text, db, Player)
    extracted["available_bowling_options"] = extracted["player_candidates"]
    extracted["can_recommend"] = bool(extracted["format"] and extracted["score"] is not None and extracted["wickets"] is not None and extracted["legal_balls"] is not None)
    return {"extracted": extracted, "message": "Review and correct extracted fields before running the simulation. Names are candidates, not confirmed identities."}
