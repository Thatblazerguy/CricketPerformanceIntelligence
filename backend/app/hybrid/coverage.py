"""Match coverage classification.

A scorecard can never yield FULL_BALL_BY_BALL, and a match with missing or
gapped delivery data is PARTIAL rather than silently treated as complete.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

from app.hybrid.formats import is_limited_overs

FULL = "FULL_BALL_BY_BALL"
PARTIAL = "PARTIAL_BALL_BY_BALL"
SCORECARD = "SCORECARD_ONLY"
METADATA = "METADATA_ONLY"
UNKNOWN = "UNKNOWN"
STATUSES = (FULL, PARTIAL, SCORECARD, METADATA, UNKNOWN)

LABELS = {
    FULL: "FULL MATCH DATA",
    PARTIAL: "PARTIAL MATCH DATA",
    SCORECARD: "SCORECARD DATA",
    METADATA: "COVERAGE UNVERIFIED",
    UNKNOWN: "COVERAGE UNVERIFIED",
}

# Fields whose absence from the source is worth surfacing but does not affect
# delivery-level completeness (Cricsheet info.missing markers).
METADATA_ONLY_GAPS = {"player_of_match", "umpires", "powerplays", "reviews", "impact_players", "officials"}


@dataclass
class InningsEvidence:
    innings_number: int
    deliveries: int = 0
    overs_present: int = 0        # distinct over numbers with at least one delivery
    max_over: Optional[int] = None  # zero-based highest over number
    forfeited: bool = False
    is_super_over: bool = False


# Results reached without the match being played out (no second innings is owed).
NOT_PLAYED_OUT = {"awarded", "conceded", "forfeited"}


def expected_innings(format_class: str, result_type: Optional[str], result_method: Optional[str] = None) -> Optional[int]:
    """Regular innings a completed match must contain, when that is knowable.

    Limited-overs matches decided by a win or tie need both innings, unless the
    result was awarded/conceded. Multi-day matches can legitimately end after
    2, 3 or 4 innings, so no number is implied.
    """
    if (result_method or "").strip().lower() in NOT_PLAYED_OUT:
        return None
    if is_limited_overs(format_class) and result_type in ("win", "tie"):
        return 2
    return None


def classify(
    innings: Sequence[InningsEvidence],
    *,
    has_ball_by_ball_source: bool,
    has_scorecard: bool,
    expected: Optional[int],
) -> Tuple[str, List[str]]:
    """Return (coverage_status, human-readable notes)."""
    notes: List[str] = []
    regular = [i for i in innings if not i.is_super_over]
    if has_ball_by_ball_source and regular:
        problems = False
        for inn in regular:
            if inn.deliveries == 0 and not inn.forfeited:
                notes.append(f"Innings {inn.innings_number} has no deliveries")
                problems = True
            elif inn.max_over is not None and inn.overs_present < inn.max_over + 1:
                gap = inn.max_over + 1 - inn.overs_present
                notes.append(f"Innings {inn.innings_number} is missing {gap} over(s) of deliveries")
                problems = True
        if expected is not None and len(regular) < expected:
            notes.append(f"{len(regular)} of {expected} expected innings present")
            problems = True
        if any(i.forfeited for i in regular):
            notes.append("Contains a forfeited innings (no deliveries by design)")
        if expected is None and len(regular) == 1 and not problems:
            notes.append("Single innings recorded; no further innings were owed for this result")
        return (PARTIAL if problems else FULL), notes
    if has_ball_by_ball_source and not regular:
        notes.append("Ball-by-ball source lists the match but holds no innings (e.g. abandoned)")
        return (SCORECARD if has_scorecard else METADATA), notes
    if has_scorecard:
        return SCORECARD, notes
    return UNKNOWN, notes


def worst(statuses: Sequence[str]) -> str:
    order = {FULL: 0, PARTIAL: 1, SCORECARD: 2, METADATA: 3, UNKNOWN: 4}
    return max(statuses, key=lambda s: order.get(s, 4)) if statuses else UNKNOWN
