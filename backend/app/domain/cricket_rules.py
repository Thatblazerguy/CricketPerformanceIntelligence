"""
CPI Cricket Rules Engine
Central, authoritative implementation of cricket scoring rules.

All cricket-rule logic lives here. No other module should reimplement
legal-ball detection, dismissal classification, or phase assignment.
"""
from __future__ import annotations
from typing import Optional
from .enums import (
    DismissalKind,
    ExtraType,
    Phase,
    BOWLER_CREDITED_DISMISSALS,
    BATTER_DISMISSED_KINDS,
    NON_LEGAL_EXTRAS,
    BOWLING_EXCLUDED_EXTRAS,
    PHASE_BOUNDARIES,
)


def is_legal_delivery(extras: dict) -> bool:
    """
    Return True if the delivery is a legal ball.

    A delivery is NOT legal if the extras dict contains 'wides' or 'noballs'.
    Byes, leg-byes and penalty runs do not affect legality.

    Args:
        extras: The extras dict from a Cricsheet delivery record (may be empty).

    Returns:
        bool: True if legal.
    """
    return (
        ExtraType.WIDES not in extras
        and ExtraType.NOBALLS not in extras
    )


def is_ball_faced_by_batter(extras: dict) -> bool:
    """
    Return True if this delivery counts as a ball faced by the batter.

    Per scorecard convention: wides do NOT count as balls faced.
    No-balls DO count as balls faced (the batter had to face the delivery).

    Args:
        extras: The extras dict from a Cricsheet delivery record.

    Returns:
        bool: True if it counts as a ball faced.
    """
    return ExtraType.WIDES not in extras


def bowling_runs_for_delivery(batter_runs: int, extras: dict) -> int:
    """
    Calculate the runs conceded by the bowler on a delivery.

    Includes: batter runs, wides, no-balls.
    Excludes: byes, leg-byes, penalty.

    Args:
        batter_runs: Runs credited to the batter (delivery.runs.batter).
        extras: The extras dict from a Cricsheet delivery record.

    Returns:
        int: Runs charged to the bowler.
    """
    bowling_runs = batter_runs
    for extra_type, runs in extras.items():
        if extra_type not in BOWLING_EXCLUDED_EXTRAS and extra_type != ExtraType.PENALTY:
            bowling_runs += runs
    return bowling_runs


def is_bowler_wicket(dismissal_kind: str) -> bool:
    """
    Return True if the bowler receives wicket credit for this dismissal.

    Args:
        dismissal_kind: The 'kind' string from a Cricsheet wicket record.

    Returns:
        bool: True if the bowler should be credited.
    """
    try:
        kind = DismissalKind(dismissal_kind)
    except ValueError:
        return False
    return kind in BOWLER_CREDITED_DISMISSALS


def is_batter_dismissed(dismissal_kind: str) -> bool:
    """
    Return True if this dismissal counts for batting average purposes.

    'retired hurt' does NOT count as a dismissal.
    All other dismissal types (including retired out) do count.

    Args:
        dismissal_kind: The 'kind' string from a Cricsheet wicket record.

    Returns:
        bool: True if the batter is considered dismissed.
    """
    try:
        kind = DismissalKind(dismissal_kind)
    except ValueError:
        # Unknown dismissal kind — treat as dismissed (conservative approach)
        return True
    return kind in BATTER_DISMISSED_KINDS


PHASE_RULES = {
    "T20": ((0, 5), (6, 14), (15, 19)),
    "T20I": ((0, 5), (6, 14), (15, 19)),
    "ODI": ((0, 9), (10, 39), (40, 49)),
    "ODM": ((0, 9), (10, 39), (40, 49)),
}


def get_phase(over_index: int, is_super_over: bool = False, match_format: str = "T20") -> Phase:
    """
    Return the match phase for a given zero-based over index.

    Args:
        over_index: Zero-based over number (0–19 for standard T20).
        is_super_over: True if the innings is a super over.

    Returns:
        Phase enum value.
    """
    if is_super_over:
        return Phase.SUPER_OVER

    boundaries = PHASE_RULES.get(getattr(match_format, "value", match_format))
    if not boundaries:
        return Phase.UNKNOWN
    for phase, (start, end) in zip((Phase.POWERPLAY, Phase.MIDDLE, Phase.DEATH), boundaries):
        if start <= over_index <= end:
            return phase

    # Beyond 20 overs (unusual, e.g. miscounted overs or shortened match extensions)
    return Phase.UNKNOWN


def format_overs(legal_balls: int) -> str:
    """
    Format legal ball count as overs display string.

    E.g., 25 balls -> "4.1" (4 complete overs + 1 ball).
    Never stores decimal overs — this is display only.

    Args:
        legal_balls: Count of legal deliveries.

    Returns:
        str: Display string in "O.B" format.
    """
    complete_overs = legal_balls // 6
    remaining_balls = legal_balls % 6
    return f"{complete_overs}.{remaining_balls}"


def calculate_batting_average(runs: int, dismissals: int) -> Optional[float]:
    """
    Calculate batting average. Returns None if no dismissals (infinite average).

    Args:
        runs: Total batter runs.
        dismissals: Number of times dismissed.

    Returns:
        float or None.
    """
    if dismissals == 0:
        return None
    return round(runs / dismissals, 2)


def calculate_strike_rate(runs: int, balls_faced: int) -> Optional[float]:
    """
    Calculate batting strike rate per 100 balls. Returns None if no balls faced.

    Args:
        runs: Total batter runs.
        balls_faced: Balls faced by batter.

    Returns:
        float or None.
    """
    if balls_faced == 0:
        return None
    return round((runs / balls_faced) * 100, 2)


def calculate_economy_rate(runs_conceded: int, legal_balls: int) -> Optional[float]:
    """
    Calculate bowling economy rate (runs per over). Returns None if no legal balls.

    Args:
        runs_conceded: Runs conceded by the bowler.
        legal_balls: Legal deliveries bowled.

    Returns:
        float or None.
    """
    if legal_balls == 0:
        return None
    return round((runs_conceded / legal_balls) * 6, 2)


def calculate_bowling_average(runs_conceded: int, wickets: int) -> Optional[float]:
    """
    Calculate bowling average. Returns None if no wickets taken.

    Args:
        runs_conceded: Runs conceded by the bowler.
        wickets: Wickets credited to the bowler.

    Returns:
        float or None.
    """
    if wickets == 0:
        return None
    return round(runs_conceded / wickets, 2)


def calculate_bowling_strike_rate(legal_balls: int, wickets: int) -> Optional[float]:
    """
    Calculate bowling strike rate (balls per wicket). Returns None if no wickets.

    Args:
        legal_balls: Legal deliveries bowled.
        wickets: Wickets credited to the bowler.

    Returns:
        float or None.
    """
    if wickets == 0:
        return None
    return round(legal_balls / wickets, 2)


def calculate_percentage(numerator: int, denominator: int) -> Optional[float]:
    """
    Calculate a percentage. Returns None if denominator is zero.

    Args:
        numerator: Count of events.
        denominator: Total count.

    Returns:
        float or None.
    """
    if denominator == 0:
        return None
    return round((numerator / denominator) * 100, 2)


def normalise_season(season_raw) -> str:
    """
    Normalise Cricsheet season value to a consistent string.

    Cricsheet 'season' can be int (2024) or string ("2020/21").

    Args:
        season_raw: The raw season value from JSON.

    Returns:
        str: Normalised season string.
    """
    return str(season_raw).strip()
