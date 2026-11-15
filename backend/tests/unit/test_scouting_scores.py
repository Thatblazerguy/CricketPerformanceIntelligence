import pytest

from app.analytics.scouting import SCOUTING_PRESETS, score_cohort
from app.api.routes.scouting import ScoutingRequest


def test_batter_and_bowler_preset_weights_are_role_separate():
    assert "strike_rate" in SCOUTING_PRESETS["BATTERS"]["High Strike Rate"]
    assert "economy" in SCOUTING_PRESETS["BOWLERS"]["Economical Bowler"]
    assert "batting_average" not in SCOUTING_PRESETS["BOWLERS"]["Economical Bowler"]
    assert "economy" not in SCOUTING_PRESETS["BATTERS"]["High Strike Rate"]


def test_preset_weight_changes_can_change_candidate_order():
    rows = [
        {"player_id": "anchor", "batting_average": 60, "strike_rate": 110},
        {"player_id": "striker", "batting_average": 30, "strike_rate": 180},
    ]
    high_sr = score_cohort(rows, "BATTERS", {"strike_rate": 1})
    reliable = score_cohort(rows, "BATTERS", {"batting_average": 1})
    assert max(high_sr, key=lambda row: row["overall_score"])["player_id"] == "striker"
    assert max(reliable, key=lambda row: row["overall_score"])["player_id"] == "anchor"


def test_all_rounder_score_keeps_discipline_scores_separate_and_combined():
    rows = [
        {"player_id": "bat-heavy", "batting_average": 70, "strike_rate": 150, "bowling_average": 45, "economy": 9},
        {"player_id": "bowl-heavy", "batting_average": 25, "strike_rate": 80, "bowling_average": 18, "economy": 5},
    ]
    scored = score_cohort(rows, "ALL_ROUNDERS", {"batting_average": .25, "strike_rate": .25, "bowling_average": .25, "economy": .25})
    by_id = {row["player_id"]: row for row in scored}
    assert by_id["bat-heavy"]["batting_score"] > by_id["bat-heavy"]["bowling_score"]
    assert by_id["bowl-heavy"]["bowling_score"] > by_id["bowl-heavy"]["batting_score"]
    assert by_id["bat-heavy"]["overall_score"] == 50
    assert by_id["bowl-heavy"]["overall_score"] == 50


def test_missing_metrics_are_excluded_and_ties_are_neutral():
    rows = [
        {"player_id": "a", "strike_rate": 150, "economy": None},
        {"player_id": "b", "strike_rate": 150, "economy": 8},
    ]
    scored = score_cohort(rows, "BATTERS", {"strike_rate": 0.5, "economy": 0.5})
    assert scored[0]["overall_score"] == 50
    assert scored[0]["metric_scores"] == {"strike_rate": 50.0}


def test_formats_are_validated_and_never_silently_merged():
    assert ScoutingRequest(format="T20I").format != ScoutingRequest(format="T20").format
    with pytest.raises(ValueError):
        ScoutingRequest(format="T20+T20I")
