import numpy as np

from app.domain.enums import ResultType
from app.ml.win_probability import FEATURES, format_family, match_state_features, multiclass_metrics, result_label
from scripts.build_win_probability import _predict_three, _walk_match


def _state(family, **overrides):
    values = dict(
        match_format="T20", gender="male", team1_batting=True, is_super_over=False,
        innings_number=2, innings_runs=60, wickets_lost=3, legal_balls=60,
        batting_team_prior_runs=100, opposition_prior_runs=0, target_runs=181, target_overs=20,
    )
    values.update(overrides)
    return match_state_features(family, **values)


def test_format_families_cover_limited_and_multiday_formats():
    assert format_family("T20I") == "T20"
    assert format_family("ODM") == "ODI"
    assert format_family("MDM") == "Test"
    assert format_family("Other") is None


def test_test_features_are_multiday_and_do_not_invent_remaining_balls():
    state = _state("Test", match_format="Test", innings_number=4, target_runs=None,
                   target_overs=None, legal_balls=450, team1_batting=False,
                   batting_team_prior_runs=500, opposition_prior_runs=300)
    assert "balls_remaining" not in state
    assert "target_runs" not in state
    assert "lead_from_team1" in FEATURES["Test"]
    assert state["lead_from_team1"] == -260
    assert "required_run_rate" not in state
    assert state["is_test_match"] == 1.0


def test_limited_overs_targets_and_super_overs_are_format_aware():
    t20 = _state("T20", legal_balls=6, target_runs=181)
    odi = _state("ODI", match_format="ODI", legal_balls=6, target_runs=181, target_overs=50)
    super_over = _state("T20", legal_balls=3, is_super_over=True, target_runs=11, target_overs=1)
    assert t20["balls_remaining"] == 114
    assert odi["balls_remaining"] == 294
    assert super_over["balls_remaining"] == 3
    assert t20["runs_required"] == 121


def test_result_labels_keep_draw_and_no_result_distinct():
    assert result_label("win", "a", "a") == 0
    assert result_label("win", "b", "a") == 1
    assert result_label("tie", None, "a") == 2
    assert result_label("no result", None, "a") is None
    assert ResultType("draw") is ResultType.DRAW


def test_missing_values_are_preserved_for_imputation_not_converted_to_zero():
    state = _state("T20", legal_balls=0, target_runs=None)
    assert state["innings_run_rate"] is None
    assert state["target_runs"] is None
    assert state["required_run_rate"] is None


def test_phase_features_use_format_specific_over_boundaries():
    t20_pp = _state("T20", legal_balls=35)
    t20_middle = _state("T20", legal_balls=36)
    odi_pp = _state("ODI", match_format="ODI", legal_balls=59, target_overs=50)
    odi_middle = _state("ODI", match_format="ODI", legal_balls=60, target_overs=50)
    odi_death = _state("ODI", match_format="ODI", legal_balls=240, target_overs=50)
    assert (t20_pp["is_powerplay"], t20_middle["is_middle"]) == (1.0, 1.0)
    assert odi_pp["is_powerplay"] == 1.0
    assert odi_middle["is_middle"] == 1.0
    assert odi_death["is_death"] == 1.0


def test_multiclass_metrics_report_fixed_three_outcome_probabilities():
    metrics = multiclass_metrics(np.array([0, 1, 2]), np.eye(3) * .9 + (np.ones((3, 3)) - np.eye(3)) * .05)
    assert metrics["samples"] == 3
    assert metrics["accuracy"] == 1.0
    assert set(metrics["calibration"]) == {"team1_win", "team2_win", "draw_or_tie"}


def test_probability_adapter_returns_normalized_three_class_probabilities():
    from sklearn.linear_model import LogisticRegression

    model = LogisticRegression().fit(np.array([[0.], [1.], [2.], [3.], [4.], [5.]]), np.array([0, 0, 1, 1, 2, 2]))
    probabilities = _predict_three(model, np.array([[.5], [2.5], [4.5]]))
    assert probabilities.shape == (3, 3)
    assert np.allclose(probabilities.sum(axis=1), 1.0, atol=1e-12)
    assert np.isfinite(probabilities).all()


def test_pre_delivery_state_excludes_current_ball_and_post_state_includes_it():
    base = dict(
        match_id="m", match_format="T20", gender="male", start_date=None,
        team1_id="a", team2_id="b", winner_id="a", result_type="win",
        innings_id="i", innings_number=1, batting_team_id="a", target_runs=None,
        target_overs=20, is_super_over=False, batter_id="p", bowler_id="q",
        over_number=0, is_legal_ball=True, is_boundary_four=False, is_boundary_six=False,
        wickets=0,
    )
    rows = [
        {**base, "delivery_id": "d1", "delivery_sequence": 0, "total_runs": 1},
        {**base, "delivery_id": "d2", "delivery_sequence": 1, "total_runs": 4, "is_boundary_four": True},
    ]
    label, _, states = _walk_match(rows, "T20")
    assert label == 0
    assert states[0][0]["score"] == 0
    assert states[0][1]["score"] == 1
    assert states[1][0]["score"] == 1
    assert states[1][1]["score"] == 5
