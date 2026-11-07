"""Configurable role-specific, format-relative scouting scores."""
from typing import Dict, List, Optional


SCOUTING_PRESETS = {
    "BATTERS": {
        "High Strike Rate": {"strike_rate": 0.30, "boundary_percentage": 0.22, "recent_form": 0.14, "death_over_strike_rate": 0.14, "consistency": 0.10, "matches": 0.10},
        "Reliable Performer": {"batting_average": 0.28, "consistency": 0.25, "matches": 0.18, "innings": 0.12, "recent_form": 0.10, "dot_ball_percentage": 0.07},
        "Powerplay Aggressor": {"powerplay_strike_rate": 0.30, "pace_strike_rate": 0.18, "boundary_percentage": 0.18, "recent_form": 0.12, "consistency": 0.10, "matches": 0.12},
        "Middle-Order Anchor": {"batting_average": 0.26, "middle_over_strike_rate": 0.20, "consistency": 0.20, "matches": 0.15, "recent_form": 0.10, "dot_ball_percentage": 0.09},
        "Finisher": {"death_over_strike_rate": 0.30, "boundary_percentage": 0.23, "recent_form": 0.16, "strike_rate": 0.14, "consistency": 0.08, "matches": 0.09},
        "Spin Dominator": {"spin_strike_rate": 0.40, "batting_average": 0.18, "boundary_percentage": 0.14, "consistency": 0.12, "matches": 0.16},
        "Pace Dominator": {"pace_strike_rate": 0.40, "batting_average": 0.18, "boundary_percentage": 0.14, "consistency": 0.12, "matches": 0.16},
    },
    "BOWLERS": {
        "Wicket Taker": {"wickets_per_match": 0.30, "bowling_strike_rate": 0.24, "bowling_average": 0.18, "bowling_recent_form": 0.12, "matches": 0.09, "bowling_consistency": 0.07},
        "Economical Bowler": {"economy": 0.30, "dot_ball_percentage": 0.22, "boundary_percentage_conceded": 0.18, "bowling_consistency": 0.12, "matches": 0.10, "bowling_recent_form": 0.08},
        "Powerplay Specialist": {"powerplay_economy": 0.26, "powerplay_wickets_per_match": 0.24, "economy": 0.16, "dot_ball_percentage": 0.12, "wickets_per_match": 0.12, "matches": 0.10},
        "Death-Over Specialist": {"death_economy": 0.25, "death_wickets_per_match": 0.22, "death_boundary_percentage": 0.15, "death_dot_ball_percentage": 0.12, "bowling_strike_rate": 0.10, "bowling_recent_form": 0.08, "matches": 0.08},
        "Middle-Over Controller": {"middle_economy": 0.28, "middle_dot_ball_percentage": 0.22, "middle_wickets_per_match": 0.16, "economy": 0.12, "bowling_consistency": 0.12, "matches": 0.10},
        "Pace Specialist": {"wickets_per_match": 0.26, "bowling_strike_rate": 0.21, "bowling_average": 0.19, "economy": 0.14, "dot_ball_percentage": 0.10, "bowling_recent_form": 0.06, "matches": 0.04},
        "Spin Specialist": {"middle_economy": 0.23, "middle_wickets_per_match": 0.20, "economy": 0.18, "wickets_per_match": 0.15, "dot_ball_percentage": 0.12, "bowling_consistency": 0.07, "matches": 0.05},
        "Consistent Performer": {"bowling_consistency": 0.24, "matches": 0.20, "bowling_innings": 0.12, "economy": 0.14, "bowling_average": 0.12, "wickets_per_match": 0.10, "bowling_recent_form": 0.08},
    },
    "ALL_ROUNDERS": {
        "Batting All-Rounder": {"batting_average": 0.20, "strike_rate": 0.15, "boundary_percentage": 0.10, "batting_consistency": 0.10, "batting_recent_form": 0.10, "batting_sample": 0.05, "bowling_average": 0.10, "economy": 0.08, "wickets_per_match": 0.07, "bowling_sample": 0.05},
        "Bowling All-Rounder": {"bowling_average": 0.18, "economy": 0.15, "wickets_per_match": 0.12, "bowling_consistency": 0.10, "bowling_recent_form": 0.10, "bowling_sample": 0.05, "batting_average": 0.12, "strike_rate": 0.08, "batting_consistency": 0.06, "batting_sample": 0.04},
        "Balanced All-Rounder": {"batting_average": 0.13, "strike_rate": 0.10, "batting_consistency": 0.08, "batting_recent_form": 0.07, "batting_sample": 0.07, "bowling_average": 0.13, "economy": 0.10, "wickets_per_match": 0.10, "bowling_consistency": 0.08, "bowling_recent_form": 0.07, "bowling_sample": 0.07},
        "Impact All-Rounder": {"strike_rate": 0.13, "boundary_percentage": 0.08, "batting_recent_form": 0.10, "batting_consistency": 0.05, "wickets_per_match": 0.14, "bowling_strike_rate": 0.13, "bowling_recent_form": 0.10, "bowling_consistency": 0.07, "batting_sample": 0.10, "bowling_sample": 0.10},
    },
}

LOWER_IS_BETTER = {
    "dot_ball_percentage", "bowling_average", "economy", "boundary_percentage_conceded",
    "powerplay_economy", "middle_economy", "death_economy", "death_boundary_percentage",
    "death_dot_ball_percentage", "middle_dot_ball_percentage", "spin_average", "pace_average",
}


def percentile(value: Optional[float], values: List[float], lower_is_better: bool = False) -> Optional[float]:
    if value is None or not values:
        return None
    below = sum(1 for candidate in values if candidate < value)
    equal = sum(1 for candidate in values if candidate == value)
    rank = 100.0 * (below + 0.5 * equal) / len(values)
    return round(100.0 - rank if lower_is_better else rank, 1)


def score_cohort(records: List[dict], category: str, weights: Dict[str, float]) -> List[dict]:
    """Score complete cohort via weighted within-format percentiles; omit missing dimensions."""
    keys = set(weights)
    metric_scores = {key: {} for key in keys}
    for key in keys:
        distribution = [float(r[key]) for r in records if r.get(key) is not None]
        for record in records:
            metric_scores[key][record["player_id"]] = percentile(
                float(record[key]) if record.get(key) is not None else None,
                distribution,
                key in LOWER_IS_BETTER,
            )

    output = []
    for record in records:
        active = [(key, float(weight)) for key, weight in weights.items()
                  if weight > 0 and metric_scores.get(key, {}).get(record["player_id"]) is not None]
        weight_sum = sum(weight for _, weight in active)
        parts = {key: metric_scores[key][record["player_id"]] for key, _ in active}
        overall = sum(parts[key] * weight for key, weight in active) / weight_sum if weight_sum else 0.0
        bat_keys = [key for key in parts if key.startswith("batting_") or key in {"strike_rate", "boundary_percentage", "dot_ball_percentage", "pace_strike_rate", "pace_average", "spin_strike_rate", "spin_average", "powerplay_strike_rate", "middle_over_strike_rate", "death_over_strike_rate"}]
        bowl_keys = [key for key in parts if key not in bat_keys]
        best = sorted(parts.items(), key=lambda item: item[1], reverse=True)[:3]
        weak = sorted(parts.items(), key=lambda item: item[1])[:2]
        result = dict(record)
        bat_weight = sum(w for k, w in active if k in bat_keys)
        bowl_weight = sum(w for k, w in active if k in bowl_keys)
        bat_score = sum(parts[k] * w for k, w in active if k in bat_keys) / bat_weight if bat_weight else None
        bowl_score = sum(parts[k] * w for k, w in active if k in bowl_keys) / bowl_weight if bowl_weight else None
        if category == "BATTERS":
            bat_score, bowl_score = round(overall, 1), None
        elif category == "BOWLERS":
            bat_score, bowl_score = None, round(overall, 1)
        result.update(
            overall_score=round(overall, 1), suitability_score=round(overall, 1),
            batting_score=bat_score, bowling_score=bowl_score,
            metric_scores=parts,
            strengths=[f"{key.replace('_', ' ').title()} scored in the cohort's top range ({value:.0f}/100)" for key, value in best if value >= 65],
            limitations=[f"{key.replace('_', ' ').title()} scored in the lower range ({value:.0f}/100)" for key, value in weak if value <= 35],
        )
        if not result["strengths"]:
            result["strengths"] = ["No standout metric relative to this format cohort"]
        if not result["limitations"]:
            result["limitations"] = ["No major low-scoring metric relative to this cohort"]
        result["explanation"] = "Score is the weighted average of available metric percentiles within the selected format and filters; missing metrics are excluded and remaining weights are renormalized."
        output.append(result)
    return output
