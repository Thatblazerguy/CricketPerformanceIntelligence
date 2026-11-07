"""Analytics Engine — Batting Statistics

All calculations are deterministic and work directly on delivery-level data.
No FastAPI request state. No hardcoded results.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Dict

from app.domain.cricket_rules import (
    calculate_batting_average,
    calculate_strike_rate,
    calculate_percentage,
)
from app.domain.enums import Phase


@dataclass
class BattingLine:
    """
    Represents a single delivery from the perspective of the batter.
    Extracted from canonical delivery records.
    """
    innings_id: str
    over_number: int
    delivery_sequence: int
    batter_runs: int
    is_legal_ball: bool
    is_ball_faced: bool
    is_boundary_four: bool
    is_boundary_six: bool
    phase: Phase
    was_dismissed: bool          # True if this batter was dismissed on this delivery
    is_super_over: bool


@dataclass
class BattingStats:
    """Aggregated batting statistics for one player over a filtered set of matches."""
    player_id: str
    matches: int = 0
    innings: int = 0
    not_outs: int = 0
    runs: int = 0
    balls_faced: int = 0
    dismissals: int = 0
    highest_score: int = 0
    fours: int = 0
    sixes: int = 0
    dot_balls: int = 0           # Legal balls where batter scored 0
    boundary_deliveries: int = 0 # Legal balls that resulted in a 4 or 6

    # Computed on demand
    @property
    def average(self) -> Optional[float]:
        return calculate_batting_average(self.runs, self.dismissals)

    @property
    def strike_rate(self) -> Optional[float]:
        return calculate_strike_rate(self.runs, self.balls_faced)

    @property
    def boundary_percentage(self) -> Optional[float]:
        return calculate_percentage(self.boundary_deliveries, self.balls_faced)

    @property
    def dot_ball_percentage(self) -> Optional[float]:
        return calculate_percentage(self.dot_balls, self.balls_faced)

    @property
    def six_percentage(self) -> Optional[float]:
        return calculate_percentage(self.sixes, self.balls_faced)

    @property
    def four_percentage(self) -> Optional[float]:
        return calculate_percentage(self.fours, self.balls_faced)


@dataclass
class PhaseBattingStats:
    """Phase-specific batting breakdown."""
    phase: Phase
    runs: int = 0
    balls_faced: int = 0
    dismissals: int = 0
    fours: int = 0
    sixes: int = 0
    dot_balls: int = 0
    boundary_deliveries: int = 0

    @property
    def strike_rate(self) -> Optional[float]:
        return calculate_strike_rate(self.runs, self.balls_faced)

    @property
    def average(self) -> Optional[float]:
        return calculate_batting_average(self.runs, self.dismissals)

    @property
    def dot_ball_percentage(self) -> Optional[float]:
        return calculate_percentage(self.dot_balls, self.balls_faced)

    @property
    def boundary_percentage(self) -> Optional[float]:
        return calculate_percentage(self.boundary_deliveries, self.balls_faced)


def calculate_batting_stats(
    lines: List[BattingLine], player_id: str
) -> BattingStats:
    """
    Calculate aggregate batting statistics from a list of BattingLine records.

    Args:
        lines: All deliveries where the player was the facing batter.
        player_id: Internal player ID for the stats object.

    Returns:
        BattingStats with all metrics populated.
    """
    stats = BattingStats(player_id=player_id)

    # Group by innings to calculate innings-level statistics
    innings_groups: Dict[str, List[BattingLine]] = {}
    for line in lines:
        if line.is_super_over:
            continue  # Exclude super overs
        innings_groups.setdefault(line.innings_id, []).append(line)

    stats.innings = len(innings_groups)
    highest = 0

    match_ids_seen: set = set()

    for inn_id, inn_lines in innings_groups.items():
        inn_runs = 0
        was_dismissed_in_innings = False

        for dl in inn_lines:
            if dl.is_ball_faced:
                stats.balls_faced += 1

            stats.runs += dl.batter_runs
            inn_runs += dl.batter_runs

            if dl.is_ball_faced and dl.batter_runs == 0 and dl.is_legal_ball:
                stats.dot_balls += 1

            if dl.is_boundary_four and dl.is_ball_faced:
                stats.fours += 1
                stats.boundary_deliveries += 1
            elif dl.is_boundary_six and dl.is_ball_faced:
                stats.sixes += 1
                stats.boundary_deliveries += 1

            if dl.was_dismissed:
                was_dismissed_in_innings = True

        highest = max(highest, inn_runs)

        if was_dismissed_in_innings:
            stats.dismissals += 1
        else:
            stats.not_outs += 1

    stats.highest_score = highest
    return stats


def calculate_phase_batting_stats(
    lines: List[BattingLine], player_id: str
) -> Dict[Phase, PhaseBattingStats]:
    """
    Break down batting statistics by match phase.

    Args:
        lines: All deliveries where the player was the facing batter.
        player_id: Internal player ID.

    Returns:
        Dict mapping Phase to PhaseBattingStats.
    """
    phase_stats: Dict[Phase, PhaseBattingStats] = {
        Phase.POWERPLAY: PhaseBattingStats(phase=Phase.POWERPLAY),
        Phase.MIDDLE: PhaseBattingStats(phase=Phase.MIDDLE),
        Phase.DEATH: PhaseBattingStats(phase=Phase.DEATH),
    }

    # Track dismissals by phase per innings
    innings_phase_dismissed: Dict[tuple, bool] = {}

    for dl in lines:
        if dl.is_super_over:
            continue
        if dl.phase not in phase_stats:
            continue

        ps = phase_stats[dl.phase]

        if dl.is_ball_faced:
            ps.balls_faced += 1
        ps.runs += dl.batter_runs

        if dl.is_legal_ball and dl.is_ball_faced and dl.batter_runs == 0:
            ps.dot_balls += 1

        if dl.is_ball_faced:
            if dl.is_boundary_four:
                ps.fours += 1
                ps.boundary_deliveries += 1
            elif dl.is_boundary_six:
                ps.sixes += 1
                ps.boundary_deliveries += 1

        if dl.was_dismissed:
            key = (dl.innings_id, dl.phase)
            if not innings_phase_dismissed.get(key):
                innings_phase_dismissed[key] = True
                ps.dismissals += 1

    return phase_stats

