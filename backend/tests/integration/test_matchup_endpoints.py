"""
Integration tests for Matchup Analysis API endpoints.
Tests:
- /matchups/filter-metadata
- /matchups/{batter_id}/{bowler_id}/summary (overall + year filtered)
- /matchups/{batter_id}/{bowler_id}/dismissals
- /matchups/{batter_id}/{bowler_id}/by-match
- /matchups/{batter_id}/{bowler_id}/by-over
- /matchups/{batter_id}/{bowler_id}/trends
- Cricket rules verification (balls faced != wides, bowler wickets, no-data matchups)
"""
import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

# Known players in DB: Virat Kohli and Jasprit Bumrah
KOHLI_ID = "5dbf3cbf-2274-4b20-8bad-896ec7a98f2d"
BUMRAH_ID = "c66feec5-a197-47b1-b134-c69213d7cb77"


def test_filter_metadata():
    response = client.get("/api/v1/matchups/filter-metadata")
    assert response.status_code == 200
    data = response.json()
    assert "years" in data
    assert "formats" in data
    assert "competitions" in data
    assert "venues" in data
    assert len(data["years"]) > 0
    assert len(data["formats"]) > 0
    # Years should be sorted
    assert data["years"] == sorted(data["years"])


def test_matchup_summary():
    response = client.get(f"/api/v1/matchups/{KOHLI_ID}/{BUMRAH_ID}/summary?format=T20")
    assert response.status_code == 200
    data = response.json()
    assert data["batter_name"] == "Virat Kohli"
    assert data["bowler_name"] == "Jasprit Bumrah"
    assert data["balls_faced"] > 50
    assert data["batter_runs"] > 50
    assert data["strike_rate"] is not None
    assert data["strike_rate"] > 100.0
    if data["dismissals"]:
        assert data["batting_average"] == round(data["batter_runs"] / data["dismissals"], 2)
    else:
        assert data["batting_average"] is None
    assert "bowling_average" not in data
    dismissals = client.get(f"/api/v1/matchups/{KOHLI_ID}/{BUMRAH_ID}/dismissals?format=T20")
    assert dismissals.status_code == 200
    assert data["dismissals"] == dismissals.json()["bowler_credited"]
    assert data["matches_count"] >= 10
    assert "phases" in data
    assert len(data["phases"]) == 3
    # Check phases
    phases = {p["phase"]: p for p in data["phases"]}
    assert "powerplay" in phases
    assert "middle" in phases
    assert "death" in phases
    assert phases["powerplay"]["balls"] > 0


def test_matchup_year_filtering():
    # Overall balls faced
    all_res = client.get(f"/api/v1/matchups/{KOHLI_ID}/{BUMRAH_ID}/summary")
    total_balls = all_res.json()["balls_faced"]

    # Filtered year range 2015 to 2018
    filtered_res = client.get(
        f"/api/v1/matchups/{KOHLI_ID}/{BUMRAH_ID}/summary?start_year=2015&end_year=2018"
    )
    assert filtered_res.status_code == 200
    filtered_balls = filtered_res.json()["balls_faced"]

    # Filtered should be strictly less than total but > 0
    assert 0 < filtered_balls < total_balls
    assert filtered_res.json()["filters_applied"]["start_year"] == 2015
    assert filtered_res.json()["filters_applied"]["end_year"] == 2018


def test_matchup_dismissals():
    response = client.get(f"/api/v1/matchups/{KOHLI_ID}/{BUMRAH_ID}/dismissals")
    assert response.status_code == 200
    data = response.json()
    assert data["total_dismissals"] >= 1
    assert data["bowler_wickets"] >= 1
    assert "by_type" in data
    assert sum(data["by_type"].values()) == data["total_dismissals"]


def test_matchup_by_match():
    response = client.get(
        f"/api/v1/matchups/{KOHLI_ID}/{BUMRAH_ID}/by-match?page=1&page_size=10"
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total"] >= 10
    assert len(data["matches"]) <= 10
    match = data["matches"][0]
    assert "date" in match
    assert "balls_faced" in match
    assert "runs" in match
    assert "dismissed" in match
    assert "over_numbers" in match


def test_matchup_by_over():
    response = client.get(f"/api/v1/matchups/{KOHLI_ID}/{BUMRAH_ID}/by-over")
    assert response.status_code == 200
    data = response.json()
    assert "overs" in data
    assert len(data["overs"]) > 0
    # Over numbers should be sorted
    over_nums = [o["over_number"] for o in data["overs"]]
    assert over_nums == sorted(over_nums)


def test_matchup_trends():
    response = client.get(f"/api/v1/matchups/{KOHLI_ID}/{BUMRAH_ID}/trends")
    assert response.status_code == 200
    data = response.json()
    assert "by_year" in data
    assert len(data["by_year"]) >= 5
    assert "by_innings" in data
    assert len(data["by_innings"]) >= 1


def test_matchup_nonexistent_player():
    response = client.get("/api/v1/matchups/invalid-id-123/invalid-id-456/summary")
    assert response.status_code == 404


def test_matchup_no_records_pair():
    # Two players who never faced each other
    # e.g., bowler vs bowler or players from different eras
    players_res = client.get("/api/v1/players?page_size=10")
    players = players_res.json()["players"]
    p1 = players[0]["id"]
    p2 = players[1]["id"]
    response = client.get(f"/api/v1/matchups/{p1}/{p2}/summary")
    assert response.status_code == 200
    data = response.json()
    assert data["total_deliveries"] >= 0
    if data["dismissals"] == 0:
        assert data["batting_average"] is None
