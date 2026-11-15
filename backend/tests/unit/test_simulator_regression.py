"""Regression fixture: CSK vs MI (2019 IPL final XIs), men's T20.

The fixture freezes the CPI inputs (calibration block, the 22 player profiles and
names), so this seeded match is exactly reproducible regardless of later data syncs.
It mirrors the audited single-match run (MI ~135 batting first, CSK chasing comfortably).
"""
from __future__ import annotations

import gzip
import json
import random
from pathlib import Path

import pytest

from app.ml import match_simulator as ms
from app.services import match_simulation as svc

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "simulator" / "csk_vs_mi_2019.json.gz"


@pytest.fixture(scope="module")
def fx():
    with gzip.open(FIXTURE, "rt") as fh:
        return json.load(fh)


def make_ctx(fx, swap=False):
    keys = ("B", "A") if swap else ("A", "B")
    teams = {}
    positions = {}
    for new, old in zip(("A", "B"), keys):
        t = fx["payload"]["teams"][old]
        order = [p["id"] for p in t["players"]]
        keeper = next((p["id"] for p in t["players"] if p["is_wicketkeeper"]), None)
        teams[new] = ms.TeamSetup(new, t["name"], order, keeper=keeper)
        positions.update({p: i + 1 for i, p in enumerate(order)})
    model = ms.SimModel(fx["calibration"], "T20", "male", fx["profiles"], fx["meta"], positions=positions,
                        keepers={t.keeper for t in teams.values() if t.keeper})
    toss_winner = "A" if swap else "B"  # CSK wins the toss in both orientations
    return {"model": model, "rules": ms.rules_for("T20"), "teams": teams, "meta": fx["meta"], "gender": "male",
            "conditions": {"toss_winner": toss_winner, "toss_decision": "field"}}


@pytest.fixture(scope="module")
def match(fx):
    ctx = make_ctx(fx)
    return ctx, svc.detailed_match(ctx, fx["seed"], wp_sims=200)


def test_seeded_result_is_reproduced_exactly(fx, match):
    _, out = match
    mi, csk = out["innings"][0], out["innings"][1]
    assert (mi["batting_team"], mi["runs"], mi["wickets"], mi["overs"]) == ("MI", 134, 7, "20.0")
    assert (csk["batting_team"], csk["runs"], csk["wickets"], csk["overs"]) == ("CSK", 135, 0, "14.1")
    assert out["result"] == "CSK won by 10 wickets (35 balls left)"
    again = svc.detailed_match(make_ctx(fx), fx["seed"], wp_sims=200)
    assert [i["scorecard"] for i in again["innings"]] == [i["scorecard"] for i in out["innings"]]
    assert again["win_probability"]["points"] == out["win_probability"]["points"]


def test_scorecards_extras_partnerships_and_fall_of_wickets_reconcile(match):
    _, out = match
    for inn in out["innings"]:
        card = inn["scorecard"]
        extras = inn["extras_detail"]
        bat_runs = sum(b["runs"] or 0 for b in card["batting"])
        assert bat_runs + sum(extras.values()) == inn["runs"]
        assert sum(b["runs"] for b in card["bowling"]) + extras["byes"] + extras["legbyes"] == inn["runs"]
        assert sum(b["wides"] for b in card["bowling"]) == extras["wides"]
        assert sum(b["no_balls"] for b in card["bowling"]) == extras["noballs"]
        assert card["extras"].get("wides", 0) == extras["wides"] and card["extras"].get("noballs", 0) == extras["noballs"]
        assert sum(p["runs"] for p in card["partnerships"]) == inn["runs"]
        assert sum(p["balls"] for p in card["partnerships"]) == inn["legal_balls"]
        fow = card["fall_of_wickets"]
        assert len(fow) == inn["wickets"] and [f["wicket"] for f in fow] == list(range(1, inn["wickets"] + 1))
        assert all(a["score"] <= b["score"] for a, b in zip(fow, fow[1:])) and all(f["score"] <= inn["runs"] for f in fow)
        outs = [b for b in card["batting"] if b["dismissal"] not in ("not out", "did not bat")]
        assert len(outs) == inn["wickets"]
        assert sum(p["runs"] for p in card["phases"]) == inn["runs"]
        assert sum(p["legal_balls"] for p in card["phases"]) == inn["legal_balls"]
        assert sum(p["wickets"] for p in card["phases"]) == inn["wickets"]


def test_bowling_allocation_and_innings_completion(match):
    _, out = match
    mi, csk = out["innings"][0], out["innings"][1]
    for inn in (mi, csk):
        bowling = inn["scorecard"]["bowling"]
        assert all(b["legal_balls"] <= 24 for b in bowling)
        assert sum(b["legal_balls"] for b in bowling) == inn["legal_balls"]
        overs = [b["over"] for b in inn["balls"]]
        bowler_by_over = {}
        for ball in inn["balls"]:
            bowler_by_over.setdefault(ball["over"], set()).add(ball["bowler"])
        assert all(len(v) == 1 for v in bowler_by_over.values())
        seq = [next(iter(bowler_by_over[o])) for o in sorted(bowler_by_over)]
        assert all(x != y for x, y in zip(seq, seq[1:]))
        assert overs == sorted(overs)
    assert mi["legal_balls"] == 120 or mi["wickets"] == 10
    assert csk["target"] == mi["runs"] + 1 and csk["runs"] >= csk["target"]
    assert csk["runs"] - csk["balls"][-1]["runs"] < csk["target"]  # the chase stops on the winning ball


def test_win_probability_always_refers_to_team_a(match, fx):
    ctx, out = match
    wp = out["win_probability"]
    assert wp["available"] and wp["team"] == "A" and wp["team_name"] == "MI"
    pts = wp["points"]
    assert pts[0]["label"] == "start" and pts[-1]["label"] == "result"
    assert pts[-1]["team_a"] == 0.0  # MI lost
    for p in pts:
        assert 0.0 <= p["ci_low"] <= p["team_a"] <= p["ci_high"] <= 1.0
        assert p["team_a"] + p["team_b"] == pytest.approx(1.0, abs=1e-3)
        if not p["exact"]:
            assert 0.0 < p["team_a"] < 1.0  # Jeffreys estimate, never a hard 0/1 from finite samples
    second = [p for p in pts if p["innings"] == 2 and p["label"] == "over"]
    assert second and all(p["batting"] == "B" for p in second)
    # CSK cruising toward a small target: MI's chance must fall as the chase progresses.
    assert second[-1]["team_a"] <= second[0]["team_a"] + 0.05
    # Swapping which side is "Team A" gives the complementary pre-match probability.
    swapped = svc.detailed_match(make_ctx(fx, swap=True), fx["seed"], wp_sims=400)["win_probability"]["points"][0]
    assert pts[0]["team_a"] + swapped["team_a"] == pytest.approx(1.0, abs=0.12)


def test_terminal_states_are_exact_and_posterior_tracks_low_scoring(fx, match):
    ctx, _ = match
    rules = ctx["rules"]
    chase = ms.InningsResult(2, "B", "A", target=136)
    assert ms._terminal(rules, 1, chase, {"score": 136, "wickets": 2, "legal_balls": 90}) == 0.0
    assert ms._terminal(rules, 1, chase, {"score": 120, "wickets": 10, "legal_balls": 90}) == 1.0
    assert ms._terminal(rules, 1, chase, {"score": 135, "wickets": 6, "legal_balls": 120}) == 0.5
    assert ms._terminal(rules, 1, chase, {"score": 100, "wickets": 6, "legal_balls": 96}) is None
    # Posterior after a low first innings leans toward low-scoring conditions.
    r = ms.simulate_match(ctx["model"], rules, ctx["teams"], random.Random(f"{fx['seed']}:detail"),
                          toss_winner="B", toss_decision="field", detailed=True)
    post = ms.condition_posterior(r["innings"][0].snapshots[-1]["loglik"])
    mean_z = sum(w * z for w, z in zip(post, ms.CONDITION_Z))
    assert abs(sum(post) - 1) < 1e-9 and mean_z < 0
