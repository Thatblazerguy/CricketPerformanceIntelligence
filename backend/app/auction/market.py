"""Market context, player valuation, squad evaluation and franchise intelligence.

A *market context* is everything known immediately before an auction:

* ``season:<year>``   — a completed IPL auction replayed with information
  available before its auction date (pool = recorded lots for that auction,
  squads = recorded retentions, purse = sourced/derived purse; models are
  re-trained on earlier seasons only, so the replay is leakage-free);
* ``scenario:<id>``   — a user scenario (uploaded retention list + player
  pool) valued with the production model and current data.

Four price notions are kept apart everywhere:

1. ``actual_price_lakh``      — the historical recorded sale (replays only).
2. ``market_value_lakh``      — CPI estimated market value: performance-implied
                                 price (on-field features only).
3. ``predicted_price_lakh``   — CPI predicted auction price (p10/p50/p90) from
                                 the full model incl. market context.
4. Simulation purchase prices — produced only by ``app.auction.simulator``.
"""
from __future__ import annotations

import math
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy.optimize import Bounds, LinearConstraint, milp
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.ml import auction_price as M
from app.auction.features import get_features
from app.auction.sources import FRANCHISE_NAMES, franchise_code
from app.models.models import (
    AuctionFranchiseSeason, AuctionLot, AuctionPlayer, AuctionRetention, AuctionRule, AuctionScenario,
    AuctionSeason, AuctionTeam, Player, PlayerAttribute,
)

ACTIVE_FRANCHISES = ["CSK", "DC", "GT", "KKR", "LSG", "MI", "PBKS", "RCB", "RR", "SRH"]
ASSUMED_QUALITY = 40.0  # used only when a player has no T20 evidence at all; always flagged


# ==========================================================================
# Context
# ==========================================================================

@dataclass
class Rules:
    season: Optional[int]
    auction_type: str
    purse_lakh: Optional[float]
    min_squad: int
    max_squad: int
    max_overseas_squad: int
    max_overseas_xi: int
    min_base_price_lakh: float
    rtm_enabled: bool
    bid_increments: List[List[float]]
    provenance: dict = field(default_factory=dict)

    def increment(self, current_lakh: float) -> float:
        inc = 5.0
        for threshold, step in self.bid_increments or [[0, 5]]:
            if current_lakh >= threshold:
                inc = step
        return float(inc)

    def as_dict(self):
        return {k: getattr(self, k) for k in ("season", "auction_type", "purse_lakh", "min_squad", "max_squad",
                                              "max_overseas_squad", "max_overseas_xi", "min_base_price_lakh",
                                              "rtm_enabled", "bid_increments", "provenance")}


@dataclass
class Context:
    key: str
    label: str
    as_of: date
    rules: Rules
    pool: List[dict]
    franchises: Dict[str, dict]
    historical: bool
    notes: List[str] = field(default_factory=list)


def _rules_from_season(s: AuctionSeason) -> Rules:
    return Rules(season=s.season, auction_type=s.auction_type,
                 purse_lakh=float(s.purse_lakh) if s.purse_lakh else None,
                 min_squad=s.min_squad or 18, max_squad=s.max_squad or 25,
                 max_overseas_squad=s.max_overseas_squad or 8, max_overseas_xi=s.max_overseas_xi or 4,
                 min_base_price_lakh=float(s.min_base_price_lakh or 20), rtm_enabled=bool(s.rtm_enabled),
                 bid_increments=s.bid_increments or [[0, 5], [100, 10], [200, 20], [300, 25]],
                 provenance=dict(s.rule_sources or {}))


def _bowling_kinds(db: Session, ids: List[str]) -> Dict[str, str]:
    out = {}
    if not ids:
        return out
    for pid, kind in db.execute(select(AuctionLot.player_id, AuctionLot.bowling_kind).where(
            AuctionLot.player_id.in_(ids), AuctionLot.bowling_kind.is_not(None))).all():
        out.setdefault(pid, kind)
    for pid, value in db.execute(select(PlayerAttribute.player_id, PlayerAttribute.attribute_value).where(
            PlayerAttribute.player_id.in_(ids), PlayerAttribute.attribute_type == "bowling_type")).all():
        out.setdefault(pid, "pace" if value.casefold().startswith("pace") else "spin")
    return out


def _nationality(db: Session, ids: List[str]) -> Dict[str, Optional[bool]]:
    out = {}
    if not ids:
        return out
    for pid, ov in db.execute(select(AuctionLot.player_id, AuctionLot.overseas).where(
            AuctionLot.player_id.in_(ids), AuctionLot.overseas.is_not(None)).order_by(AuctionLot.season.desc())).all():
        out.setdefault(pid, ov)
    for pid, nat in db.execute(select(PlayerAttribute.player_id, PlayerAttribute.attribute_value).where(
            PlayerAttribute.player_id.in_(ids), PlayerAttribute.attribute_type == "nationality")).all():
        if pid not in out and nat and nat.casefold() not in ("unknown",):
            out[pid] = nat.strip().casefold() not in ("india", "indian")
    return out


def _roles_hist(db: Session, ids: List[str]) -> Dict[str, str]:
    out = {}
    if ids:
        for pid, role in db.execute(select(AuctionLot.player_id, AuctionLot.role).where(
                AuctionLot.player_id.in_(ids), AuctionLot.role.is_not(None)).order_by(AuctionLot.season.desc())).all():
            out.setdefault(pid, role)
    return out


def available_contexts(db: Session) -> List[dict]:
    seasons = {s.season: s for s in db.scalars(select(AuctionSeason)).all()}
    counts = db.execute(text("""SELECT season, COUNT(*) FILTER (WHERE acquisition_type='auction') pool,
        COUNT(*) FILTER (WHERE status='UNSOLD') unsold, COUNT(*) FILTER (WHERE status='RETAINED') retained
        FROM auction_lots GROUP BY season""")).mappings().all()
    fs = db.execute(text("""SELECT season, COUNT(*) n, COUNT(*) FILTER (WHERE purse_basis <> 'unknown') known
        FROM auction_franchise_seasons GROUP BY season""")).mappings().all()
    fs = {r["season"]: r for r in fs}
    out = []
    for r in sorted(counts, key=lambda r: -r["season"]):
        s = seasons.get(r["season"])
        f = fs.get(r["season"], {})
        if not s or r["season"] < 2018:
            continue
        reported = (s.rule_sources or {}).get("pool_size_reported")
        out.append({"key": f"season:{r['season']}", "label": f"IPL {r['season']} auction ({s.auction_type.title()})",
                    "season": r["season"], "auction_date": s.auction_date.isoformat() if s.auction_date else None,
                    "auction_type": s.auction_type, "pool_recorded": r["pool"], "unsold_recorded": r["unsold"],
                    "pool_size_reported": reported,
                    "pool_complete": bool(r["unsold"]) and (not reported or r["pool"] >= 0.9 * reported),
                    "purse_known_for": f.get("known", 0), "franchises": f.get("n", 0),
                    "simulatable": f.get("known", 0) >= 8})
    for sc in db.scalars(select(AuctionScenario).where(AuctionScenario.status != "REPLAY")
                         .order_by(AuctionScenario.created_at.desc())).all():
        n_pool = db.scalar(select(text("count(*)")).select_from(AuctionPlayer).where(AuctionPlayer.scenario_id == sc.id))
        n_teams = db.scalar(select(text("count(*)")).select_from(AuctionTeam).where(AuctionTeam.scenario_id == sc.id))
        out.append({"key": f"scenario:{sc.id}", "label": f"Scenario: {sc.name} ({sc.season})", "season": None,
                    "scenario_id": sc.id, "pool_recorded": n_pool, "franchises": n_teams,
                    "simulatable": bool(n_pool and n_teams), "pool_complete": None})
    return out


def build_context(db: Session, key: str) -> Context:
    kind, _, ident = key.partition(":")
    if kind == "season":
        return _season_context(db, int(ident))
    if kind == "scenario":
        return _scenario_context(db, ident)
    raise ValueError("Unknown context key")


def _player_entry(pid, name, role, kind, overseas, capped=None, base=None, set_code=None, lot_number=None,
                  identity="MATCHED", **extra):
    return {"player_id": pid, "name": name, "role": role, "bowling_kind": kind, "overseas": overseas,
            "capped": capped, "base_lakh": base, "set_code": set_code, "lot_number": lot_number,
            "identity_status": identity, **extra}


def _season_context(db: Session, season: int) -> Context:
    s = db.get(AuctionSeason, season)
    if not s or not s.auction_date:
        raise ValueError(f"No auction configuration for season {season}")
    rules = _rules_from_season(s)
    lots = db.scalars(select(AuctionLot).where(AuctionLot.season == season)).all()
    ids = [l.player_id for l in lots if l.player_id]
    kinds = _bowling_kinds(db, ids)
    pool, squads = [], defaultdict(list)
    for l in lots:
        entry = _player_entry(l.player_id, l.player_name, l.role, l.bowling_kind or kinds.get(l.player_id),
                              l.overseas, l.capped, float(l.base_price_lakh) if l.base_price_lakh is not None else None,
                              l.set_code, l.lot_number, l.identity_status, lot_id=l.id,
                              previous_franchise=l.previous_franchise, verification=l.verification,
                              actual_status=l.status, actual_franchise=l.franchise,
                              actual_price_lakh=float(l.final_price_lakh) if l.final_price_lakh is not None else None,
                              is_rtm=l.is_rtm)
        if l.status == "RETAINED":
            if l.franchise:
                squads[l.franchise].append({**entry, "price_lakh": entry["actual_price_lakh"], "acquired": "retained"})
        else:
            pool.append(entry)
    pool.sort(key=lambda p: (p["lot_number"] is None, p["lot_number"] or 0, -(p["base_lakh"] or 0), p["name"]))
    franchises = {}
    for fs in db.scalars(select(AuctionFranchiseSeason).where(AuctionFranchiseSeason.season == season)).all():
        franchises[fs.franchise] = {
            "code": fs.franchise, "name": FRANCHISE_NAMES.get(fs.franchise, fs.franchise),
            "purse_lakh": float(fs.purse_before_auction_lakh) if fs.purse_before_auction_lakh is not None else None,
            "purse_basis": fs.purse_basis, "squad": squads.get(fs.franchise, []),
            "slots_left_recorded": fs.slots_left, "overseas_slots_left_recorded": fs.overseas_slots_left}
    notes = []
    unsold = sum(1 for p in pool if p["actual_status"] == "UNSOLD")
    reported = rules.provenance.get("pool_size_reported")
    if not unsold:
        notes.append(f"Only sold players are recorded for {season}; the full pool"
                     + (f" ({reported} players)" if reported else "") + " is not available, so unsold players are absent from this replay.")
    if any(f["purse_lakh"] is None for f in franchises.values()):
        notes.append("Pre-auction purse is unknown for some franchises; they cannot be simulated reliably.")
    return Context(key=f"season:{season}", label=f"IPL {season} auction", as_of=s.auction_date, rules=rules,
                   pool=pool, franchises=franchises, historical=True, notes=notes)


def _scenario_context(db: Session, scenario_id: str) -> Context:
    sc = db.get(AuctionScenario, scenario_id)
    if not sc:
        raise ValueError("Scenario not found")
    season_year = int(str(sc.season)[:4]) if str(sc.season)[:4].isdigit() else None
    cfg = db.get(AuctionSeason, season_year) if season_year else None
    rule = db.scalar(select(AuctionRule).where(AuctionRule.scenario_id == sc.id).order_by(AuctionRule.version.desc()))
    rj = rule.rules_json if rule else {}
    base_rules = _rules_from_season(cfg) if cfg else Rules(season_year, sc.auction_type, None, 18, 25, 8, 4, 30, False,
                                                            [[0, 5], [100, 10], [200, 20], [300, 25]])
    if rj.get("total_purse"):
        base_rules.purse_lakh = float(rj["total_purse"]) * 100
    for k_src, k_dst in (("maximum_squad_size", "max_squad"), ("minimum_squad_size", "min_squad"),
                         ("overseas_squad_limit", "max_overseas_squad"), ("overseas_xi_limit", "max_overseas_xi")):
        if rj.get(k_src) is not None:
            setattr(base_rules, k_dst, int(rj[k_src]))
    base_rules.provenance = {**base_rules.provenance, "scenario_rules_version": rule.version if rule else None}
    pool_rows = db.execute(select(AuctionPlayer, Player).join(Player, Player.id == AuctionPlayer.player_id)
                           .where(AuctionPlayer.scenario_id == sc.id)).all()
    teams = db.scalars(select(AuctionTeam).where(AuctionTeam.scenario_id == sc.id)).all()
    rets = db.execute(select(AuctionRetention, Player).join(Player, Player.id == AuctionRetention.player_id)
                      .where(AuctionRetention.scenario_id == sc.id)).all()
    ids = [p.id for _, p in pool_rows] + [p.id for _, p in rets]
    kinds, nat, roles = _bowling_kinds(db, ids), _nationality(db, ids), _roles_hist(db, ids)
    from app.auction.sources import normalize_role
    pool = []
    for ap, p in pool_rows:
        ov = ap.overseas_eligible if ap.overseas_eligible is not None else (
            (ap.nationality.strip().casefold() not in ("india", "indian")) if ap.nationality else nat.get(p.id))
        pool.append(_player_entry(p.id, p.canonical_name, normalize_role(ap.primary_role) or roles.get(p.id),
                                  kinds.get(p.id), ov, None, float(ap.base_price) * 100, ap.auction_category,
                                  ap.auction_order, ap.identity_match_status))
    pool.sort(key=lambda p: (p["lot_number"] is None, p["lot_number"] or 0, -(p["base_lakh"] or 0), p["name"]))
    # Missing uploaded retention prices are filled from sourced retention
    # records for the same season and player (never guessed).
    recorded = {}
    if season_year:
        for lot in db.scalars(select(AuctionLot).where(AuctionLot.season == season_year, AuctionLot.status == "RETAINED",
                                                       AuctionLot.player_id.in_([p.id for _, p in rets]))).all():
            if lot.final_price_lakh is not None:
                recorded[lot.player_id] = float(lot.final_price_lakh)
    franchises = {}
    filled_total = 0
    for t in teams:
        code = franchise_code(t.franchise_name) or franchise_code(t.franchise_code) or t.franchise_code[:8]
        squad = []
        for r, p in rets:
            if r.team_id != t.id:
                continue
            price = float(r.retention_price) if r.retention_price is not None else recorded.get(p.id)
            filled_total += int(r.retention_price is None and price is not None)
            squad.append(_player_entry(p.id, p.canonical_name, roles.get(p.id), kinds.get(p.id), nat.get(p.id),
                                       price_lakh=price, acquired="retained",
                                       price_source="upload" if r.retention_price is not None else
                                       ("recorded retention" if price is not None else None)))
        known = all(x["price_lakh"] is not None for x in squad)
        known_spend = sum(x["price_lakh"] for x in squad if x["price_lakh"] is not None)
        missing = sum(1 for x in squad if x["price_lakh"] is None)
        # Same purse rule as the original scenario analysis; when retention prices
        # are missing the result is labelled approximate rather than presented as exact.
        if t.initial_purse and float(t.initial_purse) > 0:
            purse = float(t.remaining_purse) * 100 - known_spend
            basis = "scenario_team" if not missing else f"approximate ({missing} retention prices missing)"
        elif base_rules.purse_lakh:
            purse = base_rules.purse_lakh - known_spend
            basis = "derived_from_retentions" if not missing else f"approximate ({missing} retention prices missing)"
        else:
            purse, basis = None, "unknown"
        franchises[code] = {"code": code, "name": FRANCHISE_NAMES.get(code, t.franchise_name), "purse_lakh": purse,
                            "purse_basis": basis, "squad": squad, "team_id": t.id}
    notes = []
    if filled_total:
        notes.append(f"{filled_total} retention prices missing from the upload were taken from sourced {season_year} retention records.")
    if any(f["purse_basis"].startswith("approximate") for f in franchises.values()):
        notes.append("Some retention prices are missing; those franchises' purse is approximate (season purse minus known retention prices).")
    if any(f["purse_basis"] == "unknown" for f in franchises.values()):
        notes.append("No season purse is configured for this scenario, so some franchises' purse is unknown.")
    return Context(key=f"scenario:{sc.id}", label=f"Scenario: {sc.name}", as_of=date.today(), rules=base_rules,
                   pool=pool, franchises=franchises, historical=False, notes=notes)


# ==========================================================================
# Models per context (leakage-free for replays)
# ==========================================================================

_CTX_MODELS: Dict[str, dict] = {}
_VALUATION_CACHE: Dict[str, dict] = {}


def models_for(db: Session, ctx: Context) -> dict:
    if not ctx.historical:
        prod = M.load_production(db)
        if prod is None:
            M.train_production(db)
            prod = M.load_production(db)
        frame = M.build_frame(db)
        train = frame[(frame.status == "SOLD") & frame.price_lakh.notna() & frame.purse_lakh.notna()
                      & (frame.verification != "conflict") & (frame.season >= M.MIN_TRAIN_SEASON)]
        perf = _cached(f"perf:prod:{prod['version']}", lambda: M.PriceModel(M.PERF_FEATURES).fit(train))
        return {"price": prod["price"], "perf": perf, "sale": prod["sale"], "version": prod["version"],
                "trained_on": "all recorded seasons", "train_seasons": sorted(int(s) for s in train.season.unique())}
    season = ctx.rules.season

    def fit():
        frame = M.build_frame(db)
        train = frame[(frame.status == "SOLD") & frame.price_lakh.notna() & frame.purse_lakh.notna()
                      & (frame.verification != "conflict") & (frame.season >= M.MIN_TRAIN_SEASON)
                      & (frame.season < season)]
        cls_train = frame[frame.status.isin(["SOLD", "UNSOLD"]) & (frame.season >= 2021) & (frame.season < season)]
        return {"price": M.PriceModel(M.ALL_FEATURES).fit(train), "perf": M.PriceModel(M.PERF_FEATURES).fit(train),
                "sale": M.fit_sale_classifier(cls_train), "version": f"replay-{season}-{M.FEATURE_VERSION}",
                "trained_on": f"seasons before {season} only",
                "train_seasons": sorted(int(s) for s in train.season.unique())}
    return _cached(f"replay:{season}", fit)


def _cached(key, fn):
    if key not in _CTX_MODELS:
        _CTX_MODELS[key] = fn()
    return _CTX_MODELS[key]


def invalidate_caches():
    _CTX_MODELS.clear()
    _VALUATION_CACHE.clear()


# ==========================================================================
# Quality, roles, valuation
# ==========================================================================

def _pct_rank(values: Dict[str, float], higher_better=True) -> Dict[str, float]:
    items = [(k, v) for k, v in values.items() if v is not None and not (isinstance(v, float) and math.isnan(v))]
    if not items:
        return {}
    ordered = sorted(v for _, v in items)
    n = len(ordered)
    out = {}
    for k, v in items:
        lo = sum(1 for x in ordered if x < v)
        eq = sum(1 for x in ordered if x == v)
        pr = (lo + 0.5 * eq) / n
        out[k] = 100 * (pr if higher_better else 1 - pr)
    return out


def quality_scores(features: Dict[str, dict]) -> Dict[str, dict]:
    """Cohort-relative batting/bowling quality (0-100) from shrunk, IPL-equivalent rates.

    Batting composite: strike rate, average, boundary %, (−)dot %.
    Bowling composite: phase-adjusted economy (economy vs the phase-mix
    expectation, so death specialists are not penalised for bowling at the
    death), strike rate and dot %.
    Players below a minimum evidence threshold get ``None`` for that discipline.
    """
    bat_ok = {p: f for p, f in features.items() if (f.get("bat_evidence_balls") or 0) >= 60}
    bowl_ok = {p: f for p, f in features.items() if (f.get("bowl_evidence_balls") or 0) >= 60}
    comps = {}
    sr = _pct_rank({p: f.get("bat_sr_eq") for p, f in bat_ok.items()})
    avg = _pct_rank({p: f.get("bat_avg_eq") for p, f in bat_ok.items()})
    bnd = _pct_rank({p: f.get("bat_boundary_pct") for p, f in bat_ok.items()})
    dot = _pct_rank({p: f.get("bat_dot_pct") for p, f in bat_ok.items()}, higher_better=False)
    phase_econ = {}
    for p, f in bowl_ok.items():
        shares = {"pp": f.get("bowl_pp_share") or 0, "death": f.get("bowl_death_share") or 0}
        shares["mid"] = max(0.0, 1 - shares["pp"] - shares["death"])
        actual = f.get("bowl_econ_eq")
        if actual is None:
            continue
        # Expected economy for this player's phase mix (IPL-scale phase priors approximated
        # from the cohort's phase economies).
        phase_econ[p] = (shares, actual)
    cohort_phase = {}
    for ph in ("pp", "mid", "death"):
        vals = [f.get(f"bowl_{ph}_econ") for f in bowl_ok.values() if f.get(f"bowl_{ph}_econ") is not None]
        cohort_phase[ph] = statistics.median(vals) if vals else None
    adj = {}
    for p, (shares, actual) in phase_econ.items():
        if all(cohort_phase.values()):
            expected = sum(shares[ph] * cohort_phase[ph] for ph in shares)
            adj[p] = expected - actual
    eco = _pct_rank(adj)
    bsr = _pct_rank({p: f.get("bowl_sr_eq") for p, f in bowl_ok.items()}, higher_better=False)
    bdot = _pct_rank({p: f.get("bowl_dot_pct") for p, f in bowl_ok.items()})
    for p in features:
        parts_bat = [(sr.get(p), .4), (avg.get(p), .3), (bnd.get(p), .2), (dot.get(p), .1)]
        parts_bowl = [(eco.get(p), .5), (bsr.get(p), .3), (bdot.get(p), .2)]
        comps[p] = {"bat": _weighted(parts_bat), "bowl": _weighted(parts_bowl)}
    return comps


def _weighted(parts):
    parts = [(v, w) for v, w in parts if v is not None]
    if not parts:
        return None
    return round(sum(v * w for v, w in parts) / sum(w for _, w in parts), 1)


def functional_tags(p: dict, f: dict) -> List[str]:
    tags = []
    role = p.get("role")
    if (f.get("bat_evidence_balls") or 0) >= 60:
        if (f.get("pos_top_share") or 0) >= 0.5:
            tags.append("top_order")
        elif (f.get("pos_lower_share") or 0) >= 0.35 or ((f.get("death_balls_share") or 0) >= 0.3 and role != "BOWL"):
            tags.append("finisher")
        elif role != "BOWL":
            tags.append("middle_order")
    elif role in ("BAT", "WK"):
        tags.append("batter_unproven")
    if role == "WK" or (f.get("stumpings_window") or 0) >= 2:
        tags.append("wicketkeeper")
    bowls = (f.get("bowl_evidence_balls") or 0) >= 60 or role in ("BOWL", "AR")
    if bowls:
        kind = p.get("bowling_kind")
        tags.append("pace" if kind == "pace" else "spin" if kind == "spin" else "bowler_type_unknown")
        if (f.get("bowl_death_share") or 0) >= 0.3 and (f.get("bowl_evidence_balls") or 0) >= 60:
            tags.append("death_bowler")
        if (f.get("bowl_pp_share") or 0) >= 0.35 and (f.get("bowl_evidence_balls") or 0) >= 60:
            tags.append("powerplay_bowler")
    if role == "AR" or ((f.get("bat_evidence_balls") or 0) >= 120 and (f.get("bowl_evidence_balls") or 0) >= 240):
        tags.append("all_rounder")
    return tags


def _lognorm_exceed(threshold, p10, p50, p90) -> Optional[float]:
    if not all(v and v > 0 for v in (threshold, p10, p50, p90)):
        return None
    sigma = max(1e-3, (math.log(p90) - math.log(p10)) / 2.5631)
    z = (math.log(threshold) - math.log(p50)) / sigma
    return 0.5 * math.erfc(z / math.sqrt(2))


def value_pool(db: Session, ctx: Context) -> dict:
    """Valuation for every player in the context pool (and squad members' qualities)."""
    cache_key = ctx.key
    if cache_key in _VALUATION_CACHE:
        return _VALUATION_CACHE[cache_key]
    models = models_for(db, ctx)
    squad_players = [x for f in ctx.franchises.values() for x in f["squad"]]
    everyone = ctx.pool + squad_players
    ids = [p["player_id"] for p in everyone if p.get("player_id")]
    feats = get_features(db, ids, ctx.as_of)
    q = quality_scores({pid: feats.get(pid, {}) for pid in ids})
    purse = ctx.rules.purse_lakh

    # Model frame for the pool.
    rows = []
    lots_prior = M._prior_prices(db.scalars(select(AuctionLot)).all())
    season_cfgs = {s.season: s for s in db.scalars(select(AuctionSeason)).all()}
    purse_by_season = {s: float(c.purse_lakh) for s, c in season_cfgs.items() if c.purse_lakh}
    season_for_prior = ctx.rules.season or (ctx.as_of.year + 1)
    for p in ctx.pool:
        f = feats.get(p["player_id"], {}) if p.get("player_id") else {}
        prior = lots_prior.get((p["player_id"], season_for_prior), {}) if p.get("player_id") else {}
        if not prior and p.get("player_id"):
            # Scenario seasons may be beyond recorded lots: use the latest earlier record.
            earlier = [k for k in lots_prior if k[0] == p["player_id"] and k[1] <= season_for_prior]
            prior = lots_prior.get(max(earlier, key=lambda k: k[1])) if earlier else {}
        ps, pr = (prior or {}).get("prior_sold"), (prior or {}).get("prior_retained")
        if ps and ps.season >= season_for_prior:
            ps = None
        if pr and pr.season >= season_for_prior:
            pr = None
        row = {k: (float(f[k]) if f.get(k) is not None else np.nan) for k in M.PERF_FEATURES}
        row.update({
            "purse_lakh": purse or np.nan, "base_lakh": p["base_lakh"] if p["base_lakh"] is not None else np.nan,
            "base_share": (p["base_lakh"] / purse) if purse and p["base_lakh"] else np.nan,
            "prior_price_share": float(ps.final_price_lakh) / purse_by_season[ps.season] if ps and purse_by_season.get(ps.season) else np.nan,
            "prior_retained_share": float(pr.final_price_lakh) / purse_by_season[pr.season] if pr and purse_by_season.get(pr.season) else np.nan,
            "seasons_since_prior": (season_for_prior - max(x.season for x in (ps, pr) if x)) if (ps or pr) else np.nan,
            "prior_count": float((prior or {}).get("count", 0)),
            "is_overseas": np.nan if p["overseas"] is None else float(p["overseas"]),
            "is_capped": np.nan if p.get("capped") is None else float(p["capped"]),
            "is_mega": float(ctx.rules.auction_type == "MEGA"),
            "is_marquee": float(bool(p.get("set_code") and str(p["set_code"]).upper().startswith("M") and str(p["set_code"])[1:].isdigit())),
            "is_pace": np.nan if not p.get("bowling_kind") else float(p["bowling_kind"] == "pace"),
            "is_spin": np.nan if not p.get("bowling_kind") else float(p["bowling_kind"] == "spin"),
            "market_liquidity": np.nan, "age_at_auction": np.nan,
        })
        for r in ("bat", "bowl", "ar", "wk"):
            row[f"role_{r}"] = np.nan if not p.get("role") else float(p["role"].lower() == r)
        rows.append(row)
    frame = pd.DataFrame(rows)
    if purse and not frame.empty:
        pred = models["price"].predict(frame)
        perf = models["perf"].predict(frame)
    else:
        pred = perf = pd.DataFrame({"p10": [np.nan] * len(frame), "p50": [np.nan] * len(frame), "p90": [np.nan] * len(frame)})
    sale_p = [None] * len(frame)
    sale_basis = "No sale classifier available for this context"
    pool_incomplete = ctx.historical and not any(p.get("actual_status") == "UNSOLD" for p in ctx.pool)
    if pool_incomplete:
        sale_basis = "Not estimated: the recorded pool for this auction contains sold players only"
    elif models.get("sale") is not None and not frame.empty:
        open_slots = sum(max(0, ctx.rules.max_squad - len(f["squad"])) for f in ctx.franchises.values())
        rate = min(0.95, open_slots / len(frame)) if len(frame) and open_slots else None
        sale_p = list(M.sale_probabilities(models["sale"], frame, rate))
        sale_basis = (f"Prior-shifted to {open_slots} open slots / {len(frame)} pool players" if rate else "Uncalibrated")

    # Tags, scarcity.
    players = []
    for i, p in enumerate(ctx.pool):
        pid = p.get("player_id")
        f = feats.get(pid, {}) if pid else {}
        qq = q.get(pid, {"bat": None, "bowl": None}) if pid else {"bat": None, "bowl": None}
        players.append({**p, "features": f, "bat_quality": qq["bat"], "bowl_quality": qq["bowl"],
                        "tags": functional_tags(p, f),
                        "p10": _f(pred["p10"].iloc[i]), "p50": _f(pred["p50"].iloc[i]), "p90": _f(pred["p90"].iloc[i]),
                        "market_value_lakh": _f(perf["p50"].iloc[i]),
                        "sale_probability": None if sale_p[i] is None else round(float(sale_p[i]), 3)})
    for pl in players:
        pl["quality"] = overall_quality(pl)
    _attach_scarcity(players)
    for pl in players:
        _attach_judgements(pl, ctx)
    squad_quality = {}
    for x in squad_players:
        pid = x.get("player_id")
        if pid:
            qq = q.get(pid, {"bat": None, "bowl": None})
            squad_quality[pid] = {"bat_quality": qq["bat"], "bowl_quality": qq["bowl"],
                                  "tags": functional_tags(x, feats.get(pid, {})), "features": feats.get(pid, {})}
    out = {"players": players, "squad_quality": squad_quality, "models": {
        k: v for k, v in models.items() if k in ("version", "trained_on", "train_seasons")}, "sale_basis": sale_basis}
    _VALUATION_CACHE[cache_key] = out
    return out


def _f(v):
    return None if v is None or (isinstance(v, float) and math.isnan(v)) else round(float(v), 1)


def overall_quality(p: dict) -> Optional[float]:
    bat, bowl, role = p.get("bat_quality"), p.get("bowl_quality"), p.get("role")
    if role in ("BAT", "WK"):
        return bat
    if role == "BOWL":
        return bowl
    if role == "AR":
        if bat is not None and bowl is not None:
            # An all-rounder is valued for both skills; a weak second skill
            # pulls the score down (no credit for token runs/wickets).
            return round(0.75 * (bat + bowl) / 2 + 0.25 * min(bat, bowl), 1)
        return round((bat if bat is not None else bowl) * 0.8, 1) if (bat is not None or bowl is not None) else None
    vals = [v for v in (bat, bowl) if v is not None]
    return max(vals) if vals else None


SCARCITY_GROUPS = {
    "Indian pace (death)": lambda p: p["overseas"] is False and "pace" in p["tags"] and "death_bowler" in p["tags"],
    "Indian pace": lambda p: p["overseas"] is False and "pace" in p["tags"],
    "Overseas pace": lambda p: p["overseas"] is True and "pace" in p["tags"],
    "Indian spin": lambda p: p["overseas"] is False and "spin" in p["tags"],
    "Overseas spin": lambda p: p["overseas"] is True and "spin" in p["tags"],
    "Indian wicketkeeper": lambda p: p["overseas"] is False and "wicketkeeper" in p["tags"],
    "Indian finisher": lambda p: p["overseas"] is False and "finisher" in p["tags"],
    "Overseas finisher": lambda p: p["overseas"] is True and "finisher" in p["tags"],
    "Indian top order": lambda p: p["overseas"] is False and "top_order" in p["tags"],
    "Overseas top order": lambda p: p["overseas"] is True and "top_order" in p["tags"],
    "Indian all-rounder": lambda p: p["overseas"] is False and "all_rounder" in p["tags"],
    "Overseas all-rounder": lambda p: p["overseas"] is True and "all_rounder" in p["tags"],
}


def _attach_scarcity(players: List[dict]):
    """Scarcity from the actual pool: how few comparable-or-better alternatives exist."""
    groups = {g: [p for p in players if fn(p)] for g, fn in SCARCITY_GROUPS.items()}
    for p in players:
        best = None
        for g, members in groups.items():
            if p not in members:
                continue
            q = p.get("quality")
            if q is None:
                alts = len(members) - 1
            else:
                alts = sum(1 for m in members if m is not p and m.get("quality") is not None and m["quality"] >= q - 5)
            score = round(100 / (1 + alts), 1)
            if best is None or score > best["score"]:
                best = {"group": g, "score": score, "comparable_alternatives": alts, "group_size": len(members)}
        p["scarcity"] = best


def _attach_judgements(p: dict, ctx: Context):
    f = p["features"]
    evidence = (f.get("bat_evidence_balls") or 0) + (f.get("bowl_evidence_balls") or 0)
    width = (p["p90"] / p["p10"]) if p.get("p10") and p.get("p90") else None
    missing = []
    if not p.get("player_id"):
        missing.append("player identity unresolved — no performance data linked")
    if evidence < 120:
        missing.append("little or no men's T20 evidence in the 3 years before the auction")
    if p.get("base_lakh") is None:
        missing.append("base price not recorded")
    if p.get("overseas") is None:
        missing.append("overseas/domestic status unknown")
    conf = "high" if evidence >= 600 and (f.get("ipl_bat_balls", 0) + f.get("ipl_bowl_balls", 0)) >= 200 and width and width < 6 \
        else "medium" if evidence >= 200 else "low"
    p["confidence"] = conf
    p["missing_information"] = missing
    p["evidence_balls"] = round(evidence, 0)
    p["bidding_war_probability"] = None
    if p.get("base_lakh") and p.get("p50"):
        pr = _lognorm_exceed(3 * p["base_lakh"], p["p10"], p["p50"], p["p90"])
        p["bidding_war_probability"] = None if pr is None else round(pr, 3)
    # Market premium: predicted auction price relative to performance-implied value.
    if p.get("p50") and p.get("market_value_lakh"):
        p["market_premium"] = round(p["p50"] / p["market_value_lakh"], 2)
    else:
        p["market_premium"] = None
    demand = p.get("bidding_war_probability")
    p["demand_level"] = None if demand is None else ("Very high" if demand >= .5 else "High" if demand >= .3
                                                      else "Moderate" if demand >= .12 else "Low")
    p["ipl_suitability"] = None if not f else round(min(100.0, 100 * (f.get("ipl_share_of_evidence") or 0) * 0.5
                                                         + min(50.0, (f.get("ipl_matches_career") or 0) / 2)), 1)
    p["recent_form"] = _recent_form(f)
    p["explanation"] = _explain(p)


def _recent_form(f: dict) -> Optional[float]:
    if not f or not f.get("days_since_t20") and f.get("days_since_t20") != 0:
        return None
    recency = max(0.0, 1 - (f.get("days_since_t20") or 0) / 730)
    return round(100 * recency, 1)


def _explain(p: dict) -> List[str]:
    f, out = p["features"], []
    if p.get("bat_quality") is not None:
        out.append(f"Batting quality {p['bat_quality']:.0f}/100 (IPL-equivalent SR {f.get('bat_sr_eq')}, avg {f.get('bat_avg_eq')}, "
                   f"{int(f.get('t20_bat_balls') or 0)} T20 balls faced in 3 yrs).")
    if p.get("bowl_quality") is not None:
        out.append(f"Bowling quality {p['bowl_quality']:.0f}/100 (economy {f.get('bowl_econ_eq')}, death share "
                   f"{f.get('bowl_death_share')}, {int(f.get('t20_bowl_balls') or 0)} T20 balls bowled).")
    if p.get("scarcity"):
        s = p["scarcity"]
        out.append(f"{s['group']}: {s['comparable_alternatives']} comparable-or-better alternatives in this pool.")
    if p.get("market_premium") is not None:
        out.append(f"Predicted price is {p['market_premium']:.2f}× the performance-implied value.")
    if f.get("ipl_matches_career") is not None:
        out.append(f"{f.get('ipl_matches_career')} IPL matches before the auction.")
    return out


# ==========================================================================
# Squad evaluation (best XI via MILP), needs, purse constraints
# ==========================================================================

def player_strength(x: dict, sq: Optional[dict] = None) -> Tuple[Optional[float], Optional[float], bool]:
    """(bat, bowl, assumed) — assumed=True when no evidence exists and a prior is used."""
    bat = (sq or x).get("bat_quality")
    bowl = (sq or x).get("bowl_quality")
    role = x.get("role")
    assumed = False
    if bat is None and bowl is None:
        assumed = True
        if role in ("BAT", "WK"):
            bat = ASSUMED_QUALITY
        elif role == "BOWL":
            bowl = ASSUMED_QUALITY
        elif role == "AR":
            bat = bowl = ASSUMED_QUALITY * 0.8
        else:
            bat = ASSUMED_QUALITY * 0.7
    return bat, bowl, assumed


def best_xi(members: List[dict], max_overseas: int) -> dict:
    """Maximise top-7 batting + top-5 bowling quality subject to 11 players,
    ≤ max_overseas overseas, ≥1 wicketkeeper (when the squad has one)."""
    n = len(members)
    if n == 0:
        return {"score": 0.0, "xi": [], "batting": 0.0, "bowling": 0.0, "feasible": False}
    bat = np.array([m["bat"] or 0.0 for m in members])
    bowl = np.array([m["bowl"] or 0.0 for m in members])
    can_bowl = np.array([1.0 if m["bowl"] is not None else 0.0 for m in members])
    ov = np.array([1.0 if m.get("overseas") else 0.0 for m in members])
    wk = np.array([1.0 if m.get("keeper") else 0.0 for m in members])
    size = min(11, n)
    nb, nw = min(7, size), min(5, int(can_bowl.sum()), size)
    # Variables: x (select), b (bat slot), w (bowl slot)
    c = -np.concatenate([np.zeros(n), bat, bowl])
    A, lb, ub = [], [], []
    eye = np.eye(n)
    z = np.zeros((n, n))
    A.append(np.hstack([-eye, eye, z])); lb += [-np.inf] * n; ub += [0] * n          # b <= x
    A.append(np.hstack([-eye, z, eye])); lb += [-np.inf] * n; ub += [0] * n          # w <= x
    A.append(np.hstack([z, z, eye * 0 + np.diag(1 - can_bowl)])); lb += [-np.inf] * n; ub += [0] * n  # non-bowlers can't fill bowl slots
    A.append(np.concatenate([np.ones(n), np.zeros(2 * n)])[None]); lb.append(size); ub.append(size)
    A.append(np.concatenate([np.zeros(n), np.ones(n), np.zeros(n)])[None]); lb.append(nb); ub.append(nb)
    A.append(np.concatenate([np.zeros(2 * n), np.ones(n)])[None]); lb.append(nw); ub.append(nw)
    A.append(np.concatenate([ov, np.zeros(2 * n)])[None]); lb.append(-np.inf); ub.append(max_overseas)
    if wk.sum() >= 1:
        A.append(np.concatenate([wk, np.zeros(2 * n)])[None]); lb.append(1); ub.append(np.inf)
    res = milp(c, constraints=LinearConstraint(np.vstack(A), lb, ub), integrality=np.ones(3 * n),
               bounds=Bounds(0, 1))
    if not res.success:
        return {"score": 0.0, "xi": [], "batting": 0.0, "bowling": 0.0, "feasible": False}
    x = res.x[:n] > 0.5
    b = res.x[n:2 * n] > 0.5
    w = res.x[2 * n:] > 0.5
    return {"score": round(float(-res.fun), 1), "batting": round(float(bat[b].sum()), 1),
            "bowling": round(float(bowl[w].sum()), 1), "feasible": True,
            "xi": [members[i]["player_id"] or members[i]["name"] for i in range(n) if x[i]],
            "bat_slots": [members[i]["name"] for i in range(n) if b[i]],
            "bowl_slots": [members[i]["name"] for i in range(n) if w[i]]}


def squad_members(squad: List[dict], qual: Dict[str, dict]) -> List[dict]:
    out = []
    for x in squad:
        sq = qual.get(x.get("player_id")) if x.get("player_id") else None
        bat, bowl, assumed = player_strength(x, sq)
        tags = (sq or {}).get("tags") or x.get("tags") or []
        out.append({"player_id": x.get("player_id"), "name": x["name"], "bat": bat, "bowl": bowl,
                    "overseas": x.get("overseas"), "keeper": "wicketkeeper" in tags or x.get("role") == "WK",
                    "tags": tags, "assumed": assumed, "role": x.get("role"),
                    "bowling_kind": x.get("bowling_kind"), "price_lakh": x.get("price_lakh")})
    return out


REQUIREMENT_GROUPS = [
    # key, label, matcher(member), xi_need, depth_need
    ("wicketkeeper", "Wicketkeeper", lambda m: m["keeper"], 1, 2),
    ("top_order", "Top-order batter", lambda m: "top_order" in m["tags"], 3, 4),
    ("middle_order", "Middle-order batter (4–5)", lambda m: "middle_order" in m["tags"], 2, 3),
    ("finisher", "Finisher", lambda m: "finisher" in m["tags"], 1, 2),
    ("pace", "Pace bowler", lambda m: "pace" in m["tags"], 3, 5),
    ("death_bowler", "Death-overs bowler", lambda m: "death_bowler" in m["tags"], 2, 3),
    ("powerplay_bowler", "Powerplay bowler", lambda m: "powerplay_bowler" in m["tags"], 2, 3),
    ("spin", "Spin bowler", lambda m: "spin" in m["tags"], 2, 3),
    ("all_rounder", "All-rounder", lambda m: "all_rounder" in m["tags"], 2, 3),
]


def derive_requirement_targets(db: Session, as_of: date) -> Dict[str, dict]:
    """Data-derived squad usage: median number of distinct players per role group
    used by IPL teams in the last three IPL seasons before ``as_of`` (≥3 appearances)."""
    rows = db.execute(text("""
        WITH bat AS (
          SELECT b.team_id, b.season, b.player_id,
                 COUNT(*) FILTER (WHERE b.batting_position <= 3) top_n,
                 COUNT(*) FILTER (WHERE b.batting_position BETWEEN 4 AND 5) mid_n,
                 COUNT(*) FILTER (WHERE b.batting_position BETWEEN 6 AND 8 AND b.balls >= 4) low_n
          FROM scouting_bat_innings b JOIN tournaments t ON t.id = b.tournament_id
          WHERE t.name = 'Indian Premier League' AND b.start_date < :as_of AND b.start_date >= :since
          GROUP BY 1, 2, 3),
        bowl AS (
          SELECT b.team_id, b.season, b.player_id, COUNT(*) n,
                 SUM(b.death_balls) death, SUM(b.pp_balls) pp, SUM(b.legal_balls) balls
          FROM scouting_bowl_innings b JOIN tournaments t ON t.id = b.tournament_id
          WHERE t.name = 'Indian Premier League' AND b.start_date < :as_of AND b.start_date >= :since
          GROUP BY 1, 2, 3)
        SELECT x.team_id, x.season,
               (SELECT COUNT(*) FROM bat WHERE bat.team_id = x.team_id AND bat.season = x.season AND top_n >= 3) top_order,
               (SELECT COUNT(*) FROM bat WHERE bat.team_id = x.team_id AND bat.season = x.season AND mid_n >= 3) middle_order,
               (SELECT COUNT(*) FROM bat WHERE bat.team_id = x.team_id AND bat.season = x.season AND low_n >= 3) finisher,
               (SELECT COUNT(*) FROM bowl WHERE bowl.team_id = x.team_id AND bowl.season = x.season AND n >= 3) bowlers,
               (SELECT COUNT(*) FROM bowl WHERE bowl.team_id = x.team_id AND bowl.season = x.season AND n >= 3 AND death >= 0.3 * balls) death_bowler,
               (SELECT COUNT(*) FROM bowl WHERE bowl.team_id = x.team_id AND bowl.season = x.season AND n >= 3 AND pp >= 0.35 * balls) powerplay_bowler
        FROM (SELECT DISTINCT team_id, season FROM bat) x
    """), {"as_of": as_of, "since": as_of - timedelta(days=int(365.25 * 3))}).mappings().all()
    targets = {}
    if rows:
        for key in ("top_order", "middle_order", "finisher", "death_bowler", "powerplay_bowler"):
            vals = [r[key] for r in rows]
            targets[key] = {"median_used": statistics.median(vals), "team_seasons": len(rows)}
        targets["bowlers"] = {"median_used": statistics.median([r["bowlers"] for r in rows]), "team_seasons": len(rows)}
    return targets


def derive_role_targets(db: Session, as_of: date) -> dict:
    """Median number of players per auction role (BAT/BOWL/AR/WK) that IPL teams
    used (≥3 appearances) per team-season in the three seasons before ``as_of``.
    Roles come from each player's most recent auction record; players with no
    recorded role are counted as 'unclassified' and excluded."""
    rows = db.execute(text("""
        WITH used AS (
          SELECT team_id, season, player_id FROM (
            SELECT b.team_id, b.season, b.player_id, b.match_id FROM scouting_bat_innings b
              JOIN tournaments t ON t.id = b.tournament_id
             WHERE t.name = 'Indian Premier League' AND b.start_date < :as_of AND b.start_date >= :since
            UNION
            SELECT b.team_id, b.season, b.player_id, b.match_id FROM scouting_bowl_innings b
              JOIN tournaments t ON t.id = b.tournament_id
             WHERE t.name = 'Indian Premier League' AND b.start_date < :as_of AND b.start_date >= :since) x
          GROUP BY 1, 2, 3 HAVING COUNT(DISTINCT match_id) >= 3),
        roles AS (
          SELECT DISTINCT ON (player_id) player_id, role FROM auction_lots
           WHERE player_id IS NOT NULL AND role IS NOT NULL ORDER BY player_id, season DESC)
        SELECT u.team_id, u.season, r.role, COUNT(*) n
        FROM used u LEFT JOIN roles r ON r.player_id = u.player_id GROUP BY 1, 2, 3
    """), {"as_of": as_of, "since": as_of - timedelta(days=int(365.25 * 3))}).mappings().all()
    by_ts = defaultdict(dict)
    for r in rows:
        by_ts[(r["team_id"], r["season"])][r["role"]] = r["n"]
    if not by_ts:
        return {}
    targets = {}
    for role in ("BAT", "BOWL", "AR", "WK"):
        targets[role] = max(1, int(round(statistics.median([d.get(role, 0) for d in by_ts.values()]))))
    unclassified = statistics.median([d.get(None, 0) for d in by_ts.values()])
    return {"targets": targets, "team_seasons": len(by_ts),
            "basis": f"median players used per IPL team-season ({len(by_ts)} team-seasons, 3 seasons before {as_of}); "
                     f"median {unclassified:g} used players per team had no recorded auction role"}


def squad_needs(members: List[dict], targets: Dict[str, dict], max_overseas_squad: int, max_squad: int) -> List[dict]:
    needs = []
    for key, label, match, xi_need, depth_need in REQUIREMENT_GROUPS:
        observed = targets.get(key, {}).get("median_used")
        target = max(xi_need, int(round(observed))) if observed else depth_need
        if key in ("pace", "spin") and targets.get("bowlers"):
            # Split the observed bowler usage between pace/spin by XI need.
            target = max(xi_need, depth_need)
        capable = [m for m in members if match(m)]
        skill = "bowl" if key in ("pace", "spin", "death_bowler", "powerplay_bowler") else "bat"
        strong = [m for m in capable if not m["assumed"] and (m[skill] or 0) >= 55]
        gap = max(0, target - len(capable))
        if len(capable) < xi_need:
            priority = "Critical"
            reason = f"Only {len(capable)} {label.lower()} option(s) for {xi_need} XI place(s)."
        elif len(strong) < xi_need:
            priority = "High"
            reason = f"{len(capable)} option(s), but only {len(strong)} rated 55+ for {xi_need} XI place(s)."
        elif gap > 0:
            priority = "Medium"
            reason = f"{len(capable)} option(s); teams typically use {target}. Depth needed."
        else:
            priority = "Low"
            reason = f"{len(capable)} option(s) — covered."
        needs.append({"key": key, "label": label, "priority": priority, "reason": reason, "have": len(capable),
                      "strong": len(strong), "target": target, "gap": gap,
                      "target_basis": (f"median used by IPL teams ({targets[key]['team_seasons']} team-seasons, last 3 seasons)"
                                       if key in targets else "XI requirement + one backup")})
    order = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
    needs.sort(key=lambda n: (order[n["priority"]], -n["gap"]))
    return needs


def purse_constraints(purse_lakh: Optional[float], squad_size: int, overseas: int, rules: Rules) -> dict:
    if purse_lakh is None:
        return {"known": False}
    slots = max(0, rules.max_squad - squad_size)
    min_needed = max(0, rules.min_squad - squad_size)
    # To complete the minimum squad every remaining compulsory slot must be filled at least at the minimum base price.
    reserve = max(0, min_needed - 1) * rules.min_base_price_lakh
    max_bid = max(0.0, purse_lakh - reserve) if slots > 0 else 0.0
    return {"known": True, "purse_lakh": round(purse_lakh, 2), "slots_left": slots, "min_slots_to_fill": min_needed,
            "overseas_slots_left": max(0, rules.max_overseas_squad - overseas),
            "avg_per_slot_lakh": round(purse_lakh / slots, 2) if slots else None,
            "minimum_reserve_lakh": reserve, "max_theoretical_bid_lakh": round(max_bid, 2)}


# ==========================================================================
# Franchise behaviour (history)
# ==========================================================================

def franchise_behaviour(db: Session, before_season: Optional[int] = None) -> Dict[str, dict]:
    q = select(AuctionLot).where(AuctionLot.status == "SOLD", AuctionLot.acquisition_type == "auction",
                                 AuctionLot.final_price_lakh.is_not(None), AuctionLot.verification != "conflict")
    if before_season:
        q = q.where(AuctionLot.season < before_season)
    lots = db.scalars(q).all()
    seasons = {s.season: float(s.purse_lakh) for s in db.scalars(select(AuctionSeason)).all() if s.purse_lakh}
    lots = [l for l in lots if l.season in seasons and l.franchise]
    league = defaultdict(list)
    for l in lots:
        league["share"].append(float(l.final_price_lakh) / seasons[l.season])
    league_os = sum(1 for l in lots if l.overseas) / max(1, sum(1 for l in lots if l.overseas is not None))
    league_war = [float(l.final_price_lakh) / float(l.base_price_lakh) >= 3 for l in lots if l.base_price_lakh]
    league_war_rate = sum(league_war) / len(league_war) if league_war else None
    out = {}
    for fr in sorted({l.franchise for l in lots}):
        mine = [l for l in lots if l.franchise == fr]
        n_seasons = len({l.season for l in mine})
        shares = [float(l.final_price_lakh) / seasons[l.season] for l in mine]
        by_role = defaultdict(float)
        for l in mine:
            by_role[l.role or "Unknown"] += float(l.final_price_lakh) / seasons[l.season]
        total = sum(by_role.values()) or 1
        os_known = [l for l in mine if l.overseas is not None]
        os_rate = sum(1 for l in os_known if l.overseas) / len(os_known) if os_known else None
        wars = [float(l.final_price_lakh) / float(l.base_price_lakh) >= 3 for l in mine if l.base_price_lakh]
        top = sorted(mine, key=lambda l: -float(l.final_price_lakh))[:5]
        tendencies = []
        sufficient = len(mine) >= 40 and n_seasons >= 4
        if sufficient and os_rate is not None and league_os:
            z = (os_rate - league_os) / math.sqrt(league_os * (1 - league_os) / len(os_known))
            if abs(z) >= 2:
                tendencies.append({"tendency": f"{'More' if z > 0 else 'Less'} overseas-focused buying than the league "
                                               f"({os_rate:.0%} vs {league_os:.0%} of purchases)", "z": round(z, 2)})
        mean_share = statistics.mean(shares) if shares else None
        league_mean = statistics.mean(league["share"]) if league["share"] else None
        if sufficient and mean_share and league_mean and len(shares) > 1:
            se = statistics.pstdev(league["share"]) / math.sqrt(len(shares))
            z = (mean_share - league_mean) / se if se else 0
            if abs(z) >= 2:
                tendencies.append({"tendency": f"{'Higher' if z > 0 else 'Lower'} average spend per purchase than the league",
                                   "z": round(z, 2)})
        if sufficient and wars and league_war_rate:
            rate = sum(wars) / len(wars)
            z = (rate - league_war_rate) / math.sqrt(league_war_rate * (1 - league_war_rate) / len(wars))
            if abs(z) >= 2:
                tendencies.append({"tendency": f"{'More' if z > 0 else 'Fewer'} bidding-war buys (≥3× base) than the league",
                                   "z": round(z, 2)})
        out[fr] = {
            "franchise": fr, "name": FRANCHISE_NAMES.get(fr, fr), "purchases": len(mine), "seasons": n_seasons,
            "avg_price_share_of_purse": round(mean_share, 4) if mean_share else None,
            "avg_price_lakh_recent": round(statistics.mean([float(l.final_price_lakh) for l in mine if l.season >= 2022]), 1)
            if any(l.season >= 2022 for l in mine) else None,
            "spend_share_by_role": {k: round(v / total, 3) for k, v in sorted(by_role.items())},
            "overseas_purchase_rate": round(os_rate, 3) if os_rate is not None else None,
            "bidding_war_rate": round(sum(wars) / len(wars), 3) if wars else None, "bidding_war_sample": len(wars),
            "biggest_purchases": [{"season": l.season, "player": l.player_name, "price_lakh": float(l.final_price_lakh),
                                   "role": l.role} for l in top],
            "tendencies": tendencies,
            "evidence": ("sufficient" if sufficient else "insufficient — observations only, no tendencies inferred"),
            # Aggression multiplier for the simulator: only when statistically supported.
            "aggression": round(1 + 0.1 * max(-1.0, min(1.0, next((t["z"] for t in tendencies if "spend per purchase" in t["tendency"]), 0) / 3)), 3),
        }
    return out
