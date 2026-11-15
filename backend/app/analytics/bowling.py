"""Analytics Engine — Bowling Statistics"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Dict

from app.domain.cricket_rules import (
    calculate_economy_rate,
    calculate_bowling_average,
    calculate_bowling_strike_rate,
    calculate_percentage,
    format_overs,
)
from app.domain.enums import Phase


@dataclass
class BowlingLine:
    """Single delivery from bowler perspective."""
    innings_id: str
    over_number: int
    delivery_sequence: int
    bowling_runs: int          # Runs charged to the bowler
    is_legal_ball: bool
    is_boundary_conceded: bool # Batter scored 4 or 6
    is_dot_ball: bool          # Legal ball, batter scored 0
    bowler_wicket: bool        # Bowler credited with this dismissal
    phase: Phase
    is_super_over: bool


@dataclass
class BowlingStats:
    """Aggregated bowling statistics."""
    player_id: str
    matches: int = 0
    innings_bowled: int = 0
    legal_balls: int = 0
    runs_conceded: int = 0
    wickets: int = 0
    dot_balls: int = 0
    boundary_deliveries: int = 0  # Legal balls where batter scored 4 or 6

    @property
    def overs_display(self) -> str:
        return format_overs(self.legal_balls)

    @property
    def economy_rate(self) -> Optional[float]:
        return calculate_economy_rate(self.runs_conceded, self.legal_balls)

    @property
    def bowling_average(self) -> Optional[float]:
        return calculate_bowling_average(self.runs_conceded, self.wickets)

    @property
    def bowling_strike_rate(self) -> Optional[float]:
        return calculate_bowling_strike_rate(self.legal_balls, self.wickets)

    @property
    def dot_ball_percentage(self) -> Optional[float]:
        return calculate_percentage(self.dot_balls, self.legal_balls)

    @property
    def boundary_percentage(self) -> Optional[float]:
        return calculate_percentage(self.boundary_deliveries, self.legal_balls)


@dataclass
class PhaseBowlingStats:
    """Phase-specific bowling breakdown."""
    phase: Phase
    legal_balls: int = 0
    runs_conceded: int = 0
    wickets: int = 0
    dot_balls: int = 0
    boundary_deliveries: int = 0

    @property
    def economy_rate(self) -> Optional[float]:
        return calculate_economy_rate(self.runs_conceded, self.legal_balls)

    @property
    def bowling_average(self) -> Optional[float]:
        return calculate_bowling_average(self.runs_conceded, self.wickets)

    @property
    def dot_ball_percentage(self) -> Optional[float]:
        return calculate_percentage(self.dot_balls, self.legal_balls)

    @property
    def boundary_percentage(self) -> Optional[float]:
        return calculate_percentage(self.boundary_deliveries, self.legal_balls)


def calculate_bowling_stats(
    lines: List[BowlingLine], player_id: str
) -> BowlingStats:
    """
    Calculate aggregate bowling statistics from BowlingLine records.

    Args:
        lines: All deliveries bowled by the player.
        player_id: Internal player ID.

    Returns:
        BowlingStats.
    """
    stats = BowlingStats(player_id=player_id)
    innings_seen: set = set()

    for dl in lines:
        if dl.is_super_over:
            continue
        innings_seen.add(dl.innings_id)
        stats.runs_conceded += dl.bowling_runs
        if dl.is_legal_ball:
            stats.legal_balls += 1
            if dl.is_dot_ball:
                stats.dot_balls += 1
            if dl.is_boundary_conceded:
                stats.boundary_deliveries += 1
        if dl.bowler_wicket:
            stats.wickets += 1

    stats.innings_bowled = len(innings_seen)
    return stats


def calculate_phase_bowling_stats(
    lines: List[BowlingLine], player_id: str
) -> Dict[Phase, PhaseBowlingStats]:
    """Break down bowling statistics by match phase."""
    phase_stats: Dict[Phase, PhaseBowlingStats] = {
        Phase.POWERPLAY: PhaseBowlingStats(phase=Phase.POWERPLAY),
        Phase.MIDDLE: PhaseBowlingStats(phase=Phase.MIDDLE),
        Phase.DEATH: PhaseBowlingStats(phase=Phase.DEATH),
    }

    for dl in lines:
        if dl.is_super_over:
            continue
        if dl.phase not in phase_stats:
            continue

        ps = phase_stats[dl.phase]
        ps.runs_conceded += dl.bowling_runs
        if dl.is_legal_ball:
            ps.legal_balls += 1
            if dl.is_dot_ball:
                ps.dot_balls += 1
            if dl.is_boundary_conceded:
                ps.boundary_deliveries += 1
        if dl.bowler_wicket:
            ps.wickets += 1

    return phase_stats

