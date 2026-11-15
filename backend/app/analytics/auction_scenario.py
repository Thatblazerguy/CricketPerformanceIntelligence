"""Scenario analysis: team needs and franchise-specific auction bid estimates.

``run_scenario`` keeps its original response shape (teams → needs and
recommendations; player_predictions with competition-adjusted closes) but is
now computed from the shared Auction Intelligence foundation:

* prices: the version-2 price model (``app.ml.auction_price``) — p10/p50/p90;
* squad state, best XI, functional needs and marginal value:
  ``app.auction.market`` / ``app.auction.optimizer``;
* role targets: derived from how many players per role IPL teams actually
  used in the last three seasons (``market.derive_role_targets``) instead of the
  former fixed 6/6/4/2 template, which remains only as a fallback when no IPL
  usage data exists; explicit ``role_targets`` in scenario rules still win;
* competition: the existing ``demand_score``, ``team_willingness_lakh`` and
  ``competition_adjusted_price`` helpers.
"""
from collections import Counter, defaultdict

import numpy as np
from sqlalchemy import select

from app.ml.auction_price import role_key
from app.analytics.auction_competition import competition_adjusted_price, demand_score, team_willingness_lakh
from app.models.models import (
    AuctionHistoryRecord, AuctionModelRun, AuctionPlayer, AuctionRetention, AuctionRule, AuctionTeam,
)

DEFAULT_ROLE_TARGETS = {"Batter": 6, "Bowler": 6, "All-Rounder": 4, "Wicketkeeper": 2}
SERIOUS_BIDDER_DEMAND_THRESHOLD = 20.0


def role_needs(retained_roles, targets=None):
    targets = targets or DEFAULT_ROLE_TARGETS
    gaps = {role: max(0, int(target) - int(retained_roles.get(role, 0)))
            for role, target in targets.items() if int(target) > 0}
    return {role: gap for role, gap in gaps.items() if gap > 0}


def _role_markup_priors(db, year):
    rows = db.scalars(select(AuctionHistoryRecord).where(
        AuctionHistoryRecord.auction_year < year,
        AuctionHistoryRecord.status == "SOLD",
        AuctionHistoryRecord.acquisition_type == "auction",
        AuctionHistoryRecord.final_price_lakh.is_not(None),
        AuctionHistoryRecord.base_price_lakh.is_not(None),
        AuctionHistoryRecord.base_price_lakh > 0,
    )).all()
    by_role, all_markups = defaultdict(list), []
    for row in rows:
        markup = max(0.0, float(row.final_price_lakh) / float(row.base_price_lakh) - 1.0)
        if markup > 0:
            all_markups.append(markup)
        key = role_key(row.role)
        if key != "Unknown" and markup > 0:
            by_role[key].append(markup)
    def robust(values):
        # Positive sale premiums capture observed bidding beyond reserve/base.
        # Log compression keeps unusually large reserve-price multiples from
        # dominating estimates while retaining their direction and rank.
        return float(np.log1p(np.median(values))) if len(values) >= 5 else None
    overall = robust(all_markups) or 0.0
    return {role: robust(values) if robust(values) is not None else overall for role, values in by_role.items()}, overall


ROLE_NAMES = {"BAT": "Batter", "BOWL": "Bowler", "AR": "All-Rounder", "WK": "Wicketkeeper"}


def run_scenario(db, scenario):
    from app.auction import market as mk, optimizer as op
    from app.ml import auction_price as M

    teams = db.scalars(select(AuctionTeam).where(AuctionTeam.scenario_id == scenario.id)).all()
    retentions = db.scalars(select(AuctionRetention).where(AuctionRetention.scenario_id == scenario.id)).all()
    pool_count = db.scalar(select(AuctionPlayer.id).where(AuctionPlayer.scenario_id == scenario.id,
                                                          AuctionPlayer.availability_status == "AVAILABLE").limit(1))
    if not teams or not retentions:
        return {"ready": False, "message": "Import the full retention-list CSV before running the scenario.",
                "teams": [], "model": None}
    if not pool_count:
        return {"ready": False, "message": "Import the player-pool CSV before running the scenario.",
                "teams": [], "model": None}
    if M.load_production(db) is None:
        return {"ready": False, "message": "Train the auction price model (Train from history) before running this scenario.",
                "teams": [], "model": None}

    key = f"scenario:{scenario.id}"
    mk._VALUATION_CACHE.pop(key, None)  # scenario uploads change between runs
    ctx = mk.build_context(db, key)
    available = {p.player_id for p in db.scalars(select(AuctionPlayer).where(
        AuctionPlayer.scenario_id == scenario.id, AuctionPlayer.availability_status == "AVAILABLE")).all()}
    val = mk.value_pool(db, ctx)
    pool = [p for p in val["players"] if p.get("player_id") in available]
    rule = db.scalar(select(AuctionRule).where(AuctionRule.scenario_id == scenario.id).order_by(AuctionRule.version.desc()))
    rules = rule.rules_json if rule else {}
    if rules.get("role_targets"):
        targets = {role_key(r): int(t) for r, t in rules["role_targets"].items() if int(t) > 0}
        target_basis = "scenario rules"
    else:
        derived = mk.derive_role_targets(db, ctx.as_of)
        targets = {ROLE_NAMES[k]: v for k, v in derived.get("targets", {}).items()} or dict(DEFAULT_ROLE_TARGETS)
        target_basis = derived.get("basis") or "fallback template (no IPL usage data before this date)"
    functional_targets = mk.derive_requirement_targets(db, ctx.as_of)
    year = int(str(scenario.season)[:4]) if str(scenario.season)[:4].isdigit() else ctx.as_of.year + 1
    role_markups, overall_markup = _role_markup_priors(db, year)
    backtest = db.scalar(select(AuctionModelRun).where(AuctionModelRun.task == "v2_backtest")
                         .order_by(AuctionModelRun.created_at.desc()))
    mae_lakh = float((((backtest.evaluation_json or {}).get("pooled") or {}).get("cpi") or {}).get("mae_lakh") or 0) if backtest else 0.0

    states, output_teams = {}, []
    for code, fr in sorted(ctx.franchises.items(), key=lambda kv: kv[1]["name"]):
        st = op.franchise_state(ctx, val, code, targets=functional_targets)
        states[code] = st
        role_counts = Counter(ROLE_NAMES.get(m["role"], "Unknown") for m in st["members"])
        gaps = role_needs(role_counts, targets)
        purse = st["purse"]
        output_teams.append({
            "team_id": fr.get("team_id"), "franchise": fr["name"], "franchise_code": code,
            "retained_count": len(fr["squad"]), "retained_role_counts": dict(role_counts),
            "needs": [{"role": r, "target": targets[r], "retained": role_counts.get(r, 0), "players_needed": g}
                      for r, g in sorted(gaps.items(), key=lambda kv: -kv[1])],
            "squad_requirements": st["needs"],
            "remaining_purse_cr": round(purse["purse_lakh"] / 100.0, 2) if purse.get("known") else None,
            "purse_basis": fr["purse_basis"],
            "squad_slots_remaining": purse.get("slots_left"),
            "overseas_slots_remaining": purse.get("overseas_slots_left"),
            "max_bid_cr": round(purse["max_theoretical_bid_lakh"] / 100.0, 2) if purse.get("known") else None,
            "best_xi_score": st["xi"]["score"],
            "recommendations": [],
        })
    team_out = {t["franchise_code"]: t for t in output_teams}

    output_players = []
    minimum_increment_lakh = float(rules.get("minimum_bid_increment", 0.2)) * 100.0
    for p in pool:
        base = p.get("base_lakh") or ctx.rules.min_base_price_lakh
        anchor = p.get("p50") or base
        role_name = ROLE_NAMES.get(p.get("role"), "Unknown")
        bidders = []
        for code, st in states.items():
            purse = st["purse"]
            if not purse.get("known") or purse["slots_left"] <= 0:
                continue
            if p.get("overseas") and purse["overseas_slots_left"] <= 0:
                continue
            mv = op.marginal_value(st, p, ctx.rules.max_overseas_xi)
            need = max(0.0, min(1.6, mv["total"] / 45.0))
            gaps = role_needs(Counter(ROLE_NAMES.get(m["role"], "Unknown") for m in st["members"]), targets)
            score, reasons = demand_score(gaps.get(role_name, 0), targets.get(role_name, 1), p.get("quality"),
                                          purse["purse_lakh"], anchor, base, purse["slots_left"],
                                          purse["overseas_slots_left"], bool(p.get("overseas")))
            # Functional fit (best-XI improvement) can create demand even when the
            # coarse role count is already met, e.g. a death bowler for a weak attack.
            score = round(max(score, 100.0 * min(1.0, need)), 1) if need >= 0.1 else score
            if score <= 0:
                continue
            willingness = team_willingness_lakh(anchor * (0.55 + 0.75 * need), base, purse["max_theoretical_bid_lakh"])
            reasons = reasons + [f"Best-XI change {mv['xi_delta']:+.1f}"] + \
                [f"Fills {f['need']} ({f['priority']})" for f in mv["fills"]]
            bidders.append({"code": code, "team_id": team_out[code]["team_id"], "franchise": team_out[code]["franchise"],
                            "demand_score": score, "need": need, "willingness_lakh": willingness, "reasons": reasons,
                            "marginal": mv})
        serious = [b for b in bidders if b["demand_score"] >= SERIOUS_BIDDER_DEMAND_THRESHOLD]
        alternatives = (p.get("scarcity") or {}).get("comparable_alternatives", 0)
        price = competition_adjusted_price(base, anchor, [b["willingness_lakh"] for b in serious], alternatives,
                                           role_markups.get(role_key(p.get("role")), overall_markup), mae_lakh)
        if len(serious) >= 2:
            vals = sorted((b["willingness_lakh"] for b in serious), reverse=True)
            price["expected_lakh"] = round(min(vals[0], max(price["expected_lakh"], vals[1] + minimum_increment_lakh)), 2)
            price["low_lakh"] = round(max(base, min(price["low_lakh"], price["expected_lakh"])), 2)
            price["high_lakh"] = round(max(price["high_lakh"], price["expected_lakh"]), 2)
        if p.get("p90"):
            # The v2 model is trained on competitive sale prices, so competition is
            # already inside its range; the adjustment may move within it, not beyond.
            price["expected_lakh"] = round(min(price["expected_lakh"], p["p90"]), 2)
            price["low_lakh"] = round(min(price["low_lakh"], price["expected_lakh"]), 2)
            price["high_lakh"] = round(max(min(price["high_lakh"], p["p90"]), price["expected_lakh"]), 2)
        serious.sort(key=lambda b: (-b["demand_score"], -b["willingness_lakh"], b["franchise"]))
        output_players.append({
            "player_id": p["player_id"], "player_name": p["name"], "role": role_name,
            "base_price_cr": round(base / 100.0, 2),
            "individual_valuation_cr": round(anchor / 100.0, 2),
            "model_range_cr": {"p10": _cr(p.get("p10")), "p50": _cr(p.get("p50")), "p90": _cr(p.get("p90"))},
            "market_value_cr": _cr(p.get("market_value_lakh")),
            "predicted_final_price_lakh": price["expected_lakh"],
            "predicted_final_price_cr": round(price["expected_lakh"] / 100.0, 2),
            "confidence_interval_lakh": {"low": price["low_lakh"], "high": price["high_lakh"]},
            "confidence_interval_cr": {"low": round(price["low_lakh"] / 100.0, 2), "high": round(price["high_lakh"] / 100.0, 2)},
            "confidence": p.get("confidence"), "quality": p.get("quality"), "tags": p.get("tags"),
            "realistic_competing_franchises": len(serious),
            "demand_score": round(min(100.0, sum(b["demand_score"] for b in serious)), 1),
            "scarcity_score": price["scarcity_score"], "scarcity_group": (p.get("scarcity") or {}).get("group"),
            "comparable_alternatives": price["comparable_alternatives"],
            "competition_level": price["competition_level"], "competition_pressure": price["competition_pressure"],
            "bidding_war_probability": p.get("bidding_war_probability"), "sale_probability": p.get("sale_probability"),
            "most_likely_competitors": [{"team_id": b["team_id"], "franchise": b["franchise"],
                                         "demand_score": b["demand_score"], "role_gap": None,
                                         "willingness_to_pay_cr": round(b["willingness_lakh"] / 100.0, 2),
                                         "reasons": b["reasons"]} for b in serious[:5]],
            "price_basis": "Version-2 model price adjusted for feasible bidder competition, functional squad need and comparable-player scarcity.",
            "quality_sample": f"{int(p.get('evidence_balls') or 0)} IPL-equivalent T20 balls" if p.get("quality") is not None else "insufficient T20 sample",
            "recent_form": {"sample_matches": None, "assessment": "; ".join(p.get("explanation") or []) or "Insufficient recent match data",
                            "features": {}, "influenced_price_model": True},
        })
        for b in bidders:
            team_out[b["code"]]["recommendations"].append({
                "player_id": p["player_id"], "player_name": p["name"], "role": role_name,
                "base_price_cr": round(base / 100.0, 2),
                "estimated_bid_lakh": b["willingness_lakh"], "estimated_bid_cr": round(b["willingness_lakh"] / 100.0, 2),
                "estimated_team_willingness_cr": round(b["willingness_lakh"] / 100.0, 2),
                "need_priority": b["demand_score"], "demand_score": b["demand_score"],
                "squad_improvement": b["marginal"]["total"], "fills": b["marginal"]["fills"],
                "confidence": p.get("confidence"), "historical_team_sales": None,
                "price_basis": "Model price scaled by this franchise's best-XI improvement and depth needs, capped by its legal maximum bid.",
                "demand_reasons": b["reasons"],
            })
    for t in output_teams:
        t["recommendations"].sort(key=lambda x: (-x["need_priority"], -x["estimated_team_willingness_cr"], x["player_name"]))
        t["recommendations"] = t["recommendations"][:10]
    output_players.sort(key=lambda x: (-x["realistic_competing_franchises"], -x["demand_score"], -x["predicted_final_price_lakh"]))
    return {
        "ready": True,
        "scenario": {"id": scenario.id, "name": scenario.name, "season": scenario.season},
        "model": {"version": val["models"].get("version"), "holdout_mae_lakh": mae_lakh or None,
                  "holdout_start_year": None, "evaluation": "rolling-origin backtest (see Backtesting)"},
        "assumptions": {
            "role_targets": targets, "role_target_basis": target_basis,
            "target_note": f"Role targets: {target_basis}. Override with role_targets in the scenario rules.",
            "price_note": "Version-2 price model (quantile gradient boosting on pre-auction features) with an 80% range; "
                          "expected closes add feasible bidder competition from each franchise's best-XI improvement and purse.",
            "price_unit": "INR crore and lakh",
            "context_notes": ctx.notes,
        },
        "teams": output_teams,
        "player_predictions": output_players,
    }


def _cr(lakh):
    return round(float(lakh) / 100.0, 2) if lakh is not None else None
