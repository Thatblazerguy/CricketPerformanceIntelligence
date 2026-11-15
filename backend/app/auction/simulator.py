"""Multi-franchise auction room.

Every franchise is an independent agent with its own purse, squad, overseas
slots and needs. For each lot an agent computes a *willingness to pay*:

    W = market × (0.55 + 0.75 · need) × strategy × aggression × ε

* market     — CPI predicted auction price (p50) for the player.
* need       — marginal squad value for *this* franchise (ΔXI from the best-XI
               MILP + depth credit for unmet needs), normalised to ~0–1.6.
               Re-computed after every purchase, so needs evolve live.
* strategy   — the user's chosen strategy for their franchise; AI franchises
               use "balanced".
* aggression — data-derived franchise spend tendency, only where historical
               evidence is statistically significant (otherwise 1.0).
* ε          — a deterministic private-valuation draw whose spread comes from
               the model's own price uncertainty (seeded: replays are repeatable).

W is then capped by (a) the legal maximum (purse minus the minimum reserve
needed to complete the squad at the minimum base price) and (b) an
opportunity-cost reserve: the expected cost of filling the franchise's other
Critical needs with the cheapest adequate players still to come.

Bidding is an ascending English auction using the season's increment ladder.
At each step the non-leading franchise with the highest remaining
willingness raises by one increment; the lot closes when nobody else will pay
the next bid. RTM is applied for seasons that allow it (previous franchise may
match; the winner gets one final raise to their own limit).

Everything here is *simulated*. Nothing is a reconstruction of real bidding —
bid-level historical data does not exist in CPI.
"""
from __future__ import annotations

import hashlib
import math
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from app.auction import market as mk, optimizer as op

STRATEGIES = {
    "balanced": {"mult": 1.0, "reserve_factor": 1.0, "label": "Balanced squad",
                 "summary": "Bids up to need-adjusted market value while protecting the cost of Critical needs."},
    "aggressive": {"mult": 1.25, "reserve_factor": 0.5, "label": "Aggressive",
                   "summary": "Pays up to 25% over need-adjusted value and keeps only half the opportunity-cost reserve."},
    "conservative": {"mult": 0.85, "reserve_factor": 1.25, "label": "Conservative",
                     "summary": "Caps bids 15% below need-adjusted value and over-reserves for remaining needs."},
    "value": {"mult": 1.0, "reserve_factor": 1.0, "label": "Value-focused",
              "summary": "Never pays above the lower of predicted price and performance-implied value."},
    "role_first": {"mult": 1.0, "reserve_factor": 0.8, "label": "Role-first",
                   "summary": "Pays heavily for players filling Critical/High needs; barely bids on anything else."},
}
NEED_SCALE = 45.0


def _noise(seed: int, franchise: str, key: str, sigma: float) -> float:
    h = int(hashlib.sha256(f"{seed}|{franchise}|{key}".encode()).hexdigest()[:12], 16)
    u1 = ((h & 0xFFFFFF) + 1) / (0xFFFFFF + 2)
    u2 = (((h >> 24) & 0xFFFFFF) + 1) / (0xFFFFFF + 2)
    z = math.sqrt(-2 * math.log(u1)) * math.cos(2 * math.pi * u2)
    return math.exp(sigma * z)


def _pkey(p: dict) -> str:
    return p.get("player_id") or "name:" + p["name"]


class AuctionRoom:
    def __init__(self, db: Session, ctx: mk.Context, state: dict):
        self.db, self.ctx, self.state = db, ctx, state
        self.val = mk.value_pool(db, ctx)
        self.players = {_pkey(p): p for p in self.val["players"]}
        self.targets = state.setdefault("targets", mk.derive_requirement_targets(db, ctx.as_of))
        self.behaviour = state.setdefault("behaviour", {k: v["aggression"] for k, v in
                                                        mk.franchise_behaviour(db, ctx.rules.season).items()})
        self._fstate_cache: Dict[str, dict] = {}

    # ------------------------------------------------------------------ setup
    @classmethod
    def new_state(cls, db: Session, ctx: mk.Context, user_franchise: Optional[str], strategy: str, seed: int,
                  order: str = "recorded") -> dict:
        val = mk.value_pool(db, ctx)
        franchises = {}
        for code, f in ctx.franchises.items():
            if f["purse_lakh"] is None:
                continue
            retained = len(f["squad"])
            rtm = 0
            if ctx.rules.rtm_enabled and ctx.rules.season == 2025:
                rtm = max(0, 6 - retained)  # 2025 rule: RTM cards = 6 − retentions
            franchises[code] = {"purse_lakh": f["purse_lakh"], "squad": [_squad_entry(x) for x in f["squad"]],
                                "bought": [], "rtm_cards": rtm, "spent_lakh": 0.0}
        lots = [p for p in val["players"]]
        if order == "quality":
            lots.sort(key=lambda p: -(p.get("p50") or 0))
        keys = [_pkey(p) for p in lots]
        return {"context": ctx.key, "user_franchise": user_franchise if user_franchise in franchises else None,
                "strategy": strategy if strategy in STRATEGIES else "balanced", "seed": seed,
                "order": keys, "cursor": 0, "franchises": franchises, "lot": None, "results": [],
                "status": "READY", "excluded_franchises": [c for c in ctx.franchises if c not in franchises],
                "labels": {"bids": "simulated", "interest": "model-estimated"}}

    # --------------------------------------------------------------- helpers
    def fstate(self, code: str) -> dict:
        if code not in self._fstate_cache:
            f = self.state["franchises"][code]
            self._fstate_cache[code] = op.franchise_state(self.ctx, self.val, code, squad=f["squad"],
                                                          purse_lakh=f["purse_lakh"], targets=self.targets)
        return self._fstate_cache[code]

    def remaining_pool(self) -> List[dict]:
        upcoming = self.state["order"][self.state["cursor"]:]
        return [self.players[k] for k in upcoming if k in self.players]

    def willingness(self, code: str, player: dict, strategy: Optional[str] = None) -> dict:
        fs = self.fstate(code)
        rules = self.ctx.rules
        strategy = strategy or "balanced"
        cfg = STRATEGIES[strategy]
        purse = fs["purse"]
        reasons = []
        if not purse.get("known") or purse["slots_left"] <= 0:
            return _ineligible("Squad full", strategy)
        if player.get("overseas") and purse["overseas_slots_left"] <= 0:
            return _ineligible("No overseas slot left", strategy)
        base = player.get("base_lakh") or rules.min_base_price_lakh
        if purse["max_theoretical_bid_lakh"] < base:
            return _ineligible("Cannot afford base price while completing squad", strategy)
        mv = op.marginal_value(fs, player, rules.max_overseas_xi)
        need = max(0.0, min(1.6, mv["total"] / NEED_SCALE))
        market = player.get("p50") or base
        fills_priority = any(f["priority"] in ("Critical", "High") for f in mv["fills"])
        if strategy == "role_first":
            factor = (0.3 + 1.2 * need) if fills_priority else 0.4 * (0.55 + 0.75 * need)
        else:
            factor = 0.55 + 0.75 * need
        sigma = 0.15
        if player.get("p10") and player.get("p90"):
            sigma = min(0.35, max(0.08, (math.log(player["p90"]) - math.log(player["p10"])) / 2.5631 * 0.35))
        eps = _noise(self.state["seed"], code, _pkey(player), sigma)
        aggression = self.behaviour.get(code, 1.0) if code != self.state.get("user_franchise") else 1.0
        limit = market * factor * cfg["mult"] * aggression * eps
        if strategy == "value":
            cap = min(x for x in (player.get("p50"), player.get("market_value_lakh")) if x) if (player.get("p50") or player.get("market_value_lakh")) else limit
            limit = min(limit, cap)
            reasons.append("Value strategy: capped at the lower of predicted price and performance-implied value")
        if need < 0.1:
            # No squad improvement: only a bargain depth bid.
            limit = min(limit, 0.5 * market) if purse["slots_left"] > purse["min_slots_to_fill"] else 0.0
            reasons.append("Little squad improvement — bargain bids only")
        reserve = op.critical_reserve(fs, self.remaining_pool(), exclude_key=_pkey(player))
        opp_cap = purse["purse_lakh"] - purse["minimum_reserve_lakh"] - cfg["reserve_factor"] * reserve["total_lakh"]
        legal_cap = purse["max_theoretical_bid_lakh"]
        capped_by = None
        if limit > legal_cap:
            limit, capped_by = legal_cap, "legal maximum (must complete squad)"
        if opp_cap > base and limit > opp_cap:
            limit, capped_by = opp_cap, "opportunity-cost reserve for other Critical needs"
        limit = max(0.0, limit)
        if mv["fills"]:
            reasons.append("Fills " + ", ".join(f"{f['need']} ({f['priority']})" for f in mv["fills"]))
        reasons.append(f"Best-XI change {mv['xi_delta']:+.1f}; would {'start' if mv['would_start'] else 'not start'}")
        if capped_by:
            reasons.append(f"Limit capped by {capped_by}")
        return {"limit": round(limit, 1), "need": round(need, 3), "eligible": limit >= base, "reasons": reasons,
                "marginal": mv, "reserve_for_needs_lakh": reserve["total_lakh"], "market_lakh": market,
                "strategy": strategy}

    def _next_bid(self, lot: dict) -> float:
        if lot["bid"] is None:
            return lot["base"]
        return round(lot["bid"] + self.ctx.rules.increment(lot["bid"]), 2)

    # --------------------------------------------------------------- actions
    def call_next(self) -> dict:
        st = self.state
        if st["lot"] and st["lot"]["status"] == "BIDDING":
            raise ValueError("Finish the current lot first")
        if st["cursor"] >= len(st["order"]):
            st["status"] = "COMPLETE"
            return st
        key = st["order"][st["cursor"]]
        st["cursor"] += 1
        p = self.players[key]
        base = p.get("base_lakh") or self.ctx.rules.min_base_price_lakh
        interest = {}
        for code in st["franchises"]:
            if code == st.get("user_franchise"):
                continue
            w = self.willingness(code, p)
            interest[code] = {"limit": w["limit"], "need": w["need"], "eligible": w["eligible"], "reasons": w["reasons"]}
        st["lot"] = {"player_key": key, "name": p["name"], "base": base, "bid": None, "leader": None,
                     "history": [], "status": "BIDDING", "passed": [], "interest": interest}
        st["status"] = "LIVE"
        return st

    def user_bid(self, amount: Optional[float] = None) -> dict:
        st, lot = self.state, self.state["lot"]
        user = st.get("user_franchise")
        if not user:
            raise ValueError("You are not controlling a franchise in this simulation")
        if not lot or lot["status"] != "BIDDING":
            raise ValueError("No player is on the block")
        if lot["leader"] == user:
            raise ValueError("You already hold the highest bid")
        if user in lot["passed"]:
            raise ValueError("You passed on this player")
        nxt = self._next_bid(lot)
        amount = float(amount) if amount else nxt
        if amount < nxt:
            raise ValueError(f"Bid must be at least {nxt:g} lakh")
        fs = self.fstate(user)
        p = self.players[lot["player_key"]]
        purse = fs["purse"]
        if purse["slots_left"] <= 0:
            raise ValueError("Your squad is full")
        if p.get("overseas") and purse["overseas_slots_left"] <= 0:
            raise ValueError("No overseas slot left")
        from app.auction_rules import validate_bid
        validate_bid(current_bid=lot["bid"] if lot["bid"] is not None else amount - self.ctx.rules.increment(amount),
                     offered_bid=amount, minimum_increment=self.ctx.rules.increment(lot["bid"] or amount),
                     remaining_purse=purse["purse_lakh"], squad_count=len(fs["members"]),
                     maximum_squad_size=self.ctx.rules.max_squad)
        if amount > purse["max_theoretical_bid_lakh"]:
            raise ValueError(f"Bid exceeds your maximum legal bid of {purse['max_theoretical_bid_lakh']:g} lakh "
                             "(you must keep enough to complete the minimum squad)")
        self._record(user, amount, "USER")
        return st

    def user_pass(self) -> dict:
        lot = self.state["lot"]
        user = self.state.get("user_franchise")
        if lot and user and user not in lot["passed"]:
            lot["passed"].append(user)
        return self.state

    def _record(self, code, amount, source):
        lot = self.state["lot"]
        lot["bid"], lot["leader"] = amount, code
        lot["history"].append({"franchise": code, "bid_lakh": amount, "source": source})

    def ai_step(self) -> str:
        """One AI bid. Returns 'bid', 'awaiting_user' or 'closed'."""
        st, lot = self.state, self.state["lot"]
        if not lot or lot["status"] != "BIDDING":
            return "closed"
        nxt = self._next_bid(lot)
        user = st.get("user_franchise")
        cands = [(c, i["limit"]) for c, i in lot["interest"].items()
                 if c != lot["leader"] and i["eligible"] and i["limit"] >= nxt and c not in lot["passed"]
                 and self.fstate(c)["purse"]["max_theoretical_bid_lakh"] >= nxt]
        if cands:
            cands.sort(key=lambda x: (-x[1], x[0]))
            self._record(cands[0][0], nxt, "AI")
            return "bid"
        user_active = user and user != lot["leader"] and user not in lot["passed"] and st.get("user_controls", True)
        if user_active:
            return "awaiting_user"
        self._close()
        return "closed"

    def run_lot(self, user_autopilot: bool = False) -> str:
        """Advance the current lot until it closes or needs the user."""
        guard = 0
        while guard < 2000:
            guard += 1
            outcome = self.ai_step()
            if outcome == "closed":
                return "closed"
            if outcome == "awaiting_user":
                if not user_autopilot:
                    return "awaiting_user"
                rec = self.recommend()
                lot = self.state["lot"]
                if rec["max_bid_lakh"] >= self._next_bid(lot) and rec["action"] != "Stop bidding":
                    try:
                        self.user_bid()
                        lot["history"][-1]["source"] = "USER-AUTO"
                    except ValueError:
                        self.user_pass()
                else:
                    self.user_pass()
        return "closed"

    def _close(self):
        st, lot = self.state, self.state["lot"]
        p = self.players[lot["player_key"]]
        rtm_note = None
        if lot["leader"] is None:
            lot["status"] = "UNSOLD"
            result = {"player_key": lot["player_key"], "name": p["name"], "status": "UNSOLD", "franchise": None,
                      "price_lakh": None, "bids": 0}
        else:
            winner, price = lot["leader"], lot["bid"]
            prev = p.get("previous_franchise")
            if self.ctx.rules.rtm_enabled and prev and prev != winner and prev in st["franchises"] \
                    and st["franchises"][prev]["rtm_cards"] > 0 and prev != st.get("user_franchise"):
                w_prev = self.willingness(prev, p)
                if w_prev["eligible"] and w_prev["limit"] >= price:
                    # Winner gets one final raise (to its own limit); RTM side matches if it can.
                    # Simplified behavioural assumption: the winner makes one final raise of
                    # at most ~15% (never above its own limit or legal maximum). A user-held
                    # winning bid is not raised automatically.
                    w_win = lot["interest"].get(winner, {}).get("limit", price) if winner != st.get("user_franchise") else price
                    raise_to = price
                    while raise_to + self.ctx.rules.increment(raise_to) <= min(price * 1.15, w_win):
                        raise_to += self.ctx.rules.increment(raise_to)
                    final = max(price, min(raise_to, self.fstate(winner)["purse"]["max_theoretical_bid_lakh"]))
                    if w_prev["limit"] >= final and self.fstate(prev)["purse"]["max_theoretical_bid_lakh"] >= final:
                        st["franchises"][prev]["rtm_cards"] -= 1
                        rtm_note = f"{prev} used RTM to match {final:g} lakh (winner's final raise)"
                        winner, price = prev, final
                    else:
                        rtm_note = f"{prev} considered RTM but could not match the final raise to {final:g} lakh"
                        price = final
            lot["status"] = "SOLD"
            f = st["franchises"][winner]
            f["purse_lakh"] = round(f["purse_lakh"] - price, 2)
            f["spent_lakh"] = round(f["spent_lakh"] + price, 2)
            entry = {**_squad_entry(p), "price_lakh": price, "acquired": "simulated auction"}
            f["squad"].append(entry)
            f["bought"].append({"player_key": lot["player_key"], "name": p["name"], "price_lakh": price})
            self._fstate_cache.pop(winner, None)
            result = {"player_key": lot["player_key"], "name": p["name"], "status": "SOLD", "franchise": winner,
                      "price_lakh": price, "bids": len(lot["history"]), "rtm": rtm_note,
                      "underbidder": next((h["franchise"] for h in reversed(lot["history"]) if h["franchise"] != lot["leader"]), None)}
        result.update({"p10": p.get("p10"), "p50": p.get("p50"), "p90": p.get("p90"), "role": p.get("role"),
                       "overseas": p.get("overseas"), "actual_price_lakh": p.get("actual_price_lakh"),
                       "actual_franchise": p.get("actual_franchise"), "actual_status": p.get("actual_status"),
                       "history": lot["history"]})
        st["results"].append(result)
        if st["cursor"] >= len(st["order"]):
            st["status"] = "COMPLETE"

    # -------------------------------------------------------- recommendations
    def recommend(self) -> dict:
        st, lot = self.state, self.state["lot"]
        user = st.get("user_franchise")
        if not user or not lot:
            return {"action": None, "max_bid_lakh": 0, "reasons": []}
        p = self.players[lot["player_key"]]
        w = self.willingness(user, p, st.get("strategy", "balanced"))
        fs = self.fstate(user)
        nxt = self._next_bid(lot) if lot["status"] == "BIDDING" else None
        reasons = list(w["reasons"])
        alts = op.alternatives(self.val, p, self.remaining_pool())
        cheaper_better = [a for a in alts if a["cheaper"] and (a["quality"] or 0) >= (p.get("quality") or 0) - 3]
        purse_after = fs["purse"]["purse_lakh"] - (nxt or 0) if fs["purse"].get("known") else None
        if not w["eligible"]:
            action = "Do not bid"
        elif nxt is not None and nxt > w["limit"]:
            action = "Stop bidding"
            reasons.insert(0, f"Next bid {nxt:g} lakh exceeds your limit of {w['limit']:g} lakh")
        elif nxt is not None and nxt > 0.85 * w["limit"]:
            action = "Bid cautiously"
            reasons.insert(0, "Close to your limit")
        else:
            action = "Continue bidding"
        if w["need"] >= 1.0 and any(f["priority"] == "Critical" for f in w["marginal"]["fills"]):
            reasons.append("Player is critical to your squad requirements")
        if cheaper_better:
            reasons.append(f"{len(cheaper_better)} comparable player(s) still to come at lower predicted prices "
                           f"(e.g. {cheaper_better[0]['name']} ~{cheaper_better[0]['p50']:g} lakh)")
        if p.get("p90") and nxt and nxt > p["p90"]:
            reasons.append("Price already above the top of CPI's predicted range — overpriced relative to the market estimate")
        if purse_after is not None and purse_after - fs["purse"]["minimum_reserve_lakh"] < w["reserve_for_needs_lakh"]:
            reasons.append(f"Spending here leaves {purse_after:g} lakh against ~{w['reserve_for_needs_lakh']:g} lakh "
                           "expected for your other Critical/High needs")
        return {"action": action, "max_bid_lakh": w["limit"], "next_bid_lakh": nxt, "reasons": reasons,
                "need": w["need"], "marginal": w["marginal"], "alternatives": alts[:5],
                "purse_after_next_bid_lakh": purse_after, "reserve_for_needs_lakh": w["reserve_for_needs_lakh"],
                "strategy": STRATEGIES[st.get("strategy", "balanced")]["label"]}

    # ---------------------------------------------------------------- views
    def snapshot(self) -> dict:
        st = self.state
        lot = st["lot"]
        teams = []
        for code, f in st["franchises"].items():
            fs = self.fstate(code)
            teams.append({"code": code, "name": self.ctx.franchises[code]["name"], "purse_lakh": f["purse_lakh"],
                          "spent_lakh": f["spent_lakh"], "squad_size": len(f["squad"]), "bought": f["bought"],
                          "overseas": fs["overseas"], "slots_left": fs["purse"]["slots_left"],
                          "overseas_slots_left": fs["purse"]["overseas_slots_left"],
                          "max_bid_lakh": fs["purse"]["max_theoretical_bid_lakh"], "xi_score": fs["xi"]["score"],
                          "top_needs": [n for n in fs["needs"] if n["priority"] in ("Critical", "High")][:4],
                          "rtm_cards": f["rtm_cards"], "is_user": code == st.get("user_franchise")})
        current = None
        if lot:
            p = self.players[lot["player_key"]]
            current = {**lot, "player": _public_player(p), "next_bid_lakh": self._next_bid(lot) if lot["status"] == "BIDDING" else None,
                       "interest": [{"franchise": c, **{k: v for k, v in i.items()}} for c, i in
                                    sorted(lot["interest"].items(), key=lambda kv: -kv[1]["limit"])]}
        return {"status": st["status"], "cursor": st["cursor"], "total_lots": len(st["order"]),
                "user_franchise": st.get("user_franchise"), "strategy": st.get("strategy"),
                "strategy_summary": STRATEGIES[st.get("strategy", "balanced")]["summary"],
                "teams": teams, "current": current, "results": st["results"][-40:],
                "results_count": len(st["results"]),
                "recommendation": self.recommend() if lot and lot["status"] == "BIDDING" and st.get("user_franchise") else None,
                "excluded_franchises": st.get("excluded_franchises", []),
                "upcoming": [_public_player(self.players[k]) for k in st["order"][st["cursor"]:st["cursor"] + 8]],
                "labels": {"bids": "Simulated bids — not a reconstruction of real bidding",
                           "interest": "Model-estimated franchise interest and limits",
                           "actual": "Actual historical outcome shown for comparison only"}}

    def summary(self) -> dict:
        res = self.state["results"]
        sold = [r for r in res if r["status"] == "SOLD"]
        both = [r for r in sold if r.get("actual_price_lakh")]
        same_team = sum(1 for r in both if r["franchise"] == r.get("actual_franchise"))
        short = [{"franchise": c, "squad_size": len(f["squad"]), "minimum": self.ctx.rules.min_squad}
                 for c, f in self.state["franchises"].items() if len(f["squad"]) < self.ctx.rules.min_squad]
        return {"lots": len(res), "sold": len(sold), "unsold": len(res) - len(sold),
                "below_minimum_squad": short,
                "below_minimum_note": ("Recorded pool is sold-only, so there were not enough players to complete every squad."
                                       if short and self.ctx.historical else None),
                "total_spend_lakh": round(sum(r["price_lakh"] for r in sold), 0),
                "vs_actual": {"compared": len(both),
                              "mae_lakh": round(sum(abs(r["price_lakh"] - r["actual_price_lakh"]) for r in both) / len(both), 1) if both else None,
                              "same_franchise_rate": round(same_team / len(both), 3) if both else None,
                              "note": "Simulated outcomes vs recorded outcomes (replays only)."}}


def _ineligible(reason: str, strategy: str) -> dict:
    return {"limit": 0.0, "need": 0.0, "eligible": False, "reasons": [reason], "strategy": strategy,
            "marginal": {"xi_delta": 0.0, "depth_value": 0.0, "total": 0.0, "fills": [], "would_start": False},
            "reserve_for_needs_lakh": 0.0, "market_lakh": None}


def _squad_entry(x: dict) -> dict:
    return {k: x.get(k) for k in ("player_id", "name", "role", "bowling_kind", "overseas", "price_lakh", "acquired",
                                  "bat_quality", "bowl_quality", "tags")}


def _public_player(p: dict) -> dict:
    keys = ("player_id", "name", "role", "bowling_kind", "overseas", "capped", "base_lakh", "set_code", "lot_number",
            "p10", "p50", "p90", "market_value_lakh", "quality", "bat_quality", "bowl_quality", "tags", "confidence",
            "scarcity", "bidding_war_probability", "previous_franchise", "explanation", "sale_probability")
    out = {k: p.get(k) for k in keys}
    f = p.get("features") or {}
    out["stats"] = {k: f.get(k) for k in ("ipl_matches_career", "bat_sr_eq", "bat_avg_eq", "bat_death_sr",
                                          "bowl_econ_eq", "bowl_sr_eq", "bowl_death_econ", "t20_bat_balls", "t20_bowl_balls")}
    return out
