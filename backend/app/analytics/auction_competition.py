"""Scenario demand, bidder eligibility and competition-adjusted price helpers."""
from math import exp, log1p


def competition_level(bidder_count):
    if bidder_count >= 6:
        return "Extreme"
    if bidder_count >= 3:
        return "High"
    if bidder_count >= 1:
        return "Moderate"
    return "Low"


def demand_score(gap, target, quality_score, purse_lakh, player_price_lakh,
                 base_price_lakh, slots_left, overseas_slots=None, is_overseas=False):
    """Return a 0-100 team-player demand score and constraint explanation."""
    reasons = []
    if gap <= 0:
        return 0.0, ["No remaining role shortage"]
    if slots_left <= 0:
        return 0.0, ["Squad is full"]
    if is_overseas and overseas_slots is not None and overseas_slots <= 0:
        return 0.0, ["Overseas squad limit reached"]
    if purse_lakh < base_price_lakh:
        return 0.0, ["Remaining purse is below the base price"]

    urgency = min(1.0, float(gap) / max(1, int(target)))
    quality = 0.60 if quality_score is None else 0.55 + 0.45 * max(0.0, min(1.0, quality_score / 100.0))
    affordability = min(1.0, purse_lakh / max(base_price_lakh, player_price_lakh, 1.0))
    score = 100.0 * urgency * quality * affordability
    reasons.append("Role shortage: {} of {} target slots unfilled".format(gap, target))
    if quality_score is not None:
        reasons.append("Pool-relative CPI performance quality: {:.0f}/100".format(quality_score))
    else:
        reasons.append("CPI performance sample unavailable; demand confidence reduced")
    if is_overseas and overseas_slots is not None:
        reasons.append("{} overseas squad slots remain".format(overseas_slots))
    return round(score, 1), reasons


def team_willingness_lakh(predicted_price_lakh, base_price_lakh, purse_lakh):
    """Return a franchise's price estimate, bounded by its actual available purse.

    A purse is an affordability ceiling, not a bid estimate. Demand and urgency
    affect whether a franchise is a credible bidder; the franchise-specific
    auction model supplies its willingness-to-pay anchor.
    """
    base = max(0.0, float(base_price_lakh or 0.0))
    purse = max(0.0, float(purse_lakh or 0.0))
    predicted = max(base, float(predicted_price_lakh or 0.0))
    return round(min(purse, predicted), 2)


def competition_adjusted_price(base_price_lakh, historical_value_lakh, bidder_values_lakh,
                               comparable_alternatives, role_markup, model_mae_lakh=0.0):
    """Estimate an auction close from a historical anchor and feasible bidder limits.

    A nonlinear pressure curve reacts to serious bidders and comparable pool
    alternatives. Role markup is learned from sold auction records by the caller.
    """
    base = max(0.0, float(base_price_lakh or 0.0))
    anchor = max(base, float(historical_value_lakh or 0.0))
    bidders = sorted((max(base, float(value)) for value in bidder_values_lakh), reverse=True)
    count = len(bidders)
    alternatives = max(0, int(comparable_alternatives or 0))
    markup = max(0.0, float(role_markup or 0.0))
    # Demand saturates nonlinearly; plentiful comparable players dilute the
    # pressure while multiple credible bidders make a price war increasingly likely.
    pressure = 1.0 - exp(-(count * count) / (2.0 * (alternatives + 1))) if count else 0.0
    scarcity = 1.0 / ((1.0 + alternatives) ** 0.5)
    adjusted_anchor = anchor * (1.0 + markup * pressure * scarcity)
    if count >= 2:
        expected = max(base, bidders[1], adjusted_anchor)
    elif count == 1:
        expected = max(base, min(bidders[0], adjusted_anchor))
    else:
        expected = max(base, anchor)
    if bidders:
        expected = min(expected, bidders[0])
    dispersion = (bidders[0] - bidders[1]) if count >= 2 else (anchor * 0.25)
    uncertainty = max(0.0, float(model_mae_lakh or 0.0)) + dispersion / 2.0
    low = max(base, expected - uncertainty)
    high = max(expected, expected + uncertainty)
    return {
        "expected_lakh": round(expected, 2),
        "low_lakh": round(low, 2),
        "high_lakh": round(high, 2),
        "bidder_count": count,
        "competition_level": competition_level(count),
        "competition_pressure": round(pressure, 4),
        "scarcity_score": round(100.0 / (1 + alternatives), 1),
        "comparable_alternatives": alternatives,
    }


def percentile_quality(rows, role):
    """Compute cohort-relative quality from actual T20 metrics; missing stays missing."""
    def percentiles(metric, higher_is_better):
        values = [(pid, row.get(metric)) for pid, row in rows.items()
                  if row.get(metric) is not None]
        if not values:
            return {}
        ordered = sorted(value for _, value in values)
        result = {}
        for pid, value in values:
            rank = sum(1 for candidate in ordered if candidate <= value) / float(len(ordered))
            result[pid] = rank if higher_is_better else 1.0 - rank
        return result

    if role == "Specialist Bowler":
        keys = [("wickets_per_match", True), ("economy", False), ("bowling_average", False),
                ("bowling_strike_rate", False), ("dot_percentage", True)]
        discipline = "bowling"
    elif role in ("Batting All-Rounder", "Bowling All-Rounder", "All-Rounder"):
        batting = percentile_quality(rows, "Batter")
        bowling = percentile_quality(rows, "Specialist Bowler")
        scores = {}
        for pid in rows:
            components = [score for score in (batting.get(pid), bowling.get(pid)) if score is not None]
            scores[pid] = round(sum(components) / len(components) * 100.0, 1) if components else None
        return scores
    else:
        keys = [("batting_average", True), ("strike_rate", True), ("boundary_percentage", True),
                ("batting_dot_percentage", False)]
        discipline = "batting"

    metrics = [percentiles(key, higher) for key, higher in keys]
    scores = {}
    for pid, row in rows.items():
        available = [metric[pid] for metric in metrics if pid in metric]
        balls = row.get("{}_balls".format(discipline), 0)
        minimum_sample = 60 if discipline == "bowling" else 100
        scores[pid] = round(sum(available) / len(available) * 100.0, 1) if available and balls >= minimum_sample else None
    return scores
