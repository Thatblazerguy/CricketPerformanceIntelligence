"""
Unit tests for cricket_rules.py
Tests the authoritative cricket rule implementations.
"""
import pytest
from app.domain.cricket_rules import (
    is_legal_delivery,
    is_ball_faced_by_batter,
    bowling_runs_for_delivery,
    is_bowler_wicket,
    is_batter_dismissed,
    get_phase,
    format_overs,
    calculate_batting_average,
    calculate_strike_rate,
    calculate_economy_rate,
    calculate_bowling_average,
    calculate_bowling_strike_rate,
    calculate_percentage,
    normalise_season,
)
from app.domain.enums import Phase


# ============================================================
# Legal Ball Tests
# ============================================================

class TestIsLegalDelivery:
    def test_no_extras_is_legal(self):
        assert is_legal_delivery({}) is True

    def test_byes_only_is_legal(self):
        assert is_legal_delivery({"byes": 4}) is True

    def test_legbyes_only_is_legal(self):
        assert is_legal_delivery({"legbyes": 1}) is True

    def test_penalty_only_is_legal(self):
        assert is_legal_delivery({"penalty": 5}) is True

    def test_wide_is_not_legal(self):
        assert is_legal_delivery({"wides": 1}) is False

    def test_wide_with_byes_is_not_legal(self):
        assert is_legal_delivery({"wides": 1, "byes": 2}) is False

    def test_noball_is_not_legal(self):
        assert is_legal_delivery({"noballs": 1}) is False

    def test_noball_with_batter_runs_is_not_legal(self):
        assert is_legal_delivery({"noballs": 1}) is False

    def test_byes_and_legbyes_legal(self):
        assert is_legal_delivery({"byes": 1, "legbyes": 2}) is True


# ============================================================
# Balls Faced Tests
# ============================================================

class TestIsBallFacedByBatter:
    def test_normal_delivery_is_faced(self):
        assert is_ball_faced_by_batter({}) is True

    def test_noball_counts_as_faced(self):
        assert is_ball_faced_by_batter({"noballs": 1}) is True

    def test_bye_counts_as_faced(self):
        assert is_ball_faced_by_batter({"byes": 4}) is True

    def test_wide_does_not_count(self):
        assert is_ball_faced_by_batter({"wides": 1}) is False

    def test_wide_with_runs_does_not_count(self):
        assert is_ball_faced_by_batter({"wides": 2}) is False


# ============================================================
# Bowling Runs Tests
# ============================================================

class TestBowlingRunsForDelivery:
    def test_batter_runs_only(self):
        assert bowling_runs_for_delivery(4, {}) == 4

    def test_zero_batter_zero_extras(self):
        assert bowling_runs_for_delivery(0, {}) == 0

    def test_wide_adds_to_bowling_runs(self):
        assert bowling_runs_for_delivery(0, {"wides": 1}) == 1

    def test_wide_with_runs(self):
        # Wide that goes for 2 (overthrow)
        assert bowling_runs_for_delivery(0, {"wides": 2}) == 2

    def test_noball_adds_to_bowling_runs(self):
        assert bowling_runs_for_delivery(0, {"noballs": 1}) == 1

    def test_noball_plus_batter_runs(self):
        # No-ball where batter hits 4
        assert bowling_runs_for_delivery(4, {"noballs": 1}) == 5

    def test_byes_excluded_from_bowling_runs(self):
        assert bowling_runs_for_delivery(0, {"byes": 4}) == 0

    def test_legbyes_excluded_from_bowling_runs(self):
        assert bowling_runs_for_delivery(0, {"legbyes": 1}) == 0

    def test_byes_on_wide(self):
        # Wide with byes: wides charged to bowler, byes not
        assert bowling_runs_for_delivery(0, {"wides": 1, "byes": 1}) == 1


# ============================================================
# Wicket Credit Tests
# ============================================================

class TestIsBowlerWicket:
    @pytest.mark.parametrize("kind", [
        "bowled", "caught", "caught and bowled", "lbw", "stumped", "hit wicket"
    ])
    def test_bowler_credited_dismissals(self, kind):
        assert is_bowler_wicket(kind) is True

    @pytest.mark.parametrize("kind", [
        "run out", "obstructing the field", "retired hurt", "retired out"
    ])
    def test_non_bowler_dismissals(self, kind):
        assert is_bowler_wicket(kind) is False

    def test_unknown_kind_returns_false(self):
        assert is_bowler_wicket("some_unknown_type") is False


# ============================================================
# Batter Dismissed Tests
# ============================================================

class TestIsBatterDismissed:
    @pytest.mark.parametrize("kind", [
        "bowled", "caught", "caught and bowled", "lbw", "stumped",
        "hit wicket", "run out", "obstructing the field", "retired out"
    ])
    def test_dismissed_kinds(self, kind):
        assert is_batter_dismissed(kind) is True

    def test_retired_hurt_not_dismissed(self):
        assert is_batter_dismissed("retired hurt") is False


# ============================================================
# Phase Assignment Tests
# ============================================================

class TestGetPhase:
    @pytest.mark.parametrize("over_idx", [0, 1, 2, 3, 4, 5])
    def test_powerplay_overs(self, over_idx):
        assert get_phase(over_idx) == Phase.POWERPLAY

    @pytest.mark.parametrize("over_idx", [6, 7, 10, 13, 14])
    def test_middle_overs(self, over_idx):
        assert get_phase(over_idx) == Phase.MIDDLE

    @pytest.mark.parametrize("over_idx", [15, 16, 17, 18, 19])
    def test_death_overs(self, over_idx):
        assert get_phase(over_idx) == Phase.DEATH

    def test_super_over(self):
        assert get_phase(0, is_super_over=True) == Phase.SUPER_OVER

    def test_beyond_20_overs_unknown(self):
        assert get_phase(20) == Phase.UNKNOWN

    def test_odi_uses_50_over_boundaries(self):
        assert get_phase(9, match_format="ODI") == Phase.POWERPLAY
        assert get_phase(10, match_format="ODI") == Phase.MIDDLE
        assert get_phase(39, match_format="ODI") == Phase.MIDDLE
        assert get_phase(40, match_format="ODI") == Phase.DEATH

    def test_test_format_does_not_use_limited_overs_phases(self):
        assert get_phase(0, match_format="Test") == Phase.UNKNOWN

    def test_domestic_one_day_uses_odi_boundaries(self):
        assert get_phase(40, match_format="ODM") == Phase.DEATH


# ============================================================
# Format Overs Tests
# ============================================================

class TestFormatOvers:
    def test_complete_overs(self):
        assert format_overs(24) == "4.0"

    def test_overs_with_balls(self):
        assert format_overs(25) == "4.1"

    def test_zero_balls(self):
        assert format_overs(0) == "0.0"

    def test_full_20_overs(self):
        assert format_overs(120) == "20.0"

    def test_partial_last_over(self):
        assert format_overs(119) == "19.5"


# ============================================================
# Statistical Calculation Tests
# ============================================================

class TestBattingAverage:
    def test_normal_average(self):
        assert calculate_batting_average(300, 10) == 30.0

    def test_zero_dismissals_returns_none(self):
        assert calculate_batting_average(50, 0) is None

    def test_zero_runs(self):
        assert calculate_batting_average(0, 5) == 0.0

    def test_rounding(self):
        result = calculate_batting_average(100, 3)
        assert result == 33.33


class TestStrikeRate:
    def test_normal_strike_rate(self):
        assert calculate_strike_rate(50, 40) == 125.0

    def test_zero_balls_returns_none(self):
        assert calculate_strike_rate(50, 0) is None


class TestEconomyRate:
    def test_normal_economy(self):
        # 24 runs in 24 balls = 4.0 balls/run-equivalent; economy = 24/24*6 = 6.0
        assert calculate_economy_rate(24, 24) == 6.0

    def test_zero_balls_returns_none(self):
        assert calculate_economy_rate(10, 0) is None

    def test_economy_calculation(self):
        # 30 runs in 18 balls (3 overs): economy = 30/18*6 = 10.0
        assert calculate_economy_rate(30, 18) == 10.0


class TestBowlingAverage:
    def test_normal_bowling_average(self):
        assert calculate_bowling_average(100, 5) == 20.0

    def test_zero_wickets_returns_none(self):
        assert calculate_bowling_average(100, 0) is None


class TestBowlingStrikeRate:
    def test_normal_bowling_strike_rate(self):
        assert calculate_bowling_strike_rate(30, 5) == 6.0

    def test_zero_wickets_returns_none(self):
        assert calculate_bowling_strike_rate(30, 0) is None


class TestNormaliseSeason:
    def test_int_season(self):
        assert normalise_season(2024) == "2024"

    def test_string_season(self):
        assert normalise_season("2020/21") == "2020/21"

    def test_already_string(self):
        assert normalise_season("2017") == "2017"
