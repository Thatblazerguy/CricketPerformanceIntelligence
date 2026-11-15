"""Integration tests for the Match Simulator API against the local CPI database (read-only).

XIs are resolved with the existing /xi/resolve identification logic, validated
against CPI players, then simulated through the background-job endpoints.
"""
from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
INDIA = ["Rohit Sharma (c)", "Virat Kohli", "Rishabh Pant (wk)", "SA Yadav", "Shivam Dube", "Hardik Pandya",
         "Ravindra Jadeja", "Axar Patel", "Kuldeep Yadav", "Arshdeep Singh", "Jasprit Bumrah"]
ENGLAND = ["Jos Buttler (c/wk)", "Alex Hales", "Philip Salt", "Ben Stokes", "HC Brook", "Liam Livingstone",
           "Moeen Ali", "Sam Curran", "Chris Woakes", "Chris Jordan", "Adil Rashid"]


def resolve(names, team):
    res = client.post("/api/v1/xi/resolve", json={"team_name": team, "names": names})
    assert res.status_code == 200
    return [{k: p[k] for k in ("id", "name", "input_name", "is_captain", "is_wicketkeeper")} for p in res.json()["players"]]


@pytest.fixture(scope="module")
def xis():
    return resolve(INDIA, "India"), resolve(ENGLAND, "England")


def payload(a, b, **extra):
    return {"format": "T20", "teams": {"A": {"name": "India", "players": a}, "B": {"name": "England", "players": b}}, **extra}


def wait(job, timeout=120):
    deadline = time.time() + timeout
    while job["status"] not in ("done", "error"):
        assert time.time() < deadline, "simulation job timed out"
        time.sleep(0.25)
        job = client.get(f"/api/v1/simulator/jobs/{job['id']}").json()
    return job


def test_resolver_tags_only_bracketed_captain_and_keeper(xis):
    _, england = xis
    assert all(p["id"] for p in england)
    flagged = {p["name"]: (p["is_captain"], p["is_wicketkeeper"]) for p in england}
    assert sum(c for c, _ in flagged.values()) == 1  # "Chris ..." is not a captain tag
    assert not any(w for n, (_, w) in flagged.items() if "Woakes" in n or "Jordan" in n)


def test_validate_accepts_real_xis_and_reports_teams(xis):
    india, england = xis
    res = client.post("/api/v1/simulator/match/validate", json=payload(india, england))
    assert res.status_code == 200
    report = res.json()
    assert report["valid"] is True, report["errors"]
    assert report["gender"] == "male" and report["family"] == "T20"
    for key in ("A", "B"):
        team = report["teams"][key]
        assert len(team["players"]) == 11
        assert len(team["bowling_options"]) >= 5
        assert team["keeper"]


def test_validate_flags_duplicates_cross_team_and_missing_players(xis):
    india, england = xis
    dup = india[:10] + [india[0]]
    report = client.post("/api/v1/simulator/match/validate", json=payload(dup, england)).json()
    assert report["valid"] is False and any("duplicate" in e for e in report["errors"])
    cross = england[:10] + [india[1]]
    report = client.post("/api/v1/simulator/match/validate", json=payload(india, cross)).json()
    assert any("both XIs" in e for e in report["errors"])
    missing = india[:10] + [{"id": None, "input_name": "Zzyzx Qwerty"}]
    report = client.post("/api/v1/simulator/match/validate", json=payload(missing, england)).json()
    assert any("Zzyzx Qwerty" in e for e in report["errors"])


def test_validate_warns_about_batting_order_roles(xis):
    india, england = xis
    swapped = [india[10]] + india[1:10] + [india[0]]  # Bumrah opening, Rohit at 11
    report = client.post("/api/v1/simulator/match/validate", json=payload(swapped, england)).json()
    assert report["valid"] is True
    assert any("specialist bowler batting at No. 1" in w for w in report["warnings"])


def test_match_options_lists_historical_venues():
    res = client.get("/api/v1/simulator/match/options?format=T20")
    assert res.status_code == 200
    data = res.json()
    assert data["venues"] and data["venues"][0]["matches"] > 0
    assert data["limits"]["max_simulations"] == 5000
    assert client.get("/api/v1/simulator/match/options?format=Hundred").status_code == 422


def test_full_match_job_produces_reconciled_scorecards(xis):
    india, england = xis
    venue = client.get("/api/v1/simulator/match/options?format=T20").json()["venues"][0]["id"]
    body = payload(india, england, seed=1234, conditions={"venue_id": venue, "pitch": "batting", "weather": "dew",
                                                           "toss_winner": "A", "toss_decision": "field"})
    job = wait(client.post("/api/v1/simulator/match/run", json=body).json())
    assert job["status"] == "done", job.get("error")
    out = job["result"]
    assert out["seed"] == 1234 and out["toss"]["winner"] == "A" and out["batting_first"] == "B"
    for inn in out["innings"]:
        assert inn["scorecard"]["reconciliation"]["balanced"]
    assert out["player_of_match"]["player_id"]
    assert out["win_probability"]["available"]
    assert out["validation"]["venue"]["venue_id"] == venue
    again = wait(client.post("/api/v1/simulator/match/run", json=body).json())["result"]
    assert [i["runs"] for i in again["innings"]] == [i["runs"] for i in out["innings"]]  # seeded


def test_monte_carlo_job_reports_simulated_outcomes(xis):
    india, england = xis
    job = wait(client.post("/api/v1/simulator/match/monte-carlo", json=payload(india, england, seed=9, simulations=60)).json())
    assert job["status"] == "done", job.get("error")
    mc = job["result"]
    assert mc["simulations"] == 60
    assert sum(mc["win_pct"].values()) + mc["tie_pct"] >= 99.99
    assert 100 < mc["avg_first_innings"] < 260
    assert mc["influential_players"]


def test_invalid_setup_is_rejected_before_running(xis):
    india, england = xis
    res = client.post("/api/v1/simulator/match/run", json=payload(india[:9], england))
    assert res.status_code == 422
    assert client.get("/api/v1/simulator/jobs/doesnotexist").status_code == 404


def test_innings_projection_uses_the_engine(xis):
    india, england = xis
    state = {"format": "T20", "score": 50, "wickets": 2, "legal_balls": 42, "target_runs": 170,
             "batting_order": [p["id"] for p in india[2:]], "bowlers": [p["id"] for p in england[6:]],
             "simulations": 200, "seed": 3}
    res = client.post("/api/v1/simulator/simulate", json={"state": state})
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["expected_final_score"] > 50 and 0 <= data["target_reach_probability"] <= 1
    res = client.post("/api/v1/simulator/bowling-options", json={"state": state, "options": [p["id"] for p in england[7:]], "scenarios": 100})
    assert res.status_code == 200, res.text
    assert len(res.json()["options"]) == 4
