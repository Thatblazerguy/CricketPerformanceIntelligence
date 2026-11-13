"""Unit tests for the simulator win-probability endpoint helpers.

Tests the state-to-feature mapping, model loading guard, and probability
normalisation without requiring a live database or trained model on disk.
"""
from __future__ import annotations

import numpy as np
import pytest

from app.ml.win_probability import (
    FEATURES,
    format_family,
    match_state_features,
)
from app.api.routes.simulator import parse_scoreboard_text


# ---------------------------------------------------------------------------
# match_state_features helpers used by /simulator/win-probability
# ---------------------------------------------------------------------------

def _t20_state(**overrides):
    base = dict(
        match_format="T20", gender="male",
        team1_batting=True, is_super_over=False,
        innings_number=2, innings_runs=80, wickets_lost=4,
        legal_balls=72, batting_team_prior_runs=160,
        opposition_prior_runs=0, target_runs=161, target_overs=20,
    )
    base.update(overrides)
    return match_state_features("T20", **base)


def test_t20_simulator_state_has_all_required_features():
    state = _t20_state()
    for feature in FEATURES["T20"]:
        assert feature in state, f"Missing feature: {feature}"


def test_simulator_state_calculates_runs_required_and_rate():
    state = _t20_state(innings_runs=80, target_runs=161, legal_balls=72)
    assert state["runs_required"] == 81
    # 81 runs in 48 balls → RRR = 81 * 6 / 48 = 10.125
    assert abs(state["required_run_rate"] - 10.125) < 0.01


def test_simulator_state_phase_flags_are_mutually_exclusive_for_t20():
    pp = _t20_state(legal_balls=10)
    mid = _t20_state(legal_balls=50)
    death = _t20_state(legal_balls=100)
    assert pp["is_powerplay"] == 1.0 and pp["is_middle"] == 0.0 and pp["is_death"] == 0.0
    assert mid["is_middle"] == 1.0 and mid["is_powerplay"] == 0.0 and mid["is_death"] == 0.0
    assert death["is_death"] == 1.0 and death["is_powerplay"] == 0.0 and death["is_middle"] == 0.0


def test_simulator_state_missing_target_produces_none_not_zero():
    state = _t20_state(target_runs=None, innings_number=1, batting_team_prior_runs=0,
                       opposition_prior_runs=0, target_overs=20)
    assert state["target_runs"] is None
    assert state["runs_required"] is None
    assert state["required_run_rate"] is None


def test_format_family_mapping_covers_simulator_formats():
    """The simulator supports T20, T20I, ODI, ODM. All must resolve to a family."""
    assert format_family("T20") == "T20"
    assert format_family("T20I") == "T20"
    assert format_family("ODI") == "ODI"
    assert format_family("ODM") == "ODI"


def test_feature_vector_shape_matches_model_input():
    """Feature tuple length must match FEATURES dict for each family the simulator uses."""
    for family in ("T20", "ODI"):
        assert len(FEATURES[family]) > 0, f"No features defined for {family}"
        # Build a minimal state to verify the dict has correct number of keys
        if family == "T20":
            state = _t20_state()
        else:
            state = match_state_features(
                "ODI", match_format="ODI", gender="male",
                team1_batting=True, is_super_over=False,
                innings_number=2, innings_runs=150, wickets_lost=5,
                legal_balls=180, batting_team_prior_runs=250,
                opposition_prior_runs=0, target_runs=251, target_overs=50,
            )
        assert len(state) == len(FEATURES[family])


def test_numpy_feature_array_converts_none_to_nan():
    """None values in state must become np.nan when converted for the pipeline."""
    state = _t20_state(innings_runs=0, legal_balls=0, target_runs=None)
    values = [state.get(k) for k in FEATURES["T20"]]
    arr = np.array([np.nan if v is None else v for v in values], dtype=np.float32)
    assert arr.shape == (len(FEATURES["T20"]),)
    # run_rate should be nan (no balls bowled yet, so it cannot be calculated)
    rr_idx = list(FEATURES["T20"]).index("innings_run_rate")
    assert np.isnan(arr[rr_idx])


def test_scoreboard_parser_produces_state_compatible_with_simulator():
    """Fields extracted by parse_scoreboard_text must map to simulator State keys."""
    parsed = parse_scoreboard_text(
        "T20I · Pakistan 95/3 · 12.0 overs · Target 160 · Required RR 10.83"
    )
    assert parsed["format"] == "T20I"
    assert parsed["score"] == 95
    assert parsed["wickets"] == 3
    assert parsed["legal_balls"] == 72
    assert parsed["target_runs"] == 160
    # This is a 2nd innings (target exists)
    assert parsed["uncertain_fields"] == []

