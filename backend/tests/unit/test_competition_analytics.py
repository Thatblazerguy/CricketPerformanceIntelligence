"""Unit tests for the Team/Venue Analytics statistical core (no database)."""
from datetime import date

import pytest

from app.analytics.competition_common import (
    Scope, annotate_match, binomial_p, norm_country, proportion, team_result, two_proportion_p, venue_side, wilson,
)
from app.analytics.team_analytics import chase_defence, innings_block, order_split, record
from app.analytics.venue_analytics import _toss_verdict, toss_analysis

T20 = Scope(format="T20")


def inn(n, bat, bowl, runs, balls=120, wkts=5, target_runs=None, target_overs=None, **kw):
    row = {"innings_id": f"{bat}-{n}", "innings_number": n, "batting_team_id": bat, "bowling_team_id": bowl,
           "runs": runs, "legal_balls": balls, "wickets": wkts, "fours": 10, "sixes": 5, "dots": 40, "extras": 5,
           "target_runs": target_runs, "target_overs": target_overs}
    for p in ("pp", "mid", "death"):
        row.update({f"{p}_runs": 0, f"{p}_balls": 0, f"{p}_wkts": 0, f"{p}_bnd": 0})
    row.update(kw)
    return row


def match(mid="m", winner="A", result="win", first=("A", 180), second=("B", 170, 120, 8), toss=("A", "bat"),
          margin_runs=None, margin_wkts=None, target_overs=20, **kw):
    a, b = "A", "B"
    second_bowl = first[0]
    m = {"id": mid, "start_date": date(2024, 1, 1), "season": "2024", "match_format": "T20", "tournament_id": "t1",
         "venue_id": "v1", "venue": "Ground", "venue_country": kw.get("venue_country"), "competition": "League",
         "team1_id": a, "team2_id": b, "team1": "Alpha", "team2": "Beta",
         "team1_country": kw.get("c1"), "team2_country": kw.get("c2"),
         "toss_winner_id": toss[0], "toss_decision": toss[1], "winner_id": winner, "result_type": result,
         "result_margin_runs": margin_runs, "result_margin_wickets": margin_wkts, "has_super_over": kw.get("super_over", False),
         "innings": [inn(1, first[0], second[0], first[1]),
                     inn(2, second[0], second_bowl, second[1], balls=second[2], wkts=second[3], target_runs=first[1] + 1, target_overs=target_overs)]}
    annotate_match(m, T20)
    return m


# ------------------------------------------------------------------ statistics

def test_wilson_interval_brackets_point_estimate():
    lo, hi = wilson(60, 100)
    assert lo < 60 < hi and 49 < lo < 51 and 69 < hi < 70


def test_binomial_p_is_two_sided_and_bounded():
    assert binomial_p(5, 10) == 1.0
    assert binomial_p(10, 10) < 0.01
    assert binomial_p(0, 0) is None


def test_two_proportion_p_detects_large_gap_only():
    assert two_proportion_p(80, 100, 40, 100) < 0.001
    assert two_proportion_p(52, 100, 48, 100) > 0.5
    assert two_proportion_p(1, 0, 1, 1) is None


def test_proportion_flags_small_samples():
    assert proportion(3, 5)["sample"] == "low"
    assert proportion(0, 0)["value"] is None


# ------------------------------------------------------------- result handling

def test_ties_no_results_and_draws_are_never_wins_or_losses():
    ms = [match("w", winner="A"), match("l", winner="B"), match("t", winner=None, result="tie"),
          match("nr", winner=None, result="no result")]
    r = record(ms, "A")
    assert (r["won"], r["lost"], r["tied"], r["no_result"], r["decided"]) == (1, 1, 1, 1, 2)
    assert r["win_percentage"] == 50.0
    assert team_result(ms[2], "A") == "tie"


def test_no_result_and_reduced_matches_are_incomplete():
    nr = match(winner=None, result="no result")
    reduced = match(target_overs=12)
    full = match()
    assert not nr["complete"] and not reduced["complete"] and full["complete"]
    assert reduced["reduced"]


def test_chase_facts_and_lowest_total_eligibility():
    m = match(winner="B", first=("A", 150), second=("B", 151, 110, 4))
    assert m["chase"]["won"] is True and m["chase"]["target"] == 151
    assert m["chase"]["balls_remaining"] == 10 and m["chase"]["wickets_in_hand"] == 6
    # A won chase that ended early is not a "completed" total; a full 20-over innings is.
    assert m["innings"][0]["finished"] and not m["innings"][1]["finished"]


def test_close_match_thresholds():
    assert match(margin_runs=8)["close"]
    assert not match(margin_runs=40)["close"]
    assert match(winner="B", second=("B", 181, 117, 3), margin_wkts=7)["close"]  # 3 balls to spare
    assert match(winner=None, result="tie")["close"]


def test_order_split_and_chase_defence_use_complete_matches():
    ms = [match("a", winner="A"), match("b", winner="B", first=("A", 150), second=("B", 151, 110, 4)),
          match("c", winner="A", target_overs=10)]  # reduced: kept in results, dropped from chase records
    o = order_split(ms, "A")
    assert o["batting_first"]["matches"] == 3 and o["batting_first"]["won"] == 2
    cd = chase_defence(ms, "A")
    assert cd["defences"]["attempts"] == 2 and cd["defences"]["successful"] == 1
    assert cd["defences"]["lowest_defended_total"] == 180


def test_innings_block_excludes_incomplete_from_averages():
    good, nr = match(), match(winner=None, result="no result", first=("A", 20))
    block = innings_block([good["innings"][0], nr["innings"][0]])
    assert block["average_score"] == 180 and block["complete_innings"] == 1 and block["innings"] == 2


# ------------------------------------------------------------------ home / away

def test_norm_country_aliases():
    assert norm_country("USA") == norm_country("United States of America")
    assert norm_country("Wales") == "england"


def test_verified_country_home_away_neutral():
    homes = {"homes": {}, "seasons": set()}
    m = match(venue_country="India", c1="India", c2="Australia")
    assert venue_side(m, "A", homes) == ("home", "verified_country")
    assert venue_side(m, "B", homes) == ("away", "verified_country")
    neutral = match(venue_country="England", c1="India", c2="Australia")
    assert venue_side(neutral, "A", homes)[0] == "neutral"


def test_fixture_concentration_and_unclassified():
    homes = {"homes": {("t1", "2024", "v1"): "B"}, "seasons": {("t1", "2024")}}
    m = match(venue_country="India")  # franchise sides: no verified country
    assert venue_side(m, "B", homes) == ("home", "fixture_concentration")
    assert venue_side(m, "A", homes) == ("away", "fixture_concentration")
    assert venue_side(m, "A", {"homes": {}, "seasons": set()}) == ("unclassified", None)
    assert venue_side(m, "A", {"homes": {}, "seasons": {("t1", "2024")}})[0] == "neutral"


# ------------------------------------------------------------------------ toss

def test_toss_analysis_counts_and_verdict():
    ms = [match(f"m{i}", winner="A" if i % 2 else "B", toss=("A", "field" if i % 3 else "bat")) for i in range(20)]
    t = toss_analysis(ms, True)
    assert t["tosses"] == 20 and t["decided_after_toss"] == 20
    assert t["chose_bat"]["chosen"] + t["chose_field"]["chosen"] == 20
    assert t["toss_winner_won"] == 10 and t["p_value"] == 1.0
    assert t["verdict"].startswith("No measurable toss advantage")


@pytest.mark.parametrize("k,n,prefix", [(3, 5, "Too few"), (90, 100, "Measurable toss effect"), (52, 100, "No measurable")])
def test_toss_verdict_thresholds(k, n, prefix):
    assert _toss_verdict(k, n, binomial_p(k, n))[0].startswith(prefix)
