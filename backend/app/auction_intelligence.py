"""Small, deterministic helpers for auction rules and predicted XI selection."""
import re

IPL_RULES = {"maximum_squad_size": 25, "overseas_squad_limit": 8, "overseas_xi_limit": 4}

def parse_rules_text(text: str) -> dict:
    found = {}
    patterns = {
        "maximum_squad_size": r"(?:maximum|max|up to)\s+(?:squad\s+size|players?\s+in\s+(?:the\s+)?squad)\D{0,20}(\d{1,2})|(?:maximum|max)\s+squad\s+(?:size\s*)?(\d{1,2})",
        "overseas_squad_limit": r"(?:maximum|max)\s+(?:of\s+)?(\d{1,2})\s+overseas\s+players?\s+(?:in\s+(?:the\s+)?squad)?|(?:maximum|max)\s+overseas\s+players?\s+(?:in\s+(?:the\s+)?squad)\D{0,12}(\d{1,2})",
        "overseas_xi_limit": r"(?:maximum|max)\s+(?:of\s+)?(\d{1,2})\s+overseas\s+players?\s+(?:in\s+(?:the\s+)?playing\s*xi|playing\s*xi)|(?:maximum|max)\s+overseas\s+players?\s+(?:in\s+(?:the\s+)?playing\s*xi|playing\s*xi)\D{0,12}(\d{1,2})",
    }
    for key, pattern in patterns.items():
        match = re.search(pattern, text, re.I)
        if match:
            found[key] = int(next(value for value in match.groups() if value is not None))
    return found

def validate_composition(players, rules):
    max_squad = int(rules.get("maximum_squad_size", 25))
    overseas_squad = int(rules.get("overseas_squad_limit", 8))
    overseas_xi = int(rules.get("overseas_xi_limit", 4))
    if len(players) > max_squad: raise ValueError(f"Squad exceeds maximum size of {max_squad}")
    overseas = sum(bool(p.get("overseas")) for p in players)
    if overseas > overseas_squad: raise ValueError(f"Squad exceeds overseas limit of {overseas_squad}")
    if len(players) == 11 and overseas > overseas_xi: raise ValueError(f"Playing XI exceeds overseas limit of {overseas_xi}")
    return True

def build_predicted_xi(candidates, rules, style="balanced"):
    """Greedy role/overseas-constrained XI from actual squad candidates only."""
    if style not in {"balanced", "batting-heavy", "bowling-heavy", "spin-friendly", "pace-friendly"}:
        raise ValueError("Unsupported XI style")
    if not candidates: raise ValueError("No current squad players are available")
    scores = []
    for p in candidates:
        bat, bowl = p.get("bat_score"), p.get("bowl_score")
        if style == "batting-heavy": score = (bat or 0) * 1.45 + (bowl or 0) * .65
        elif style == "bowling-heavy": score = (bat or 0) * .65 + (bowl or 0) * 1.45
        elif style == "spin-friendly": score = (bat or 0) + (p.get("spin_score") or 0) * 1.25 + (bowl or 0) * .8
        elif style == "pace-friendly": score = (bat or 0) + (p.get("pace_score") or 0) * 1.25 + (bowl or 0) * .8
        else: score = (bat or 0) + (bowl or 0)
        phase_values = [p.get("powerplay_score"), p.get("middle_score"), p.get("death_score")]
        phase_values = [x for x in phase_values if x is not None]
        if phase_values: score += sum(phase_values) / len(phase_values) * .2
        score += .12 if p.get("wicketkeeper") else 0
        scores.append({**p, "selection_score": round(score, 3)})
    scores.sort(key=lambda p: (-p["selection_score"], p["name"].casefold()))
    chosen, overseas_cap = [], int(rules.get("overseas_xi_limit", 4))
    # Prioritise a keeper if the roster contains one, then require credible bowling coverage.
    keepers = [p for p in scores if p.get("wicketkeeper")]
    if keepers: chosen.append(keepers[0])
    for p in scores:
        if p in chosen or len(chosen) >= 11: continue
        if p.get("overseas") and sum(bool(x.get("overseas")) for x in chosen) >= overseas_cap: continue
        chosen.append(p)
    if len(chosen) < 11: raise ValueError("Fewer than 11 players meet the configured XI restrictions")
    # Swap a low-scoring batter for a bowler when feasible, preserving keeper and overseas cap.
    def bowlers(xs): return sum((x.get("bowl_score") or 0) >= .25 for x in xs)
    if bowlers(chosen) < 4:
        for incoming in scores:
            if incoming in chosen or (incoming.get("bowl_score") or 0) < .25: continue
            outgoing = next((x for x in reversed(chosen) if not x.get("wicketkeeper") and (x.get("bowl_score") or 0) < .25 and (not incoming.get("overseas") or sum(bool(y.get("overseas")) for y in chosen) < overseas_cap)), None)
            if outgoing:
                chosen.remove(outgoing); chosen.append(incoming)
                if bowlers(chosen) >= 4: break
    validate_composition([{**p, "overseas": p.get("overseas", False)} for p in chosen], rules)
    chosen.sort(key=lambda p: (-(p.get("bat_score") or 0), p["name"].casefold()))
    selected_ids = {p["player_id"] for p in chosen}
    return {"players": [{"player_id": p["player_id"], "name": p["name"], "batting_order": i,
                         "role": p.get("role"), "reason": p.get("reason") or "Selected by role balance and available performance data.",
                         "confidence": p.get("confidence", "low"), "limitations": p.get("limitations"),
                         "overseas": bool(p.get("overseas")),
                         "nationality_known": bool(p.get("nationality_known"))}
                        for i, p in enumerate(chosen, 1)],
            "near_misses": [{"player_id": p["player_id"], "name": p["name"], "reason": "Ranked just outside the selected XI under current role and overseas constraints."}
                            for p in scores if p["player_id"] not in selected_ids][:5],
            "weaknesses": (["Fewer than four squad members have meaningful bowling evidence."] if bowlers(chosen) < 4 else []) +
                (["No wicketkeeper is identified in the available squad metadata."] if not any(p.get("wicketkeeper") for p in chosen) else []) +
                (["No selected player has a recorded sample for one or more T20 bowling phases."] if not all(any(p.get(f"{phase}_score") is not None for p in chosen) for phase in ("powerplay", "middle", "death")) else []),
            "confidence": "medium" if sum(p.get("data_complete", False) for p in chosen) >= 7 else "low",
            "overseas_selected": sum(bool(p.get("overseas")) for p in chosen),
            "overseas_limit": overseas_cap,
            "style": style, "selection_basis": "Current franchise squad only; player pool entries are excluded until purchased.",
            "limitations": "Scores are deterministic role and CPI-stat based rankings, not a trained match outcome prediction."}
