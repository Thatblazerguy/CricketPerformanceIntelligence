"""Auction Intelligence analytics API (mounted under the existing /auction prefix): data coverage, valuation, franchise strategy,
purse optimisation, auction-room simulation, history and backtesting.

The original scenario/upload endpoints in ``auction.py`` remain unchanged and
feed user scenarios into these services.
"""
from __future__ import annotations

import math
from decimal import Decimal
import statistics
from collections import Counter, defaultdict
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.auction import market as mk, optimizer as op
from app.ml import auction_price as M
from app.auction.simulator import STRATEGIES, AuctionRoom
from app.db.session import SessionLocal, get_db
from app.models.models import (
    AuctionBacktestPrediction, AuctionFranchiseSeason, AuctionHistoryImport, AuctionLot, AuctionModelRun,
    AuctionScenario, AuctionSeason, AuctionSession, AuctionTeam, AuctionEvent, AuctionBid, AuctionPurchase,
)

router = APIRouter(prefix="/auction", tags=["Auction Intelligence"])

# ----------------------------------------------------------------- helpers

_CTX: Dict[str, mk.Context] = {}


def _ctx(db: Session, key: str) -> mk.Context:
    if key not in _CTX:
        try:
            _CTX[key] = mk.build_context(db, key)
        except ValueError as exc:
            raise HTTPException(404, str(exc))
    return _CTX[key]


def _valuation(db: Session, key: str):
    ctx = _ctx(db, key)
    return ctx, mk.value_pool(db, ctx)


def _clean(v):
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    if isinstance(v, dict):
        return {k: _clean(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_clean(x) for x in v]
    return v


def _pkey(p):
    return p.get("player_id") or "name:" + p["name"]


def _player_row(p: dict) -> dict:
    f = p.get("features") or {}
    return {
        "key": _pkey(p), "player_id": p.get("player_id"), "name": p["name"], "role": p.get("role"),
        "bowling_kind": p.get("bowling_kind"), "overseas": p.get("overseas"), "capped": p.get("capped"),
        "base_lakh": p.get("base_lakh"), "set_code": p.get("set_code"), "lot_number": p.get("lot_number"),
        "identity_status": p.get("identity_status"),
        "predicted": {"p10": p.get("p10"), "p50": p.get("p50"), "p90": p.get("p90")},
        "market_value_lakh": p.get("market_value_lakh"), "market_premium": p.get("market_premium"),
        "sale_probability": p.get("sale_probability"), "bidding_war_probability": p.get("bidding_war_probability"),
        "demand_level": p.get("demand_level"), "quality": p.get("quality"), "bat_quality": p.get("bat_quality"),
        "bowl_quality": p.get("bowl_quality"), "scarcity": p.get("scarcity"), "recent_form": p.get("recent_form"),
        "ipl_suitability": p.get("ipl_suitability"), "confidence": p.get("confidence"), "tags": p.get("tags"),
        "evidence_balls": p.get("evidence_balls"), "missing_information": p.get("missing_information"),
        "ipl_matches": f.get("ipl_matches_career"), "t20_career_years": f.get("t20_career_years"),
        "actual": ({"status": p.get("actual_status"), "franchise": p.get("actual_franchise"),
                    "price_lakh": p.get("actual_price_lakh"), "verification": p.get("verification")}
                   if p.get("actual_status") else None),
    }


def _filter_players(players, role=None, overseas=None, search=None, min_base=None, max_base=None,
                    min_pred=None, max_pred=None, min_ipl=None, max_ipl=None, tag=None, status=None):
    out = []
    for p in players:
        if role and p.get("role") != role:
            continue
        if overseas is not None and p.get("overseas") is not overseas:
            continue
        if search and search.casefold() not in p["name"].casefold():
            continue
        b = p.get("base_lakh")
        if min_base is not None and (b is None or b < min_base):
            continue
        if max_base is not None and (b is None or b > max_base):
            continue
        pr = p.get("p50")
        if min_pred is not None and (pr is None or pr < min_pred):
            continue
        if max_pred is not None and (pr is None or pr > max_pred):
            continue
        ipl = (p.get("features") or {}).get("ipl_matches_career")
        if min_ipl is not None and (ipl or 0) < min_ipl:
            continue
        if max_ipl is not None and (ipl or 0) > max_ipl:
            continue
        if tag and tag not in (p.get("tags") or []):
            continue
        if status and p.get("actual_status") != status:
            continue
        out.append(p)
    return out


class PlayerFilters(BaseModel):
    role: Optional[str] = None
    overseas: Optional[bool] = None
    search: Optional[str] = None
    min_base: Optional[float] = None
    max_base: Optional[float] = None
    min_pred: Optional[float] = None
    max_pred: Optional[float] = None
    min_ipl: Optional[int] = None
    max_ipl: Optional[int] = None
    tag: Optional[str] = None
    status: Optional[str] = None


def _filters(role: Optional[str] = None, overseas: Optional[bool] = None, search: Optional[str] = None,
             min_base: Optional[float] = None, max_base: Optional[float] = None, min_pred: Optional[float] = None,
             max_pred: Optional[float] = None, min_ipl: Optional[int] = None, max_ipl: Optional[int] = None,
             tag: Optional[str] = None, status: Optional[str] = None) -> PlayerFilters:
    return PlayerFilters(role=role, overseas=overseas, search=search, min_base=min_base, max_base=max_base,
                         min_pred=min_pred, max_pred=max_pred, min_ipl=min_ipl, max_ipl=max_ipl, tag=tag, status=status)


# ----------------------------------------------------------------- data

@router.get("/coverage")
def coverage(db: Session = Depends(get_db)):
    rows = db.execute(text("""
        SELECT season,
               COUNT(*) FILTER (WHERE acquisition_type='auction') AS auction_records,
               COUNT(*) FILTER (WHERE status='SOLD') AS sold,
               COUNT(*) FILTER (WHERE status='UNSOLD') AS unsold,
               COUNT(*) FILTER (WHERE status='RETAINED') AS retained,
               COUNT(*) FILTER (WHERE status='SOLD' AND base_price_lakh IS NOT NULL) AS sold_with_base,
               COUNT(*) FILTER (WHERE verification='corroborated') AS corroborated,
               COUNT(*) FILTER (WHERE verification='conflict') AS conflicts,
               COUNT(*) FILTER (WHERE player_id IS NOT NULL) AS linked,
               COUNT(*) AS total,
               COUNT(DISTINCT franchise) AS franchises,
               COUNT(*) FILTER (WHERE set_code IS NOT NULL) AS with_set,
               COUNT(*) FILTER (WHERE is_rtm) AS rtm
        FROM auction_lots GROUP BY season ORDER BY season""")).mappings().all()
    seasons = {s.season: s for s in db.scalars(select(AuctionSeason)).all()}
    fs = defaultdict(Counter)
    for r in db.scalars(select(AuctionFranchiseSeason)).all():
        fs[r.season][r.purse_basis] += 1
    per_season = []
    for r in rows:
        s = seasons.get(r["season"])
        reported = (s.rule_sources or {}).get("pool_size_reported") if s else None
        gaps = []
        if not r["unsold"]:
            gaps.append("unsold players not recorded")
        if r["sold"] and r["sold_with_base"] < r["sold"] * 0.9:
            gaps.append("base prices missing for most sold players")
        if not fs[r["season"]] or fs[r["season"]].get("unknown", 0) == sum(fs[r["season"]].values()):
            gaps.append("pre-auction purse unknown")
        if s and not s.purse_lakh:
            gaps.append("season purse not recorded")
        if r["season"] == 2025:
            gaps.append("2 of 182 sales absent from the cited source table (MI and KKR totals are one short)")
        per_season.append({**dict(r), "auction_type": s.auction_type if s else None,
                           "auction_date": s.auction_date.isoformat() if s and s.auction_date else None,
                           "pool_size_reported": reported, "purse_basis": dict(fs[r["season"]]),
                           "price_verified_pct": round(100 * r["corroborated"] / r["total"], 1) if r["total"] else None,
                           "linked_pct": round(100 * r["linked"] / r["total"], 1) if r["total"] else None,
                           "gaps": gaps})
    totals = db.execute(text("""SELECT COUNT(*) total, COUNT(*) FILTER (WHERE status='SOLD') sold,
        COUNT(*) FILTER (WHERE status='UNSOLD') unsold, COUNT(*) FILTER (WHERE status='RETAINED') retained,
        COUNT(DISTINCT franchise) franchises, COUNT(DISTINCT season) seasons,
        COUNT(*) FILTER (WHERE verification='corroborated') corroborated,
        COUNT(*) FILTER (WHERE verification='conflict') conflicts,
        COUNT(*) FILTER (WHERE player_id IS NOT NULL) linked, MAX(built_at) built_at FROM auction_lots""")).mappings().one()
    sources = db.execute(text("""SELECT source_name, COUNT(*) n, MIN(auction_year) min_y, MAX(auction_year) max_y,
        MAX(imported_at) last_import, MAX(source_url) url FROM auction_history_records GROUP BY 1 ORDER BY 1""")).mappings().all()
    conflicts = db.scalars(select(AuctionLot).where(AuctionLot.verification == "conflict").order_by(AuctionLot.season)).all()
    identity = db.execute(text("SELECT identity_status, COUNT(*) FROM auction_lots GROUP BY 1")).all()
    return _clean({
        "totals": {**dict(totals), "built_at": totals["built_at"].isoformat() if totals["built_at"] else None,
                   "price_verified_pct": round(100 * totals["corroborated"] / totals["total"], 1) if totals["total"] else None},
        "per_season": per_season, "sources": [{**dict(s), "last_import": s["last_import"].isoformat() if s["last_import"] else None} for s in sources],
        "identity": {k: v for k, v in identity},
        "conflicts": [{"season": c.season, "player": c.player_name, "chosen_price_lakh": float(c.final_price_lakh) if c.final_price_lakh else None,
                       "note": c.conflict_note} for c in conflicts],
        "definitions": {
            "corroborated": "Two or more independent sources agree on the outcome and price (within 1%).",
            "single_source": "Only one source records this outcome; not independently verified.",
            "conflict": "Sources disagree; excluded from model training and evaluation.",
            "linked": "Auction name resolved to a unique CPI player (exact alias, or disambiguated by evidence).",
        },
        "not_available": ["Bid-by-bid sequences (no source records them)", "Unsold players before 2021 and for 2024–2026",
                          "Withdrawn / injury replacement signings as auction records",
                          "Player ages except for the 2022–2023 official lists"],
    })


@router.post("/rebuild")
def rebuild(db: Session = Depends(get_db)):
    from app.auction.ingest import run_full_ingest
    result = run_full_ingest(db)
    _CTX.clear()
    mk.invalidate_caches()
    return _clean(result)


@router.get("/seasons")
def seasons(db: Session = Depends(get_db)):
    out = []
    for s in db.scalars(select(AuctionSeason).order_by(AuctionSeason.season.desc())).all():
        rules = mk._rules_from_season(s)
        out.append({**rules.as_dict(), "auction_date": s.auction_date.isoformat() if s.auction_date else None,
                    "location": s.location, "max_retentions": s.max_retentions, "notes": s.notes})
    return out


@router.get("/contexts")
def contexts(db: Session = Depends(get_db)):
    return {"contexts": mk.available_contexts(db), "strategies": [{"key": k, **{x: v[x] for x in ("label", "summary")}}
                                                                  for k, v in STRATEGIES.items()]}


# ----------------------------------------------------------------- market & players

@router.get("/market")
def market_overview(context: str, f: PlayerFilters = Depends(_filters), db: Session = Depends(get_db)):
    ctx, val = _valuation(db, context)
    players = _filter_players(val["players"], **f.model_dump())
    priced = [p for p in players if p.get("p50")]
    roles = Counter(p.get("role") or "Unknown" for p in players)
    by_role = []
    for role in sorted(roles):
        grp = [p for p in priced if (p.get("role") or "Unknown") == role]
        by_role.append({"role": role, "players": roles[role],
                        "median_predicted_lakh": round(statistics.median([p["p50"] for p in grp]), 1) if grp else None,
                        "total_predicted_lakh": round(sum(p["p50"] for p in grp), 0),
                        "high_demand": sum(1 for p in grp if (p.get("bidding_war_probability") or 0) >= 0.3)})
    scarcity = Counter(p["scarcity"]["group"] for p in players if p.get("scarcity"))
    groups = []
    for g, n in scarcity.most_common():
        members = [p for p in players if p.get("scarcity") and p["scarcity"]["group"] == g]
        good = [p for p in members if (p.get("quality") or 0) >= 60]
        groups.append({"group": g, "players": n, "quality_60_plus": len(good),
                       "median_predicted_lakh": round(statistics.median([p["p50"] for p in members if p.get("p50")]), 1)
                       if any(p.get("p50") for p in members) else None})
    open_slots = sum(max(0, ctx.rules.max_squad - len(fr["squad"])) for fr in ctx.franchises.values())
    known_purse = [fr["purse_lakh"] for fr in ctx.franchises.values() if fr["purse_lakh"] is not None]
    under = sorted([p for p in priced if p.get("market_premium") and p.get("quality") is not None and p["quality"] >= 50],
                   key=lambda p: p["market_premium"])[:10]
    over = sorted([p for p in priced if p.get("market_premium") and p["market_premium"] >= 1.25],
                  key=lambda p: -p["market_premium"])[:10]
    return _clean({
        "context": {"key": ctx.key, "label": ctx.label, "as_of": ctx.as_of.isoformat(), "historical": ctx.historical,
                    "notes": ctx.notes, "rules": ctx.rules.as_dict()},
        "model": val["models"], "sale_probability_basis": val["sale_basis"],
        "records": len(players), "pool_total": len(val["players"]),
        "summary": {
            "players": len(players), "overseas": sum(1 for p in players if p.get("overseas")),
            "domestic": sum(1 for p in players if p.get("overseas") is False),
            "nationality_unknown": sum(1 for p in players if p.get("overseas") is None),
            "estimated_market_value_lakh": round(sum(p["p50"] for p in priced), 0),
            "open_squad_slots": open_slots, "purse_available_lakh": round(sum(known_purse), 0) if known_purse else None,
            "purse_known_franchises": len(known_purse), "franchises": len(ctx.franchises),
            "high_demand_players": sum(1 for p in priced if (p.get("bidding_war_probability") or 0) >= 0.3),
        },
        "by_role": by_role, "scarcity_groups": groups,
        "top_projected": [_player_row(p) for p in sorted(priced, key=lambda p: -p["p50"])[:12]],
        "bidding_wars": [_player_row(p) for p in sorted(priced, key=lambda p: -(p.get("bidding_war_probability") or 0))[:10]],
        "undervalued": [_player_row(p) for p in under],
        "overvalued": [_player_row(p) for p in over],
        "emerging": [_player_row(p) for p in sorted([p for p in priced if (p.get("features") or {}).get("ipl_matches_career", 0) <= 10
                                                       and p.get("quality") is not None], key=lambda p: -p["quality"])[:10]],
        "high_risk": [_player_row(p) for p in sorted([p for p in priced if p.get("confidence") == "low"],
                                                       key=lambda p: -p["p50"])[:10]],
        "scatter": [{"key": _pkey(p), "name": p["name"], "role": p.get("role"), "overseas": p.get("overseas"),
                     "quality": p.get("quality"), "p50": p["p50"], "base": p.get("base_lakh"),
                     "war": p.get("bidding_war_probability"), "scarcity": (p.get("scarcity") or {}).get("score"),
                     "actual": p.get("actual_price_lakh")} for p in priced],
        "definitions": {
            "predicted_price": "CPI predicted auction price: p50 with an 80% range (p10–p90), conformally calibrated.",
            "market_value": "CPI estimated market value: price implied by on-field performance features only.",
            "market_premium": "Predicted price ÷ performance-implied value. <1 suggests undervalued, >1.25 overvalued.",
            "bidding_war": "Probability the price reaches ≥3× base, from the predicted price distribution.",
            "actual": "Recorded historical outcome (replays only) — shown for comparison, never used as an input.",
        },
    })


@router.get("/players")
def players(context: str, f: PlayerFilters = Depends(_filters), sort: str = "p50", desc: bool = True,
            page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=200), db: Session = Depends(get_db)):
    ctx, val = _valuation(db, context)
    rows = _filter_players(val["players"], **f.model_dump())
    keyfn = {
        "p50": lambda p: p.get("p50") or -1, "quality": lambda p: p.get("quality") or -1,
        "base": lambda p: p.get("base_lakh") or -1, "war": lambda p: p.get("bidding_war_probability") or -1,
        "premium": lambda p: p.get("market_premium") or 99, "name": lambda p: p["name"],
        "lot": lambda p: p.get("lot_number") or 99999, "scarcity": lambda p: (p.get("scarcity") or {}).get("score") or -1,
        "actual": lambda p: p.get("actual_price_lakh") or -1,
    }.get(sort, lambda p: p.get("p50") or -1)
    rows = sorted(rows, key=keyfn, reverse=desc)
    start = (page - 1) * page_size
    return _clean({"total": len(rows), "page": page, "page_size": page_size,
                   "items": [_player_row(p) for p in rows[start:start + page_size]]})


@router.get("/players/{key:path}")
def player_detail(key: str, context: str, db: Session = Depends(get_db)):
    ctx, val = _valuation(db, context)
    p = next((x for x in val["players"] if _pkey(x) == key), None)
    if not p:
        raise HTTPException(404, "Player not in this auction pool")
    targets = mk.derive_requirement_targets(db, ctx.as_of)
    interest = []
    room_state = {"seed": 1, "franchises": {c: {} for c in ctx.franchises}}
    for code, fr in ctx.franchises.items():
        if fr["purse_lakh"] is None:
            continue
        st = op.franchise_state(ctx, val, code, targets=targets)
        mv = op.marginal_value(st, p, ctx.rules.max_overseas_xi)
        eligible = st["purse"]["slots_left"] > 0 and not (p.get("overseas") and st["purse"]["overseas_slots_left"] <= 0)
        interest.append({"franchise": code, "name": fr["name"], "eligible": eligible, "marginal": mv,
                         "purse_lakh": fr["purse_lakh"], "max_bid_lakh": st["purse"]["max_theoretical_bid_lakh"],
                         "need_score": round(min(1.6, max(0, mv["total"] / 45)), 2)})
    interest.sort(key=lambda r: (-r["eligible"], -r["need_score"]))
    history = []
    if p.get("player_id"):
        for lot in db.scalars(select(AuctionLot).where(AuctionLot.player_id == p["player_id"]).order_by(AuctionLot.season)).all():
            history.append({"season": lot.season, "status": lot.status, "franchise": lot.franchise,
                            "price_lakh": float(lot.final_price_lakh) if lot.final_price_lakh is not None else None,
                            "base_lakh": float(lot.base_price_lakh) if lot.base_price_lakh is not None else None,
                            "verification": lot.verification, "sources": [s["source"] for s in lot.sources],
                            "future_of_context": bool(ctx.rules.season and lot.season >= ctx.rules.season)})
    return _clean({"player": _player_row(p), "features": p.get("features"), "explanation": p.get("explanation"),
                   "alternatives": op.alternatives(val, p, val["players"]), "franchise_interest": interest,
                   "auction_history": history, "model": val["models"],
                   "labels": {"franchise_interest": "Model-estimated from each franchise's squad and purse",
                              "auction_history": "Recorded outcomes; rows marked future_of_context were not available at this auction"}})


# ----------------------------------------------------------------- franchises

@router.get("/franchises")
def franchises(context: str, db: Session = Depends(get_db)):
    ctx, val = _valuation(db, context)
    targets = mk.derive_requirement_targets(db, ctx.as_of)
    out = []
    for code, fr in sorted(ctx.franchises.items()):
        st = op.franchise_state(ctx, val, code, targets=targets)
        out.append({"code": code, "name": fr["name"], "purse": st["purse"], "purse_basis": fr["purse_basis"],
                    "squad_size": len(st["members"]), "overseas": st["overseas"], "xi_score": st["xi"]["score"],
                    "needs": st["needs"][:5]})
    return _clean({"context": ctx.key, "franchises": out, "requirement_targets": targets})


@router.get("/franchises/{code}")
def franchise_detail(code: str, context: str, db: Session = Depends(get_db)):
    ctx, val = _valuation(db, context)
    if code not in ctx.franchises:
        raise HTTPException(404, "Franchise not in this context")
    targets = mk.derive_requirement_targets(db, ctx.as_of)
    st = op.franchise_state(ctx, val, code, targets=targets)
    pool = val["players"]
    targets_list = []
    if st["purse"].get("known"):
        for p in pool:
            if not p.get("p50") or (p.get("overseas") and st["purse"]["overseas_slots_left"] <= 0):
                continue
            mv = op.marginal_value(st, p, ctx.rules.max_overseas_xi)
            if mv["total"] <= 0:
                continue
            targets_list.append({**_player_row(p), "marginal": mv,
                                 "value_per_crore": round(mv["total"] / max(p["p50"] / 100, 0.2), 1)})
        targets_list.sort(key=lambda r: -r["marginal"]["total"])
    behaviour = mk.franchise_behaviour(db, ctx.rules.season).get(code)
    return _clean({
        "code": code, "name": ctx.franchises[code]["name"], "purse": st["purse"],
        "purse_basis": ctx.franchises[code]["purse_basis"],
        "squad": [{**m, "price_lakh": next((x.get("price_lakh") for x in ctx.franchises[code]["squad"] if x.get("player_id") == m["player_id"]), None)}
                  for m in st["members"]],
        "xi": st["xi"], "needs": st["needs"], "requirement_targets": targets,
        "priority_targets": targets_list[:15],
        "value_targets": sorted(targets_list, key=lambda r: -r["value_per_crore"])[:10],
        "critical_reserve": op.critical_reserve(st, pool),
        "behaviour": behaviour,
        "labels": {"needs": "Calculated from the actual squad and IPL squad-usage data",
                   "behaviour": "Historical observations; tendencies listed only when statistically significant (|z| ≥ 2)"},
    })


class OptimizeBody(BaseModel):
    context: str
    franchise: str
    plan: Literal["balanced", "aggressive", "conservative", "value", "role_first"] = "balanced"
    draws: int = Field(12, ge=0, le=40)


@router.post("/optimize")
def optimize(body: OptimizeBody, db: Session = Depends(get_db)):
    ctx, val = _valuation(db, body.context)
    if body.franchise not in ctx.franchises:
        raise HTTPException(404, "Franchise not in this context")
    st = op.franchise_state(ctx, val, body.franchise, targets=mk.derive_requirement_targets(db, ctx.as_of))
    return _clean(op.optimise(ctx, val, st, val["players"], plan=body.plan, draws=body.draws))


class ScenarioPurchase(BaseModel):
    player_key: str
    price_lakh: Optional[float] = None


class ScenarioItem(BaseModel):
    name: str
    purchases: List[ScenarioPurchase]


class CompareBody(BaseModel):
    context: str
    franchise: str
    scenarios: List[ScenarioItem] = Field(min_length=1, max_length=4)


@router.post("/purchase-scenarios/compare")
def compare(body: CompareBody, db: Session = Depends(get_db)):
    ctx, val = _valuation(db, body.context)
    if body.franchise not in ctx.franchises:
        raise HTTPException(404, "Franchise not in this context")
    st = op.franchise_state(ctx, val, body.franchise, targets=mk.derive_requirement_targets(db, ctx.as_of))
    if not st["purse"].get("known"):
        raise HTTPException(422, "Purse unknown for this franchise")
    return _clean({"franchise": body.franchise, "purse_lakh": st["purse"]["purse_lakh"], "xi_now": st["xi"]["score"],
                   "results": op.compare_scenarios(ctx, val, st, val["players"], [s.model_dump() for s in body.scenarios])})


# ----------------------------------------------------------------- auction room
# The AI auction room runs on the existing session tables: an AuctionSession
# with simulation_mode="AI_ROOM" holds the engine state, and every call, bid
# and sale is written as an ordinary AuctionEvent / AuctionBid / AuctionPurchase
# (amounts in crore, like manual sessions), so /sessions/{id}/events shows it.

class RoomCreate(BaseModel):
    context: str
    user_franchise: Optional[str] = None
    strategy: Literal["balanced", "aggressive", "conservative", "value", "role_first"] = "balanced"
    seed: int = 42
    order: Literal["recorded", "quality"] = "recorded"


class RoomAction(BaseModel):
    action: Literal["call", "bid", "pass", "step", "resolve", "auto", "complete", "strategy"]
    amount: Optional[float] = None
    lots: int = Field(1, ge=1, le=600)
    strategy: Optional[str] = None


def _session_teams(db: Session, ctx: mk.Context) -> tuple:
    """Scenario id and AuctionTeam ids for a context. Replays get a REPLAY
    scenario with one AuctionTeam per franchise (purse from the sourced/derived
    pre-auction purse) so sessions keep their existing foreign keys."""
    if ctx.key.startswith("scenario:"):
        sid = ctx.key.split(":", 1)[1]
        teams = db.scalars(select(AuctionTeam).where(AuctionTeam.scenario_id == sid)).all()
        by_code = {}
        for t in teams:
            code = next((c for c, f in ctx.franchises.items() if f.get("team_id") == t.id), None)
            if code:
                by_code[code] = t.id
        return sid, by_code
    season = ctx.rules.season
    sc = db.scalar(select(AuctionScenario).where(AuctionScenario.status == "REPLAY", AuctionScenario.season == str(season)))
    if not sc:
        sc = AuctionScenario(name=f"IPL {season} auction replay", season=str(season), auction_type=ctx.rules.auction_type,
                             status="REPLAY")
        db.add(sc)
        db.flush()
    existing = {t.franchise_code: t for t in db.scalars(select(AuctionTeam).where(AuctionTeam.scenario_id == sc.id)).all()}
    for code, f in ctx.franchises.items():
        if f["purse_lakh"] is None or code in existing:
            continue
        purse_cr = Decimal(str(round(f["purse_lakh"] / 100, 2)))
        t = AuctionTeam(scenario_id=sc.id, franchise_name=f["name"], franchise_code=code, initial_purse=purse_cr,
                        remaining_purse=purse_cr, minimum_squad_size=ctx.rules.min_squad,
                        maximum_squad_size=ctx.rules.max_squad, overseas_squad_limit=ctx.rules.max_overseas_squad)
        db.add(t)
        existing[code] = t
    db.flush()
    return sc.id, {c: t.id for c, t in existing.items()}


def _cr(lakh):
    return Decimal(str(round(float(lakh) / 100, 4))) if lakh is not None else None


def _persist(db: Session, session: AuctionSession, room: AuctionRoom, team_ids: dict, before: dict):
    """Write every call / bid / result produced since ``before`` as session records."""
    st = room.state
    seq = db.scalar(select(func.max(AuctionEvent.sequence_number)).where(AuctionEvent.session_id == session.id)) or 0

    def event(kind, player_id, team, amount, payload):
        nonlocal seq
        seq += 1
        e = AuctionEvent(session_id=session.id, sequence_number=seq, event_type=kind, player_id=player_id,
                         team_id=team_ids.get(team) if team else None, bid_amount=_cr(amount), event_payload=payload)
        db.add(e)
        return e

    def lot_records(key, name, history, start, called):
        p = room.players.get(key, {})
        pid = p.get("player_id")
        if called:
            event("PLAYER_CALLED", pid, None, p.get("base_lakh"), {"player": name, "source": "AI_ROOM"})
        for h in history[start:]:
            event("BID_PLACED", pid, h["franchise"], h["bid_lakh"], {"source": h["source"], "player": name})
            if pid and h["franchise"] in team_ids:
                db.add(AuctionBid(session_id=session.id, player_id=pid, team_id=team_ids[h["franchise"]],
                                  bid_amount=_cr(h["bid_lakh"]), bid_source="USER" if h["source"].startswith("USER") else "AI"))

    open_key = before.get("open_key")
    for r in st["results"][before["results"]:]:
        was_open = r["player_key"] == open_key
        lot_records(r["player_key"], r["name"], r["history"], before["open_bids"] if was_open else 0, not was_open)
        pid = room.players.get(r["player_key"], {}).get("player_id")
        if r["status"] == "SOLD":
            e = event("PLAYER_SOLD", pid, r["franchise"], r["price_lakh"], {"player": r["name"], "rtm": r.get("rtm"), "source": "AI_ROOM"})
            db.flush()
            if pid and r["franchise"] in team_ids:
                db.add(AuctionPurchase(session_id=session.id, player_id=pid, team_id=team_ids[r["franchise"]],
                                       purchase_price=_cr(r["price_lakh"]), acquisition_type="RTM" if "used RTM" in (r.get("rtm") or "") else "AUCTION",
                                       auction_event_id=e.id))
        else:
            event("PLAYER_UNSOLD", pid, None, None, {"player": r["name"], "source": "AI_ROOM"})
    lot = st.get("lot")
    if lot and lot["status"] == "BIDDING":
        same = lot["player_key"] == open_key
        lot_records(lot["player_key"], lot["name"], lot["history"], before["open_bids"] if same else 0, not same)
    # Scenario teams are never mutated by a simulation (run_scenario reads their
    # purse); live purses live in the room state. Mirror the open lot only.
    if lot and lot["status"] == "BIDDING":
        session.active_player_id = room.players.get(lot["player_key"], {}).get("player_id")
        session.current_bid = _cr(lot["bid"])
        session.current_team_id = team_ids.get(lot["leader"]) if lot["leader"] else None
    else:
        session.active_player_id = session.current_bid = session.current_team_id = None
    session.session_status = "COMPLETED" if st["status"] == "COMPLETE" else "RUNNING" if st["cursor"] else "READY"
    session.state = dict(st)
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(session, "state")


def _mark(st: dict) -> dict:
    lot = st.get("lot")
    open_lot = lot if lot and lot["status"] == "BIDDING" else None
    return {"results": len(st["results"]), "open_key": open_lot["player_key"] if open_lot else None,
            "open_bids": len(open_lot["history"]) if open_lot else 0}


def _room_payload(session: AuctionSession, room: AuctionRoom) -> dict:
    ctx = room.ctx
    return _clean({"id": session.id, "scenario_id": session.scenario_id, **room.snapshot(), "summary": room.summary(),
                   "context": {"key": ctx.key, "label": ctx.label, "notes": ctx.notes, "rules": ctx.rules.as_dict()}})


def _room_session(db: Session, session_id: str) -> AuctionSession:
    s = db.get(AuctionSession, session_id)
    if not s or s.simulation_mode != "AI_ROOM" or not s.state:
        raise HTTPException(404, "Auction room not found")
    return s


@router.post("/rooms")
def room_create(body: RoomCreate, db: Session = Depends(get_db)):
    ctx = _ctx(db, body.context)
    usable = [c for c, f in ctx.franchises.items() if f["purse_lakh"] is not None]
    if len(usable) < 2:
        raise HTTPException(422, "Fewer than two franchises have a known purse in this context; it cannot be simulated.")
    scenario_id, team_ids = _session_teams(db, ctx)
    state = AuctionRoom.new_state(db, ctx, body.user_franchise, body.strategy, body.seed, body.order)
    state["team_ids"] = team_ids
    session = AuctionSession(scenario_id=scenario_id, simulation_mode="AI_ROOM", session_status="READY",
                             context_key=ctx.key, state=state)
    db.add(session)
    db.commit()
    return _room_payload(session, AuctionRoom(db, ctx, session.state))


@router.get("/rooms")
def room_list(db: Session = Depends(get_db)):
    rows = db.scalars(select(AuctionSession).where(AuctionSession.simulation_mode == "AI_ROOM")
                      .order_by(AuctionSession.created_at.desc()).limit(20)).all()
    return [{"id": r.id, "context": r.context_key, "user_franchise": (r.state or {}).get("user_franchise"),
             "strategy": (r.state or {}).get("strategy"), "status": r.session_status,
             "progress": f"{(r.state or {}).get('cursor', 0)}/{len((r.state or {}).get('order', []))}",
             "created_at": r.created_at.isoformat() if r.created_at else None} for r in rows]


@router.get("/rooms/{session_id}")
def room_get(session_id: str, db: Session = Depends(get_db)):
    s = _room_session(db, session_id)
    return _room_payload(s, AuctionRoom(db, _ctx(db, s.context_key), dict(s.state)))


@router.post("/rooms/{session_id}/action")
def room_action(session_id: str, body: RoomAction, db: Session = Depends(get_db)):
    session = _room_session(db, session_id)
    room = AuctionRoom(db, _ctx(db, session.context_key), dict(session.state))
    st = room.state
    before = _mark(st)
    try:
        if body.action == "strategy":
            if body.strategy not in STRATEGIES:
                raise ValueError("Unknown strategy")
            st["strategy"] = body.strategy
        elif body.action == "call":
            room.call_next()
        elif body.action == "bid":
            room.user_bid(body.amount)
        elif body.action == "pass":
            room.user_pass()
            room.run_lot()
        elif body.action == "step":
            if not st.get("lot") or st["lot"]["status"] != "BIDDING":
                room.call_next()
            else:
                room.ai_step()
        elif body.action == "resolve":
            if st.get("lot") and st["lot"]["status"] == "BIDDING":
                room.run_lot()
        elif body.action in ("auto", "complete"):
            n = body.lots if body.action == "auto" else 10 ** 6
            done = 0
            while done < n and st["status"] != "COMPLETE":
                if not st.get("lot") or st["lot"]["status"] != "BIDDING":
                    room.call_next()
                    if st["status"] == "COMPLETE":
                        break
                room.run_lot(user_autopilot=True)
                done += 1
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    _persist(db, session, room, st.get("team_ids", {}), before)
    db.commit()
    return _room_payload(session, room)


# ----------------------------------------------------------------- history

def _history_query(db: Session, season: Optional[int], franchise: Optional[str], role: Optional[str],
                   overseas: Optional[bool], status: Optional[str]):
    q = select(AuctionLot).where(AuctionLot.acquisition_type == "auction")
    if season:
        q = q.where(AuctionLot.season == season)
    if franchise:
        q = q.where(AuctionLot.franchise == franchise)
    if role:
        q = q.where(AuctionLot.role == role)
    if overseas is not None:
        q = q.where(AuctionLot.overseas.is_(overseas))
    if status:
        q = q.where(AuctionLot.status == status)
    return q


@router.get("/history")
def history(season_from: int = 2008, season_to: int = 2100, franchise: Optional[str] = None, role: Optional[str] = None,
            overseas: Optional[bool] = None, db: Session = Depends(get_db)):
    lots = db.scalars(_history_query(db, None, franchise, role, overseas, None)
                      .where(AuctionLot.season >= season_from, AuctionLot.season <= season_to)).all()
    seasons = {s.season: s for s in db.scalars(select(AuctionSeason)).all()}
    sold = [l for l in lots if l.status == "SOLD" and l.final_price_lakh is not None and l.verification != "conflict"]
    by_season = defaultdict(list)
    for l in sold:
        by_season[l.season].append(float(l.final_price_lakh))
    season_rows = []
    for s in sorted({l.season for l in lots}):
        prices = by_season.get(s, [])
        cfg = seasons.get(s)
        purse = float(cfg.purse_lakh) if cfg and cfg.purse_lakh else None
        unsold = sum(1 for l in lots if l.season == s and l.status == "UNSOLD")
        season_rows.append({"season": s, "auction_type": cfg.auction_type if cfg else None, "sold": len(prices),
                            "unsold_recorded": unsold, "total_spend_lakh": round(sum(prices), 0),
                            "avg_price_lakh": round(statistics.mean(prices), 1) if prices else None,
                            "median_price_lakh": round(statistics.median(prices), 1) if prices else None,
                            "max_price_lakh": max(prices) if prices else None, "purse_lakh": purse,
                            "avg_share_of_purse": round(statistics.mean(prices) / purse, 4) if prices and purse else None,
                            "uncapped_spend_lakh": round(sum(float(l.final_price_lakh) for l in sold if l.season == s and l.capped is False), 0),
                            "uncapped_known": any(l.capped is not None for l in lots if l.season == s)})
    fr = defaultdict(lambda: {"spend": 0.0, "n": 0})
    for l in sold:
        if l.franchise:
            fr[l.franchise]["spend"] += float(l.final_price_lakh)
            fr[l.franchise]["n"] += 1
    role_rows = defaultdict(list)
    for l in sold:
        role_rows[(l.role or "Unknown")].append(float(l.final_price_lakh))

    def dist(vals):
        vals = sorted(vals)
        q = lambda x: vals[min(len(vals) - 1, int(x * (len(vals) - 1)))]
        return {"n": len(vals), "p10": q(.1), "p25": q(.25), "median": q(.5), "p75": q(.75), "p90": q(.9), "max": vals[-1]}
    role_season = defaultdict(lambda: defaultdict(float))
    for l in sold:
        role_season[l.season][l.role or "Unknown"] += float(l.final_price_lakh)
    mm = {}
    for kind in ("MEGA", "MINI"):
        vals = [float(l.final_price_lakh) for l in sold if seasons.get(l.season) and seasons[l.season].auction_type == kind]
        shares = [float(l.final_price_lakh) / float(seasons[l.season].purse_lakh) for l in sold
                  if seasons.get(l.season) and seasons[l.season].auction_type == kind and seasons[l.season].purse_lakh]
        mm[kind] = {"sold": len(vals), "median_lakh": statistics.median(vals) if vals else None,
                    "median_share_of_purse": round(statistics.median(shares), 4) if shares else None,
                    "share_over_5pct_purse": round(sum(1 for s in shares if s >= 0.05) / len(shares), 3) if shares else None}
    base_final = [{"name": l.player_name, "season": l.season, "base": float(l.base_price_lakh), "final": float(l.final_price_lakh),
                   "role": l.role, "overseas": l.overseas, "franchise": l.franchise}
                  for l in sold if l.base_price_lakh]
    multiples = [b["final"] / b["base"] for b in base_final if b["base"]]
    top = sorted(sold, key=lambda l: -float(l.final_price_lakh))
    rec = lambda l: {"id": l.id, "season": l.season, "player": l.player_name, "player_id": l.player_id, "franchise": l.franchise,
                     "price_lakh": float(l.final_price_lakh), "role": l.role, "overseas": l.overseas,
                     "base_lakh": float(l.base_price_lakh) if l.base_price_lakh is not None else None,
                     "verification": l.verification}
    return _clean({
        "records": len(lots), "sold_records": len(sold),
        "by_season": season_rows,
        "by_franchise": sorted([{"franchise": k, "spend_lakh": round(v["spend"], 0), "purchases": v["n"],
                                 "avg_lakh": round(v["spend"] / v["n"], 1)} for k, v in fr.items()], key=lambda r: -r["spend_lakh"]),
        "by_role": {k: dist(v) for k, v in role_rows.items() if v},
        "role_spend_by_season": [{"season": s, **{k: round(v, 0) for k, v in d.items()}} for s, d in sorted(role_season.items())],
        "mega_vs_mini": mm,
        "base_vs_final": base_final[:1500],
        "base_multiple": {"n": len(multiples), "median": round(statistics.median(multiples), 2) if multiples else None,
                          "share_at_base": round(sum(1 for m in multiples if m <= 1.0001) / len(multiples), 3) if multiples else None,
                          "share_3x_plus": round(sum(1 for m in multiples if m >= 3) / len(multiples), 3) if multiples else None},
        "most_expensive": [rec(l) for l in top[:15]],
        "most_expensive_indian": [rec(l) for l in top if l.overseas is False][:10],
        "most_expensive_overseas": [rec(l) for l in top if l.overseas is True][:10],
        "notes": ["Prices are recorded sale prices (historical actuals), not CPI estimates.",
                  "Lots with conflicting source prices are excluded from aggregates.",
                  "Unsold counts exist only for seasons whose sources record unsold players (2021 partial, 2022, 2023)."],
    })


@router.get("/history/records")
def history_records(season: Optional[int] = None, franchise: Optional[str] = None, role: Optional[str] = None,
                    overseas: Optional[bool] = None, status: Optional[str] = None, search: Optional[str] = None,
                    page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=200), db: Session = Depends(get_db)):
    q = _history_query(db, season, franchise, role, overseas, status)
    if search:
        q = q.where(AuctionLot.player_name.ilike(f"%{search}%"))
    total = db.scalar(select(func.count()).select_from(q.subquery()))
    rows = db.scalars(q.order_by(AuctionLot.season.desc(), AuctionLot.final_price_lakh.desc().nullslast())
                      .offset((page - 1) * page_size).limit(page_size)).all()
    return _clean({"total": total, "page": page, "page_size": page_size, "items": [{
        "id": l.id, "season": l.season, "player": l.player_name, "player_id": l.player_id, "status": l.status,
        "franchise": l.franchise, "previous_franchise": l.previous_franchise, "role": l.role, "overseas": l.overseas,
        "capped": l.capped, "set_code": l.set_code, "lot_number": l.lot_number, "is_rtm": l.is_rtm,
        "base_lakh": float(l.base_price_lakh) if l.base_price_lakh is not None else None,
        "price_lakh": float(l.final_price_lakh) if l.final_price_lakh is not None else None,
        "verification": l.verification, "identity_status": l.identity_status,
        "sources": l.sources, "conflict_note": l.conflict_note} for l in rows]})


# ----------------------------------------------------------------- backtesting

def _latest_backtest(db: Session, version: Optional[str] = None):
    q = select(AuctionModelRun).where(AuctionModelRun.task == "v2_backtest")
    if version:
        q = q.where(AuctionModelRun.model_version == version)
    return db.scalar(q.order_by(AuctionModelRun.created_at.desc()))


@router.get("/backtest")
def backtest(version: Optional[str] = None, db: Session = Depends(get_db)):
    run = _latest_backtest(db, version)
    versions = db.scalars(select(AuctionModelRun).where(AuctionModelRun.task.in_(("v2_backtest", "v2_price", "price_regression")))
                          .order_by(AuctionModelRun.created_at.desc()).limit(30)).all()
    return _clean({"run": {"version": run.model_version, "created_at": run.created_at.isoformat(),
                           "training_rows": run.training_rows, "evaluated_rows": run.validation_rows,
                           "evaluation": run.evaluation_json} if run else None,
                   "versions": [{"version": v.model_version, "task": v.task, "created_at": v.created_at.isoformat(),
                                 "rows": v.training_rows,
                                 "pooled_mae_lakh": ((v.evaluation_json or {}).get("pooled") or {}).get("cpi", {}).get("mae_lakh")
                                 if v.task == "v2_backtest" else (v.evaluation_json or {}).get("mae_lakh")}
                                for v in versions]})


@router.get("/backtest/predictions")
def backtest_predictions(season: Optional[int] = None, version: Optional[str] = None, db: Session = Depends(get_db)):
    run = _latest_backtest(db, version)
    if not run:
        return {"items": []}
    q = select(AuctionBacktestPrediction, AuctionLot).join(AuctionLot, AuctionLot.id == AuctionBacktestPrediction.lot_id) \
        .where(AuctionBacktestPrediction.model_version == run.model_version)
    if season:
        q = q.where(AuctionBacktestPrediction.season == season)
    items = []
    for bp, lot in db.execute(q).all():
        items.append({"season": bp.season, "player": lot.player_name, "player_id": bp.player_id, "role": lot.role,
                      "overseas": lot.overseas, "status": bp.actual_status, "franchise": bp.actual_franchise,
                      "actual_lakh": float(bp.actual_price_lakh) if bp.actual_price_lakh is not None else None,
                      "p10": float(bp.p10_lakh) if bp.p10_lakh is not None else None,
                      "p50": float(bp.p50_lakh) if bp.p50_lakh is not None else None,
                      "p90": float(bp.p90_lakh) if bp.p90_lakh is not None else None,
                      "sold_probability": bp.sold_probability, "baselines": bp.baselines})
    return _clean({"version": run.model_version, "items": items})


_BACKTEST_RUNNING = {"running": False, "last": None}


def _run_backtest_job():
    db = SessionLocal()
    try:
        r = M.run_backtest(db, persist=True)
        M.train_production(db)
        mk.invalidate_caches()
        _CTX.clear()
        _BACKTEST_RUNNING["last"] = {"version": r["model_version"], "status": "complete"}
    except Exception as exc:  # surfaced through /backtest/status
        _BACKTEST_RUNNING["last"] = {"status": "failed", "error": str(exc)}
    finally:
        _BACKTEST_RUNNING["running"] = False
        db.close()


@router.post("/backtest/run", status_code=202)
def backtest_run(tasks: BackgroundTasks):
    if _BACKTEST_RUNNING["running"]:
        return {"status": "already running"}
    _BACKTEST_RUNNING["running"] = True
    tasks.add_task(_run_backtest_job)
    return {"status": "started", "note": "Rolling backtest and production retrain take roughly 2–3 minutes."}


@router.get("/backtest/status")
def backtest_status():
    return _BACKTEST_RUNNING
