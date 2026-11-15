"""Opportunity cost, marginal squad value and purse-allocation optimisation.

Marginal value
    ΔXI = best-XI score(squad + player) − best-XI score(squad), where the best
    XI is the MILP in ``market.best_xi`` (top-7 batting + top-5 bowling quality,
    overseas cap, a keeper). A player who only duplicates an existing strength
    adds little ΔXI; one who fills a hole adds a lot. Depth credit is added
    for unmet squad needs beyond the XI.

Purse allocation
    A single MILP chooses purchases from the remaining pool *together with*
    the resulting XI, so diminishing returns are exact rather than assumed:

        maximise   XI(squad ∪ bought) + 0.3·depth(bought) − ε·cost
        subject to Σ cost·buy ≤ purse;  squad size ≥ min and ≤ max;
                   overseas in squad ≤ cap;  XI: 11 players, 7 bat slots,
                   5 bowling slots (bowlers only), ≤ overseas XI cap, ≥1 keeper.

    Costs are the model's p50 (or p75 for a conservative plan). Monte Carlo
    re-solves under price draws from each player's predicted range to report
    how robust each recommendation is and a budget range per role.
"""
from __future__ import annotations

import math
import random
from collections import defaultdict
from typing import Dict, List, Optional

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp

from app.auction import market as mk

DEPTH_WEIGHT = 0.3
PRIORITY_WEIGHT = {"Critical": 1.0, "High": 0.7, "Medium": 0.4, "Low": 0.0}


def franchise_state(ctx: mk.Context, val: dict, code: str, squad: Optional[List[dict]] = None,
                    purse_lakh: Optional[float] = None, targets: Optional[dict] = None) -> dict:
    f = ctx.franchises[code]
    squad = f["squad"] if squad is None else squad
    purse = f["purse_lakh"] if purse_lakh is None else purse_lakh
    members = mk.squad_members(squad, val["squad_quality"] | {p["player_id"]: p for p in val["players"] if p.get("player_id")})
    xi = mk.best_xi(members, ctx.rules.max_overseas_xi)
    needs = mk.squad_needs(members, targets or {}, ctx.rules.max_overseas_squad, ctx.rules.max_squad)
    overseas = sum(1 for m in members if m["overseas"])
    return {"code": code, "name": f["name"], "members": members, "xi": xi, "needs": needs,
            "purse": mk.purse_constraints(purse, len(members), overseas, ctx.rules), "overseas": overseas,
            "purse_basis": f["purse_basis"], "targets": targets or {}}


def member_from_player(p: dict) -> dict:
    bat, bowl, assumed = mk.player_strength(p)
    return {"player_id": p.get("player_id"), "name": p["name"], "bat": bat, "bowl": bowl,
            "overseas": p.get("overseas"), "keeper": "wicketkeeper" in (p.get("tags") or []) or p.get("role") == "WK",
            "tags": p.get("tags") or [], "assumed": assumed, "role": p.get("role"),
            "bowling_kind": p.get("bowling_kind"), "price_lakh": None}


def marginal_value(state: dict, player: dict, max_overseas_xi: int) -> dict:
    m = member_from_player(player)
    after = mk.best_xi(state["members"] + [m], max_overseas_xi)
    delta = round(after["score"] - state["xi"]["score"], 1)
    depth, filled = 0.0, []
    for need in state["needs"]:
        match = next((g[2] for g in mk.REQUIREMENT_GROUPS if g[0] == need["key"]), None)
        if match and match(m) and need["gap"] > 0:
            w = PRIORITY_WEIGHT[need["priority"]]
            if w:
                skill = m["bowl"] if need["key"] in ("pace", "spin", "death_bowler", "powerplay_bowler") else m["bat"]
                depth += w * DEPTH_WEIGHT * (skill or 0)
                filled.append({"need": need["label"], "priority": need["priority"]})
    return {"xi_delta": delta, "depth_value": round(depth, 1), "total": round(delta + depth, 1),
            "fills": filled, "would_start": (player.get("player_id") or player["name"]) in after["xi"]}


def _solve(state: dict, candidates: List[dict], costs: np.ndarray, rules: mk.Rules, objective_eps: float = 1e-4):
    squad = state["members"]
    cand = [member_from_player(p) for p in candidates]
    allm = squad + cand
    ns, nc = len(squad), len(cand)
    n = ns + nc
    if nc == 0:
        return None
    purse = state["purse"]["purse_lakh"]
    slots = state["purse"]["slots_left"]
    min_fill = state["purse"]["min_slots_to_fill"]
    os_left = state["purse"]["overseas_slots_left"]
    bat = np.array([m["bat"] or 0.0 for m in allm])
    bowl = np.array([m["bowl"] or 0.0 for m in allm])
    can_bowl = np.array([1.0 if m["bowl"] is not None else 0.0 for m in allm])
    ov = np.array([1.0 if m["overseas"] else 0.0 for m in allm])
    wk = np.array([1.0 if m["keeper"] else 0.0 for m in allm])
    # Depth credit per candidate for open needs (capped per need via group variables would be
    # heavier; a per-need cap is enforced below with aggregated constraints).
    need_groups = [(n_, next(g[2] for g in mk.REQUIREMENT_GROUPS if g[0] == n_["key"]))
                   for n_ in state["needs"] if n_["gap"] > 0 and PRIORITY_WEIGHT[n_["priority"]] > 0]
    G = len(need_groups)
    # Variables: y (buy, nc) | x (XI, n) | b (bat slot, n) | w (bowl slot, n) | d (depth, G*nc)
    nv = nc + 3 * n + G * nc
    c = np.zeros(nv)
    c[nc + n: nc + 2 * n] = -bat
    c[nc + 2 * n: nc + 3 * n] = -bowl
    c[:nc] = objective_eps * costs
    for gi, (need, match) in enumerate(need_groups):
        wgt = PRIORITY_WEIGHT[need["priority"]] * DEPTH_WEIGHT
        skill_key = "bowl" if need["key"] in ("pace", "spin", "death_bowler", "powerplay_bowler") else "bat"
        for j, m in enumerate(cand):
            if match(m):
                c[nc + 3 * n + gi * nc + j] = -wgt * (m[skill_key] or 0)
    rows, lo, hi = [], [], []

    def row():
        return np.zeros(nv)
    # Budget and squad size.
    r = row(); r[:nc] = costs; rows.append(r); lo.append(-np.inf); hi.append(purse)
    r = row(); r[:nc] = 1; rows.append(r); lo.append(min(min_fill, nc)); hi.append(slots)
    r = row(); r[:nc] = ov[ns:]; rows.append(r); lo.append(-np.inf); hi.append(os_left)
    # XI selection over squad ∪ bought.
    for j in range(nc):  # x_cand <= y
        r = row(); r[nc + ns + j] = 1; r[j] = -1; rows.append(r); lo.append(-np.inf); hi.append(0)
    for i in range(n):
        r = row(); r[nc + n + i] = 1; r[nc + i] = -1; rows.append(r); lo.append(-np.inf); hi.append(0)
        r = row(); r[nc + 2 * n + i] = 1; r[nc + i] = -1; rows.append(r); lo.append(-np.inf); hi.append(0)
        if not can_bowl[i]:
            r = row(); r[nc + 2 * n + i] = 1; rows.append(r); lo.append(-np.inf); hi.append(0)
    size = 11
    r = row(); r[nc:nc + n] = 1; rows.append(r); lo.append(min(size, ns)); hi.append(size)
    r = row(); r[nc + n:nc + 2 * n] = 1; rows.append(r); lo.append(-np.inf); hi.append(7)
    r = row(); r[nc + 2 * n:nc + 3 * n] = 1; rows.append(r); lo.append(-np.inf); hi.append(5)
    r = row(); r[nc:nc + n] = ov; rows.append(r); lo.append(-np.inf); hi.append(rules.max_overseas_xi)
    if wk.sum() >= 1:
        r = row(); r[nc:nc + n] = wk; rows.append(r); lo.append(1 if wk[:ns].sum() or wk[ns:].sum() else 0); hi.append(np.inf)
    # Depth vars: d <= y and per-need count <= gap.
    for gi, (need, _m) in enumerate(need_groups):
        base = nc + 3 * n + gi * nc
        r = row(); r[base:base + nc] = 1; rows.append(r); lo.append(-np.inf); hi.append(need["gap"])
        for j in range(nc):
            r = row(); r[base + j] = 1; r[j] = -1; rows.append(r); lo.append(-np.inf); hi.append(0)
    A = np.vstack(rows)
    res = milp(c, constraints=LinearConstraint(A, lo, hi), integrality=np.ones(nv), bounds=Bounds(0, 1),
               options={"time_limit": 20})
    if res.x is None:
        return None
    buy = res.x[:nc] > 0.5
    xi_sel = res.x[nc:nc + n] > 0.5
    return {"buy": buy, "xi": xi_sel, "objective": float(-res.fun), "status": res.message}


def _prefilter(state: dict, pool: List[dict], limit: int = 120) -> List[dict]:
    """Keep the candidates that matter: best value per lakh and best quality per role."""
    usable = [p for p in pool if p.get("p50")]
    by_q = sorted(usable, key=lambda p: -(p.get("quality") or 0))[: limit // 2]
    by_v = sorted(usable, key=lambda p: -((p.get("quality") or mk.ASSUMED_QUALITY) / max(p["p50"], 1)))[: limit // 2]
    seen, out = set(), []
    for p in by_q + by_v:
        k = p.get("player_id") or p["name"]
        if k not in seen:
            seen.add(k)
            out.append(p)
    return out


def _sample_price(p: dict, rng: random.Random) -> float:
    p10, p50, p90 = p["p10"], p["p50"], p["p90"]
    sigma = max(1e-3, (math.log(p90) - math.log(p10)) / 2.5631) if p10 and p90 else 0.4
    v = math.exp(math.log(p50) + rng.gauss(0, sigma))
    return max(v, p.get("base_lakh") or 0)


def optimise(ctx: mk.Context, val: dict, state: dict, pool: List[dict], plan: str = "balanced",
             draws: int = 12, seed: int = 11) -> dict:
    if not state["purse"].get("known"):
        return {"feasible": False, "reason": "Purse unknown for this franchise in this context."}
    cands = _prefilter(state, [p for p in pool if p.get("p50") and
                               (p.get("overseas") is not True or state["purse"]["overseas_slots_left"] > 0)])
    if not cands:
        return {"feasible": False, "reason": "No priced candidates remain in the pool."}
    q = {"aggressive": 0.5, "balanced": 0.5, "conservative": 0.75, "value": 0.5, "role_first": 0.5}.get(plan, 0.5)

    def cost(p):
        if q == 0.5:
            return p["p50"]
        return math.exp(math.log(p["p50"]) + 0.674 * (math.log(p["p90"]) - math.log(p["p10"])) / 2.5631) if p["p10"] and p["p90"] else p["p50"]
    costs = np.array([max(cost(p), p.get("base_lakh") or 0) for p in cands])
    base = _solve(state, cands, costs, ctx.rules)
    if base is None:
        return {"feasible": False, "reason": "No feasible squad completion within the purse at predicted prices."}
    chosen = [p for p, b in zip(cands, base["buy"]) if b]
    rng = random.Random(seed)
    freq = defaultdict(int)
    role_budget = defaultdict(list)
    xi_scores = []
    for _ in range(draws):
        sc = np.array([_sample_price(p, rng) for p in cands])
        res = _solve(state, cands, sc, ctx.rules)
        if res is None:
            continue
        spend = defaultdict(float)
        for p, b, price in zip(cands, res["buy"], sc):
            if b:
                freq[p.get("player_id") or p["name"]] += 1
                spend[_budget_bucket(p)] += price
        for k in ("Indian batters", "Overseas batters", "Indian pace", "Overseas pace", "Spin", "All-rounders", "Wicketkeepers", "Other"):
            role_budget[k].append(spend.get(k, 0.0))
        xi_scores.append(res["objective"])
    members_after = state["members"] + [member_from_player(p) for p in chosen]
    xi_after = mk.best_xi(members_after, ctx.rules.max_overseas_xi)
    total_cost = float(sum(c for c, b in zip(costs, base["buy"]) if b))
    alloc = {}
    for k, vals in role_budget.items():
        arr = np.array(vals)
        if arr.max() > 0:
            alloc[k] = {"p25_lakh": round(float(np.percentile(arr, 25)), 0), "median_lakh": round(float(np.median(arr)), 0),
                        "p75_lakh": round(float(np.percentile(arr, 75)), 0)}
    return {
        "feasible": True, "plan": plan, "price_basis": "p50" if q == 0.5 else "p75 (conservative)",
        "recommended": [{"player_id": p.get("player_id"), "name": p["name"], "role": p.get("role"),
                         "overseas": p.get("overseas"), "expected_price_lakh": round(float(c), 1),
                         "p10": p["p10"], "p90": p["p90"], "quality": p.get("quality"),
                         "robustness": round(freq.get(p.get("player_id") or p["name"], 0) / max(1, draws), 2),
                         "lot_number": p.get("lot_number")}
                        for p, c in zip(cands, costs) if (p.get("player_id") or p["name"]) in
                        {x.get("player_id") or x["name"] for x in chosen}],
        "expected_spend_lakh": round(total_cost, 0),
        "purse_lakh": state["purse"]["purse_lakh"],
        "expected_remaining_lakh": round(state["purse"]["purse_lakh"] - total_cost, 0),
        "xi_before": state["xi"]["score"], "xi_after": xi_after["score"],
        "xi_after_players": xi_after.get("bat_slots", []),
        "budget_allocation": alloc,
        "monte_carlo_draws": draws,
        "frequently_selected": sorted(({"name": next((p["name"] for p in cands if (p.get("player_id") or p["name"]) == k), k),
                                        "rate": round(v / max(1, draws), 2)} for k, v in freq.items()),
                                      key=lambda x: -x["rate"])[:15],
        "method": "Mixed-integer program (HiGHS via SciPy) jointly selecting purchases and the resulting best XI; "
                  "Monte Carlo re-solves with prices drawn from each player's predicted range.",
    }


def _budget_bucket(p: dict) -> str:
    tags = p.get("tags") or []
    if p.get("role") == "WK" or "wicketkeeper" in tags:
        return "Wicketkeepers"
    if p.get("role") == "AR" or "all_rounder" in tags:
        return "All-rounders"
    if "spin" in tags:
        return "Spin"
    if "pace" in tags:
        return "Overseas pace" if p.get("overseas") else "Indian pace"
    if p.get("role") == "BAT":
        return "Overseas batters" if p.get("overseas") else "Indian batters"
    return "Other"


def alternatives(val: dict, player: dict, pool: List[dict], limit: int = 6) -> List[dict]:
    """Similar-role players in the remaining pool, ranked by quality per predicted lakh."""
    tags = set(player.get("tags") or [])
    key_tags = tags & {"pace", "spin", "wicketkeeper", "finisher", "top_order", "middle_order", "all_rounder", "death_bowler"}
    out = []
    for p in pool:
        if p is player or (p.get("player_id") and p.get("player_id") == player.get("player_id")):
            continue
        shared = key_tags & set(p.get("tags") or [])
        if not shared and p.get("role") != player.get("role"):
            continue
        if not p.get("p50"):
            continue
        out.append({"player_id": p.get("player_id"), "name": p["name"], "role": p.get("role"), "overseas": p.get("overseas"),
                    "quality": p.get("quality"), "p50": p["p50"], "p10": p["p10"], "p90": p["p90"],
                    "shared_profile": sorted(shared), "lot_number": p.get("lot_number"),
                    "cheaper": bool(player.get("p50") and p["p50"] < player["p50"]),
                    "better_output": bool(player.get("quality") is not None and (p.get("quality") or 0) > player["quality"]),
                    "value_per_crore": round((p.get("quality") or mk.ASSUMED_QUALITY) / max(p["p50"] / 100, 0.2), 1)})
    out.sort(key=lambda x: (-len(x["shared_profile"]), -x["value_per_crore"]))
    return out[:limit]


def critical_reserve(state: dict, pool: List[dict], exclude_key: Optional[str] = None) -> dict:
    """Expected cost of filling every Critical/High need with the cheapest adequate remaining option."""
    total, detail = 0.0, []
    for need in state["needs"]:
        if need["priority"] not in ("Critical", "High") or need["gap"] <= 0:
            continue
        match = next(g[2] for g in mk.REQUIREMENT_GROUPS if g[0] == need["key"])
        skill = "bowl" if need["key"] in ("pace", "spin", "death_bowler", "powerplay_bowler") else "bat"
        options = []
        for p in pool:
            if exclude_key and (p.get("player_id") or p["name"]) == exclude_key:
                continue
            m = member_from_player(p)
            if match(m) and (m[skill] or 0) >= 50 and p.get("p50"):
                options.append((p["p50"], p["name"]))
        options.sort()
        k = 1 if need["priority"] == "High" else max(1, need["target"] - need["have"] if need["have"] < need["target"] else 1)
        k = min(k, len(options))
        cost = sum(o[0] for o in options[:k]) if options else None
        if cost is not None:
            total += cost
        detail.append({"need": need["label"], "priority": need["priority"], "players_needed": k or 1,
                       "cheapest_adequate_lakh": round(cost, 0) if cost is not None else None,
                       "options": [o[1] for o in options[:3]],
                       "note": None if options else "No adequate (quality ≥ 50) option left in the pool"})
    return {"total_lakh": round(total, 0), "detail": detail}


def compare_scenarios(ctx: mk.Context, val: dict, state: dict, pool: List[dict], scenarios: List[dict]) -> List[dict]:
    """Each scenario: {name, purchases: [{player_key, price_lakh}]}. Evaluated on the
    resulting squad, the purse left, needs still open, and — crucially — the best
    squad still reachable with the remaining purse (re-optimised)."""
    index = {(p.get("player_id") or p["name"]): p for p in pool}
    results = []
    for sc in scenarios:
        bought, spend, missing = [], 0.0, []
        for item in sc.get("purchases", []):
            p = index.get(item["player_key"])
            if not p:
                missing.append(item["player_key"])
                continue
            price = float(item.get("price_lakh") or p.get("p50") or p.get("base_lakh") or 0)
            bought.append((p, price))
            spend += price
        purse = state["purse"]["purse_lakh"] - spend
        squad = [{**x, "price_lakh": x.get("price_lakh")} for x in state["members"]]
        members = state["members"] + [member_from_player(p) for p, _ in bought]
        overseas = sum(1 for m in members if m["overseas"])
        new_state = {"members": members, "xi": mk.best_xi(members, ctx.rules.max_overseas_xi),
                     "needs": mk.squad_needs(members, state.get("targets", {}), ctx.rules.max_overseas_squad, ctx.rules.max_squad),
                     "targets": state.get("targets", {}),
                     "purse": mk.purse_constraints(purse, len(members), overseas, ctx.rules)}
        remaining_pool = [p for p in pool if all(p is not b for b, _ in bought)]
        warnings = []
        if purse < 0:
            warnings.append("Scenario exceeds the purse.")
        elif new_state["purse"]["minimum_reserve_lakh"] > purse:
            warnings.append("Remaining purse cannot complete the minimum squad at minimum base prices.")
        if overseas > ctx.rules.max_overseas_squad:
            warnings.append("Overseas squad limit exceeded.")
        follow = optimise(ctx, val, new_state, remaining_pool, draws=0) if purse >= 0 else {"feasible": False}
        results.append({
            "name": sc.get("name"), "spend_lakh": round(spend, 0), "purse_left_lakh": round(purse, 0),
            "xi_after_purchases": new_state["xi"]["score"],
            "open_critical_needs": [n["label"] for n in new_state["needs"] if n["priority"] == "Critical"],
            "open_high_needs": [n["label"] for n in new_state["needs"] if n["priority"] == "High"],
            "reserve_for_critical_needs": critical_reserve(new_state, remaining_pool),
            "best_reachable_xi": follow.get("xi_after") if follow.get("feasible") else None,
            "follow_up_purchases": [r["name"] for r in follow.get("recommended", [])][:8] if follow.get("feasible") else [],
            "warnings": warnings, "unknown_players": missing,
        })
    if results:
        best = max((r for r in results if r["best_reachable_xi"] is not None), key=lambda r: r["best_reachable_xi"], default=None)
        for r in results:
            r["verdict"] = "Strongest reachable squad" if best is r else None
    return results
