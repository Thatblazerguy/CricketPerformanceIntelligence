"""Metric eligibility: which data layer and fields each metric needs.

A metric is only computed from records that actually carry its inputs. Nothing is
approximated: a strike rate needs balls faced, a matchup needs deliveries.
"""
from __future__ import annotations

from typing import Dict, Iterable, Optional, Tuple

VERIFIED, DERIVED, INCOMPLETE, UNAVAILABLE = "verified", "derived", "incomplete", "unavailable"

BOTH = ("ball_by_ball", "scorecard")
BB_ONLY = ("ball_by_ball",)

RULES: Dict[str, Dict] = {
    # career aggregates: either layer, given the fields
    "matches": {"layers": BOTH, "fields": (), "derived": False},
    "innings": {"layers": BOTH, "fields": (), "derived": False},
    "runs": {"layers": BOTH, "fields": ("runs",), "derived": False},
    "not_outs": {"layers": BOTH, "fields": ("is_out",), "derived": False},
    "highest_score": {"layers": BOTH, "fields": ("runs",), "derived": False},
    "hundreds": {"layers": BOTH, "fields": ("runs",), "derived": False},
    "fifties": {"layers": BOTH, "fields": ("runs",), "derived": False},
    "batting_average": {"layers": BOTH, "fields": ("runs", "is_out"), "derived": True},
    "strike_rate": {"layers": BOTH, "fields": ("runs", "balls"), "derived": True},
    "fours": {"layers": BOTH, "fields": ("fours",), "derived": False},
    "sixes": {"layers": BOTH, "fields": ("sixes",), "derived": False},
    "wickets": {"layers": BOTH, "fields": ("wickets",), "derived": False},
    "runs_conceded": {"layers": BOTH, "fields": ("runs_conceded",), "derived": False},
    "balls_bowled": {"layers": BOTH, "fields": ("legal_balls",), "derived": False},
    "maidens": {"layers": BOTH, "fields": ("maidens",), "derived": False},
    "bowling_average": {"layers": BOTH, "fields": ("runs_conceded", "wickets"), "derived": True},
    "economy": {"layers": BOTH, "fields": ("runs_conceded", "legal_balls"), "derived": True},
    "bowling_strike_rate": {"layers": BOTH, "fields": ("legal_balls", "wickets"), "derived": True},
    # delivery-level analytics: ball-by-ball only, complete coverage only
    "bowler_batter_matchup": {"layers": BB_ONLY, "fields": ("deliveries",), "requires_full": True},
    "phase_analysis": {"layers": BB_ONLY, "fields": ("deliveries", "over_number"), "requires_full": True},
    "boundary_distribution": {"layers": BB_ONLY, "fields": ("deliveries",), "requires_full": True},
    "dismissal_patterns": {"layers": BB_ONLY, "fields": ("deliveries",), "requires_full": True},
    "delivery_strike_rate": {"layers": BB_ONLY, "fields": ("deliveries",), "requires_full": True},
    "predictive_features": {"layers": BB_ONLY, "fields": ("deliveries",), "requires_full": True},
    # match-level
    "venue_win_pct": {"layers": BOTH, "fields": ("result",), "derived": True},
    "toss_analysis": {"layers": BOTH, "fields": ("toss", "result"), "derived": True},
    # no CPI source carries shot location
    "wagon_wheel": {"layers": (), "fields": ("shot_location",), "unsupported": True},
}


def layer_allowed(metric: str, layer: str, coverage_status: Optional[str] = None) -> bool:
    rule = RULES[metric]
    if rule.get("unsupported") or layer not in rule["layers"]:
        return False
    if rule.get("requires_full"):
        return coverage_status == "FULL_BALL_BY_BALL"
    return True


def status_for(metric: str, eligible: int, total: int) -> str:
    """Status of a metric given how many contributing records carry its inputs."""
    rule = RULES[metric]
    if rule.get("unsupported") or eligible == 0:
        return UNAVAILABLE
    if eligible < total:
        return INCOMPLETE
    return DERIVED if rule.get("derived") else VERIFIED


def records_with(records: Iterable[Dict], fields: Tuple[str, ...]):
    return [r for r in records if all(r.get(f) is not None for f in fields)]
