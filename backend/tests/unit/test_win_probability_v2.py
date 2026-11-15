"""Correctness tests for the v2 win-probability engine.

Pure-logic tests (orientation, labels, terminal rules, partitions, Elo/par leakage,
resource table) need no database. Model sanity tests load the trained bundles and
are skipped when ``artifacts/win_probability/v2`` has not been built.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.ml.wp import context, features as F, modeling as M
from app.ml.wp.engine import ARTIFACT_DIR, WinProbabilityEngine


# --------------------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------------------

def _matches(rows):
    base = dict(gender="male", match_format="T20", venue_id="v1", tournament_id=None, toss_winner_id="a",
                toss_decision="bat", winner_id=None, result_type="win")
    frame = pd.DataFrame([{**base, **r} for r in rows])
    frame["start_date"] = pd.to_datetime(frame["start_date"])
    return frame


def _toy_match(winner="b", first_batting="a", target_runs=None):
    """One T20 match: team ``first_batting`` makes 3 off 2 balls, the other side chases."""
    matches = _matches([dict(match_id="m1", start_date="2020-01-01", team1_id="a", team2_id="b", winner_id=winner)])
    second = "b" if first_batting == "a" else "a"
    innings = pd.DataFrame([
        dict(innings_id="i1", match_id="m1", innings_number=1, batting_team_id=first_batting, target_runs=None,
             target_overs=None, is_super_over=0, runs=3, legal_balls=2, wickets=0),
        dict(innings_id="i2", match_id="m1", innings_number=2, batting_team_id=second, target_runs=target_runs,
             target_overs=None, is_super_over=0, runs=4, legal_balls=1, wickets=0),
    ])
    deliveries = pd.DataFrame([
        dict(innings_id="i1", over_number=0, delivery_sequence=0, batter_id="p", bowler_id="q", total_runs=1, legal=1, boundary=0, wickets=0),
        dict(innings_id="i1", over_number=0, delivery_sequence=1, batter_id="p", bowler_id="q", total_runs=2, legal=1, boundary=0, wickets=0),
        dict(innings_id="i2", over_number=0, delivery_sequence=0, batter_id="r", bowler_id="s", total_runs=4, legal=1, boundary=1, wickets=0),
    ])
    elo, _ = context.compute_elo(matches)
    pars, _ = context.compute_pars(matches, innings)
    table = F.build_match_table(matches, elo, pars)
    frame = F.add_innings_context(F.delivery_frame(deliveries, innings, table), innings)
    return frame


# --------------------------------------------------------------------------------------
# Orientation and labels
# --------------------------------------------------------------------------------------

@pytest.mark.parametrize("first_batting", ["a", "b"])
@pytest.mark.parametrize("winner", ["a", "b"])
def test_batting_side_labels_follow_the_batting_team_not_team1(first_batting, winner):
    frame = _toy_match(winner=winner, first_batting=first_batting)
    for row in frame.itertuples():
        assert row.batting_is_team1 == (row.batting_team_id == "a")
        assert row.label_bat_win == float(row.batting_team_id == winner)
        assert row.label_multi == (0 if row.batting_team_id == winner else 1)


def test_orient_to_team1_maps_batting_probability_to_the_right_team():
    t1, t2, dr = F.orient_to_team1([0.8, 0.8], [True, False])
    assert np.allclose(t1, [0.8, 0.2]) and np.allclose(t2, [0.2, 0.8]) and np.allclose(dr, 0)
    t1, t2, dr = F.orient_to_team1([0.5], [False], bowling_win=[0.3], draw=[0.2])
    assert (t1[0], t2[0], dr[0]) == (0.3, 0.5, 0.2)


def test_result_labels_ties_draws_and_no_results():
    m = _matches([
        dict(match_id="w", start_date="2020-01-01", team1_id="a", team2_id="b", winner_id="a"),
        dict(match_id="t", start_date="2020-01-02", team1_id="a", team2_id="b", result_type="tie"),
        dict(match_id="d", start_date="2020-01-03", team1_id="a", team2_id="b", result_type="draw", match_format="Test"),
        dict(match_id="n", start_date="2020-01-04", team1_id="a", team2_id="b", result_type="no result"),
        dict(match_id="x", start_date="2020-01-05", team1_id="a", team2_id="b", winner_id="zzz"),
    ])
    elo, _ = context.compute_elo(m)
    t = F.build_match_table(m, elo, pd.DataFrame({"match_id": m["match_id"], "era_par": np.nan, "venue_par": np.nan,
                                                  "venue_innings": 0})).set_index("match_id")
    assert t.loc["w", "has_winner"] and not t.loc["w", "is_tie"]
    assert t.loc["t", "is_tie"] and not t.loc["t", "has_winner"]
    assert t.loc["d", "is_draw"]
    assert not (t.loc["n", "has_winner"] or t.loc["n", "is_tie"] or t.loc["n", "is_draw"])
    assert not t.loc["x", "has_winner"]  # winner who is neither team is not a label


def test_missing_second_innings_target_is_derived_from_first_innings_total():
    frame = _toy_match(target_runs=None)
    raw = F.limited_raw_states(frame, "T20")
    chase = raw[raw["innings"] == 2].iloc[0]
    assert chase["target"] == 4 and chase["target_source"] == "first_innings_total+1"
    recorded = F.limited_raw_states(_toy_match(target_runs=3), "T20")
    assert recorded[recorded["innings"] == 2].iloc[0]["target"] == 3


def test_rounded_dls_allotment_is_extended_causally():
    frame = _toy_match()
    frame.loc[frame["innings_number"] == 2, "target_overs"] = 0  # recorded allotment rounded down to 0 balls
    raw = F.limited_raw_states(frame, "T20")
    chase = raw[raw["innings"] == 2].iloc[0]
    assert chase["max_balls"] == 1 and chase["allotment_rounded"]  # a ball is being bowled, so >= 1 ball allotted
    assert F.validate_limited(raw, "T20").all()


def test_states_are_pre_delivery():
    frame = _toy_match()
    assert list(frame["pre_runs"]) == [0, 1, 0]
    assert list(frame["post_runs"]) == [1, 3, 4]
    assert list(frame["pre_legal_count"]) == [0, 1, 0]


def test_legacy_label_mapping_round_trip():
    from scripts.train_win_probability_v2 import legacy_team1_labels, legacy_to_batting
    y_bat = np.array([0, 1, 0, 1, 2])
    t1 = np.array([True, True, False, False, True])
    assert list(legacy_team1_labels(y_bat, t1)) == [0, 1, 1, 0, 2]
    p3 = np.array([[0.7, 0.2, 0.1], [0.7, 0.2, 0.1]])
    bat, bowl, draw = legacy_to_batting(p3, np.array([True, False]))
    assert list(bat) == [0.7, 0.2] and list(bowl) == [0.2, 0.7] and list(draw) == [0.1, 0.1]


# --------------------------------------------------------------------------------------
# Terminal states and validation (rules of cricket, not model output)
# --------------------------------------------------------------------------------------

def _limited(**kw):
    base = dict(innings=2, runs=100, wickets_lost=3, legal_balls=60, max_balls=120, target=150.0)
    base.update(kw)
    return pd.DataFrame([base])


def test_completed_chase_is_a_batting_win_and_failed_chase_a_loss():
    assert F.limited_terminal(_limited(runs=150))[0] == 1.0
    assert F.limited_terminal(_limited(runs=140, wickets_lost=10))[0] == 0.0
    assert F.limited_terminal(_limited(runs=140, legal_balls=120))[0] == 0.0
    assert F.limited_terminal(_limited(runs=149, legal_balls=120))[0] == 0.5  # tie
    assert np.isnan(F.limited_terminal(_limited())[0])
    assert np.isnan(F.limited_terminal(_limited(innings=1, target=np.nan, legal_balls=120))[0])


def test_impossible_limited_states_are_rejected():
    assert not F.validate_limited(_limited(wickets_lost=11), "T20")[0]
    assert not F.validate_limited(_limited(legal_balls=121), "T20")[0]
    assert not F.validate_limited(_limited(target=np.nan), "T20")[0]
    assert not F.validate_limited(_limited(runs=-1), "T20")[0]
    assert not F.validate_limited(_limited(max_balls=150), "T20")[0]
    assert F.validate_limited(_limited(), "T20")[0]


def test_multiday_terminal_rules():
    base = dict(innings=4, runs=0, wickets_lost=0, legal_balls=0, match_legal_balls=1500,
                batting_prior_runs=200, opposition_runs=450)
    frame = pd.DataFrame([{**base, "runs": 251}, {**base, "runs": 100, "wickets_lost": 10},
                          {**base, "runs": 250, "wickets_lost": 10}, {**base, "runs": 100},
                          {**base, "innings": 3, "runs": 100, "wickets_lost": 10, "batting_prior_runs": 150, "opposition_runs": 400}])
    out = F.multiday_terminal(frame)
    assert out[0] == 0 and out[1] == 1 and out[2] == 3 and np.isnan(out[3]) and out[4] == 1


# --------------------------------------------------------------------------------------
# Leakage guards
# --------------------------------------------------------------------------------------

def test_partitions_are_chronological_and_never_split_a_date():
    rows = [dict(match_id=f"m{i}", start_date=f"2020-01-{1 + i // 3:02d}", team1_id="a", team2_id="b", winner_id="a")
            for i in range(60)]
    m = _matches(rows)
    m["group"] = "T20"
    part = F.assign_partitions(m, pd.Series(True, index=m.index))
    order = {"train": 0, "validation": 1, "calibration": 2, "test": 3}
    ranks = part.map(order)
    assert ranks.is_monotonic_increasing  # rows are in date order
    assert m.assign(p=part).groupby("start_date")["p"].nunique().max() == 1
    assert set(part) == set(order)


def test_elo_uses_only_results_available_before_the_match():
    m = _matches([
        dict(match_id="m1", start_date="2020-01-01", team1_id="a", team2_id="b", winner_id="a"),
        dict(match_id="m2", start_date="2020-01-01", team1_id="a", team2_id="b", winner_id="a"),  # same day
        dict(match_id="m3", start_date="2020-01-02", team1_id="a", team2_id="b", winner_id="b"),
        dict(match_id="t1", start_date="2020-01-01", team1_id="c", team2_id="d", winner_id="c", match_format="Test"),
        dict(match_id="t2", start_date="2020-01-03", team1_id="c", team2_id="d", winner_id="c", match_format="Test"),
    ])
    elo, snapshot = context.compute_elo(m)
    e = elo.set_index("match_id")
    assert e.loc["m1", "elo_team1"] == e.loc["m2", "elo_team1"] == 1500  # same-day result not yet known
    assert e.loc["m3", "elo_team1"] > 1500  # both earlier wins counted
    assert e.loc["t2", "elo_team1"] == 1500  # Test still in progress (5-day lag)
    assert snapshot["t20|male|a"]["games"] == 3


def test_venue_and_era_par_only_use_earlier_matches():
    rows = [dict(match_id=f"m{i}", start_date=f"2020-02-{i + 1:02d}", team1_id="a", team2_id="b", winner_id="a")
            for i in range(3)]
    m = _matches(rows)
    innings = pd.DataFrame([dict(innings_id=f"i{i}", match_id=f"m{i}", innings_number=1, batting_team_id="a",
                                 target_runs=None, target_overs=None, is_super_over=0, runs=r, legal_balls=120, wickets=5)
                            for i, r in enumerate((150, 200, 999))])
    pars, _ = context.compute_pars(m, innings)
    p = pars.set_index("match_id")
    assert np.isnan(p.loc["m0", "era_par"])
    assert p.loc["m1", "era_par"] == 150
    assert p.loc["m2", "era_par"] == 175  # the 999 of m2 itself is never used


def test_resource_table_is_monotone():
    rng = np.random.default_rng(0)
    b = rng.integers(0, 121, 20000)
    w = rng.integers(0, 10, 20000)
    y = np.maximum(0, b * 1.3 * (1 - w / 10) + rng.normal(0, 8, 20000))
    table = F.fit_resource_table(pd.DataFrame({"balls_remaining": b, "wickets_lost": w, "runs_remaining": y}), 120)
    assert (np.diff(table.expected, axis=0) >= -1e-9).all()
    assert (np.diff(table.expected, axis=1) <= 1e-9).all()
    assert table.expected[0].max() == 0 and table.expected[:, 10].max() == 0
    assert table.resources(120, 0) == pytest.approx(1.0)


def test_metrics_and_calibrators():
    y = np.array([0, 1, 1, 0])
    p = np.array([0.2, 0.8, 0.6, 0.4])
    assert M.brier(y, p) == pytest.approx(np.mean((p - y) ** 2))
    assert M.log_loss(y, p) == pytest.approx(-np.mean(np.log([0.8, 0.8, 0.6, 0.6])))
    assert M.rps(np.array([0]), np.array([[1.0, 0.0, 0.0]]), order=(0, 2, 1)) == 0
    for method in ("none", "sigmoid", "isotonic"):
        out = M.Calibrator(method).fit(np.tile(p, 20), np.tile(y, 20)).transform(p)
        assert ((out > 0) & (out < 1)).all()


# --------------------------------------------------------------------------------------
# Model sanity (requires trained bundles)
# --------------------------------------------------------------------------------------

def _engine(fmt):
    group = {"T20": "t20", "ODI": "odi", "ODM": "odm", "Test": "test", "MDM": "mdm"}[fmt]
    if not (ARTIFACT_DIR / f"{group}.joblib").exists():
        pytest.skip("v2 bundles not built; run scripts/train_win_probability_v2.py")
    return WinProbabilityEngine.for_format(fmt)


@pytest.mark.parametrize("fmt,full", [("T20", 120), ("ODI", 300), ("ODM", 300)])
def test_one_run_needed_with_eight_wickets_and_an_over_left_is_near_certain(fmt, full):
    e = _engine(fmt)
    p = e.predict_limited(innings=2, runs=149, wickets_lost=2, legal_balls=full - 6, target=150)
    assert p["status"] == "model"
    assert p["batting_team_win"] > 0.95


@pytest.mark.parametrize("fmt,full", [("T20", 120), ("ODI", 300), ("ODM", 300)])
def test_sixty_needed_off_six_balls_nine_down_is_near_hopeless(fmt, full):
    e = _engine(fmt)
    p = e.predict_limited(innings=2, runs=140, wickets_lost=9, legal_balls=full - 6, target=200)
    assert p["status"] == "model"
    assert p["batting_team_win"] < 0.02


@pytest.mark.parametrize("fmt", ["T20", "ODI"])
def test_decided_matches_return_exact_outcomes(fmt):
    e = _engine(fmt)
    won = e.predict_limited(innings=2, runs=151, wickets_lost=4, legal_balls=100, target=150)
    lost = e.predict_limited(innings=2, runs=120, wickets_lost=10, legal_balls=100, target=150)
    assert (won["status"], won["batting_team_win"], won["bowling_team_win"]) == ("decided", 1.0, 0.0)
    assert (lost["status"], lost["batting_team_win"], lost["bowling_team_win"]) == ("decided", 0.0, 1.0)


@pytest.mark.parametrize("bad", [dict(wickets_lost=11), dict(legal_balls=130), dict(target=None),
                                 dict(runs=300, target=150), dict(innings=3), dict(max_balls=200)])
def test_engine_rejects_impossible_states(bad):
    e = _engine("T20")
    kw = dict(innings=2, runs=100, wickets_lost=3, legal_balls=60, target=150)
    kw.update(bad)
    with pytest.raises(F.InvalidStateError):
        e.predict_limited(**kw)


def test_chase_probability_moves_in_the_right_direction():
    e = _engine("T20")
    base = dict(innings=2, runs=100, wickets_lost=3, legal_balls=90, target=150)
    p = lambda **kw: e.predict_limited(**{**base, **kw})["batting_team_win"]  # noqa: E731
    assert p(runs=120) > p() > p(runs=80)
    assert p(wickets_lost=1) > p() > p(wickets_lost=7)
    assert p(legal_balls=80) > p() > p(legal_balls=100)


def test_innings_transition_matches_the_start_of_the_chase():
    e = _engine("T20")
    end_first = e.predict_limited(innings=1, runs=170, wickets_lost=6, legal_balls=120)
    start_chase = e.predict_limited(innings=2, runs=0, wickets_lost=0, legal_balls=0, target=171)
    assert end_first["batting_team_win"] == pytest.approx(1 - start_chase["batting_team_win"], abs=1e-6)


def test_predictions_are_deterministic():
    e = _engine("ODI")
    a = e.predict_limited(innings=1, runs=120, wickets_lost=2, legal_balls=150)
    b = e.predict_limited(innings=1, runs=120, wickets_lost=2, legal_balls=150)
    assert a == b


def test_test_match_model_returns_three_outcomes_and_terminal_states():
    e = _engine("Test")
    p = e.predict_multiday(innings=2, runs=150, wickets_lost=3, legal_balls=300, match_legal_balls=900,
                           batting_prior_runs=0, opposition_runs=400)
    assert p["status"] == "model"
    assert p["batting_team_win"] + p["bowling_team_win"] + p["draw_or_tie"] == pytest.approx(1.0, abs=1e-4)
    won = e.predict_multiday(innings=4, runs=201, wickets_lost=5, legal_balls=400, match_legal_balls=2000,
                             batting_prior_runs=300, opposition_runs=500)
    assert won["status"] == "decided" and won["batting_team_win"] == 1.0
    with pytest.raises(F.InvalidStateError):
        e.predict_multiday(innings=1, runs=10, wickets_lost=0, legal_balls=10, match_legal_balls=10,
                           batting_prior_runs=100, opposition_runs=0)
