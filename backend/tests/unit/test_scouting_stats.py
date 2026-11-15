"""Statistical primitives used by the scouting engine."""
import random

import pytest

from app.analytics import scouting_stats as st


def test_ratio_never_turns_missing_denominator_into_zero():
    assert st.ratio(10, 0) is None
    assert st.ratio(None, 10) is None
    assert st.ratio(150, 100, 100) == 150.0


def _simulate(true_sd, n_players=400, balls=(30, 600), seed=7):
    rng = random.Random(seed)
    pairs = []
    for _ in range(n_players):
        p = min(max(rng.gauss(0.15, true_sd), 0.01), 0.6)
        n = rng.randint(*balls)
        successes = sum(1 for _ in range(n) if rng.random() < p)
        pairs.append((successes, n))
    return pairs


def test_prior_strength_is_estimated_from_between_player_spread():
    # Expected m = p(1-p)/tau^2 = 0.1275 / 0.03^2 ≈ 142 balls.
    prior = st.estimate_prior(_simulate(0.03), "proportion")
    assert prior is not None and not prior.fallback
    assert 80 < prior.strength < 260
    assert prior.mean == pytest.approx(0.15, abs=0.01)
    # A more heterogeneous population needs less shrinkage.
    wide = st.estimate_prior(_simulate(0.08), "proportion")
    assert wide.strength < prior.strength


def test_small_cohort_uses_documented_fallback():
    prior = st.estimate_prior([(5, 20), (8, 40), (3, 10)], "proportion")
    assert prior.fallback is True
    assert prior.strength == 20  # median denominator


def test_shrinkage_pulls_small_samples_harder_than_large_ones():
    prior = st.Prior(mean=1.3, strength=200, unit_variance=2.5, players=500)
    tiny = st.shrink(30, 15, prior)       # SR 200 on 15 balls
    big = st.shrink(1600, 1000, prior)    # SR 160 on 1000 balls
    assert tiny < big                      # 15-ball cameo does not outrank sustained output
    assert abs(big - 1.6) < abs(tiny - 2.0)
    assert st.shrink(0, 0, prior) is None  # no sample → no estimate, never zero


def test_reliability_is_share_of_estimate_from_own_data():
    prior = st.Prior(1.0, 100, 1.0, 50)
    assert st.reliability(100, prior) == pytest.approx(0.5)
    assert st.reliability(900, prior) == pytest.approx(0.9)
    assert st.reliability(0, prior) == 0.0
    assert st.tier(0.65) == "Established"
    assert st.tier(0.45).startswith("Promising")
    assert st.tier(0.2) == "Insufficient data"
    assert st.tier(None) == "Insufficient data"


def test_intervals_contain_estimate_and_narrow_with_sample():
    lo, hi = st.wilson_interval(20, 100)
    assert lo < 0.2 < hi
    lo2, hi2 = st.wilson_interval(200, 1000)
    assert hi2 - lo2 < hi - lo
    alo, ahi = st.average_interval(400, 10)
    assert alo < 40 < ahi
    assert st.average_interval(10, 0) is None
    mlo, mhi = st.mean_interval(130, 100, 2.4)
    assert mlo < 1.3 < mhi


def test_percentile_rank_handles_direction_and_ties():
    dist = [1, 2, 3, 4]
    assert st.percentile_rank(4, dist) == 87.5
    assert st.percentile_rank(4, dist, higher_is_better=False) == 12.5
    assert st.percentile_rank(2.5, [2.5, 2.5]) == 50.0
    assert st.percentile_rank(None, dist) is None


def test_consistency_summary_and_rolling():
    runs = [0, 5, 12, 31, 45, 8, 60, 3, 22, 35]
    summary = st.consistency_summary(runs, good=30, poor=10)
    assert summary["innings"] == 10
    assert summary["median"] == 17.0
    assert summary["significant_pct"] == 40.0
    assert summary["poor_pct"] == 40.0
    assert summary["sd"] > 0
    assert st.consistency_summary([], 30, 10) == {"innings": 0}
    roll = st.rolling([10, 20, 30, 40], 2)
    assert roll == [None, 15.0, 25.0, 35.0]


def test_weighted_mean_ignores_missing_values():
    assert st.weighted_mean([(80, 0.5), (None, 0.5)]) == 80
    assert st.weighted_mean([(None, 1)]) is None
