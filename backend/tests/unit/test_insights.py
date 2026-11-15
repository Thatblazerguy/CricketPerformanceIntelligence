"""Regression tests for the statistical helpers behind the analytics dashboards."""
import math

import pytest

from app.analytics.insights import (
    batting_rates, bowling_rates, build_standings, consistency_summary, histogram, net_run_rate,
    normalise_bowling_style, nrr_balls, overs_display, percentile_rank, ratio, rolling_average_by_dismissal,
    rolling_mean,
)
from app.analytics.scorecard import build_innings_scorecard, key_events


def test_ratio_never_substitutes_zero_for_undefined():
    assert ratio(10, 0) is None
    assert ratio(10, None) is None
    assert ratio(None, 5) is None
    assert ratio(0, 5) == 0
    assert ratio(7, 3, 6) == 14.0


def test_overs_notation_is_overs_dot_balls_not_decimal():
    assert overs_display(0) == "0.0"
    assert overs_display(5) == "0.5"
    assert overs_display(6) == "1.0"
    assert overs_display(125) == "20.5"
    assert overs_display(None) is None


def test_batting_rates_use_dismissals_and_balls_faced():
    r = batting_rates(runs=300, balls=200, dismissals=6, fours=20, sixes=10, dots=70)
    assert r["average"] == 50.0
    assert r["strike_rate"] == 150.0
    assert r["boundary_percentage"] == 15.0
    assert r["dot_percentage"] == 35.0
    assert r["balls_per_dismissal"] == pytest.approx(33.3)
    # Unbeaten in every innings: average is undefined, not infinite or zero.
    assert batting_rates(50, 40, 0)["average"] is None


def test_bowling_rates():
    r = bowling_rates(runs=240, legal_balls=180, wickets=10, dots=80, boundaries=20)
    assert r["economy"] == 8.0
    assert r["average"] == 24.0
    assert r["strike_rate"] == 18.0
    assert r["dot_percentage"] == pytest.approx(44.44)
    assert bowling_rates(30, 24, 0)["average"] is None


def test_consistency_summary_bands_and_sample_sd():
    runs = [0, 5, 30, 50, 100, 15]
    out = consistency_summary(runs, dismissed=[True, True, True, False, True, True])
    assert out["innings"] == 6
    assert out["mean_runs_per_innings"] == pytest.approx(33.33, abs=0.01)
    mean = sum(runs) / 6
    sd = math.sqrt(sum((x - mean) ** 2 for x in runs) / 5)
    assert out["std_dev"] == round(sd, 2)
    assert out["under_10_count"] == 2
    assert out["ducks_count"] == 1
    assert out["30_plus_count"] == 3  # 30, 50, 100 (inclusive bands)
    assert out["50_plus_count"] == 2
    assert out["100_plus_count"] == 1
    assert out["median_runs"] == 22.5
    assert consistency_summary([12])["std_dev"] is None
    assert consistency_summary([]) == {"innings": 0}


def test_unbeaten_zero_is_not_a_duck():
    out = consistency_summary([0, 0], dismissed=[False, True])
    assert out["ducks_count"] == 1


def test_rolling_windows():
    assert rolling_mean([1, 2, 3, 4], 2) == [None, 1.5, 2.5, 3.5]
    assert rolling_mean([1, None, 3], 2) == [None, None, None]
    # 3-innings rolling average uses dismissals in the window.
    assert rolling_average_by_dismissal([10, 20, 30, 40], [True, False, True, True], 3) == [None, None, 30.0, 45.0]
    assert rolling_average_by_dismissal([5, 5], [False, False], 2) == [None, None]


def test_histogram_keeps_empty_interior_bins():
    bins = histogram([1, 3, 25], 10)
    assert [b["count"] for b in bins] == [2, 0, 1]
    assert bins[0]["label"] == "0–9"
    assert histogram([], 10) == []
    assert [b["label"] for b in histogram([1, 2, 2], 1, 1)] == ["1", "2"]


def test_bowling_style_labels_are_merged_case_insensitively():
    assert normalise_bowling_style("Right-arm off break") == "Right-arm Off Break"
    assert normalise_bowling_style("Right-arm Off Break") == "Right-arm Off Break"
    assert normalise_bowling_style("left-arm wrist-spin") == "Left-arm Wrist-Spin"
    assert normalise_bowling_style("  ") is None


def test_nrr_counts_all_out_innings_as_full_quota():
    assert nrr_balls(100, 10, 120) == 120
    assert nrr_balls(100, 7, 120) == 100
    assert nrr_balls(100, 10, None) == 100
    # 160 off 20 overs vs 150 off 20 overs -> +0.5
    assert net_run_rate(160, 120, 150, 120) == 0.5
    assert net_run_rate(10, 0, 5, 6) is None


def test_standings_points_and_ordering():
    rows = [
        {"team_id": "a", "team": "A", "outcome": "won", "runs_for": 180, "balls_for": 120, "runs_against": 150, "balls_against": 120},
        {"team_id": "b", "team": "B", "outcome": "lost", "runs_for": 150, "balls_for": 120, "runs_against": 180, "balls_against": 120},
        {"team_id": "a", "team": "A", "outcome": "no_result", "runs_for": 40, "balls_for": 30, "runs_against": 0, "balls_against": 0},
        {"team_id": "c", "team": "C", "outcome": "tied", "runs_for": 160, "balls_for": 120, "runs_against": 160, "balls_against": 120},
    ]
    table = build_standings(rows)
    by = {r["team_id"]: r for r in table}
    assert by["a"]["points"] == 3 and by["a"]["played"] == 2
    # No-result runs are excluded from NRR.
    assert by["a"]["runs_for"] == 180 and by["a"]["net_run_rate"] == 1.5
    assert by["a"]["win_percentage"] == 100.0
    assert by["c"]["points"] == 1
    assert [r["team_id"] for r in table] == ["a", "c", "b"]
    assert [r["position"] for r in table] == [1, 2, 3]


def test_percentile_rank_inverts_lower_is_better_metrics():
    pop = [6.0, 7.0, 8.0, 9.0]
    assert percentile_rank(9.0, pop) == 87.5
    assert percentile_rank(6.0, pop, lower_is_better=True) == 87.5
    assert percentile_rank(None, pop) is None
    assert percentile_rank(5.0, []) is None


# ------------------------------------------------------------ scorecard extensions

def _d(over, batter, bid, *, runs=0, total=None, conceded=None, legal=True, faced=True, wickets=None, extras=None, non_striker="B", nsid="b", bowler="Bowler X", bowler_id="x"):
    return {"over_index": over, "batter": batter, "batter_id": bid, "non_striker": non_striker, "non_striker_id": nsid,
            "bowler": bowler, "bowler_id": bowler_id, "batter_runs": runs, "total_runs": runs if total is None else total,
            "bowling_runs": runs if conceded is None else conceded, "legal": legal, "faced": faced,
            "four": runs == 4, "six": runs == 6, "extra_types": extras or [], "wickets": wickets or [], "over_display": f"{over + 1}.1"}


def test_bowler_dots_and_boundaries_use_legal_balls_and_bowling_runs():
    inn = {"deliveries": [
        _d(0, "A", "a", runs=0),
        _d(0, "A", "a", runs=0, total=1, conceded=0, extras=[{"type": "legbyes", "runs": 1}]),  # leg-bye: dot for bowler
        _d(0, "A", "a", runs=4),
        _d(0, "A", "a", runs=0, total=1, conceded=1, legal=False, faced=False, extras=[{"type": "wides", "runs": 1}]),
        _d(0, "A", "a", runs=6),
        _d(0, "A", "a", runs=1),
        _d(0, "B", "b", runs=0, non_striker="A", nsid="a"),
    ]}
    sc = build_innings_scorecard(inn, "T20")
    bowler = sc["bowling"][0]
    assert bowler["legal_balls"] == 6
    assert bowler["dots"] == 3
    assert (bowler["fours"], bowler["sixes"]) == (1, 1)
    assert bowler["dot_percentage"] == 50.0
    assert bowler["boundary_percentage"] == pytest.approx(33.33)
    assert bowler["maidens"] == 0


def test_partnership_contributions_and_extras_reconcile():
    inn = {"deliveries": [
        _d(0, "A", "a", runs=4),
        _d(0, "A", "a", runs=1),
        _d(0, "B", "b", runs=2, non_striker="A", nsid="a"),
        _d(0, "B", "b", runs=0, total=1, conceded=1, legal=False, faced=False, non_striker="A", nsid="a", extras=[{"type": "wides", "runs": 1}]),
        _d(0, "B", "b", runs=0, non_striker="A", nsid="a", wickets=[{"player_out_id": "b", "player_out": "B", "kind": "bowled", "bowler_credited": True}]),
    ]}
    sc = build_innings_scorecard(inn, "T20")
    p = sc["partnerships"][0]
    assert p["runs"] == 8 and p["balls"] == 4
    assert {c["player"]: c["runs"] for c in p["contributions"]} == {"A": 5, "B": 2}
    assert p["extras"] == 1
    assert sum(c["runs"] for c in p["contributions"]) + p["extras"] == p["runs"]
    assert p["run_rate"] == 12.0
    assert (p["start_score"], p["end_score"]) == (0, 8)


def test_required_run_rate_progression_for_a_chase():
    deliveries = [_d(o, "A", "a", runs=1) for o in range(2) for _ in range(6)]
    sc = build_innings_scorecard({"deliveries": deliveries, "target_runs": 30, "target_overs": 20}, "T20")
    first, second = sc["overs_progression"]
    assert first["runs_required"] == 24 and first["balls_remaining"] == 114
    assert first["required_run_rate"] == round(24 * 6 / 114, 2)
    assert second["required_run_rate"] == round(18 * 6 / 108, 2)
    assert sc["target"] == 30


def test_required_rate_undefined_once_target_reached():
    deliveries = [_d(0, "A", "a", runs=6) for _ in range(6)]
    sc = build_innings_scorecard({"deliveries": deliveries, "target_runs": 20, "target_overs": 20}, "T20")
    assert sc["overs_progression"][0]["required_run_rate"] is None
    assert sc["overs_progression"][0]["runs_required"] == 0


def test_key_events_detect_collapses_and_big_overs_only_from_events():
    overs = [{"over": i + 1, "runs": r, "wickets": w, "score": 0} for i, (r, w) in enumerate([(6, 0), (5, 1), (4, 1), (20, 0), (6, 0), (7, 0)])]
    events = key_events(overs)
    kinds = [(e["type"], e["over"]) for e in events]
    assert ("collapse", 3) in kinds  # wickets in overs 2 and 3
    assert ("big_over", 4) in kinds  # 20 >= 12 and >= 2x mean (8)
    assert key_events([]) == []
    assert key_events([{"over": 1, "runs": 8, "wickets": 0, "score": 8}]) == []
