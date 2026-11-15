"""
Integration tests for FastAPI endpoints against the real database.
"""
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.db.session import SessionLocal

client = TestClient(app)


def test_health():
    res = client.get("/api/v1/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["database"] == "ok"


def test_coverage():
    res = client.get("/api/v1/dataset/coverage")
    assert res.status_code == 200
    data = res.json()
    assert data["total_matches"] > 0
    assert data["total_players"] > 0
    assert "T20" in data["formats"]


def test_players_listing():
    res = client.get("/api/v1/players?page=1&page_size=10")
    assert res.status_code == 200
    data = res.json()
    assert data["total"] > 0
    assert len(data["players"]) == 10
    first_player = data["players"][0]
    assert "id" in first_player
    assert "name" in first_player


def test_player_batting_and_phases():
    # Pick a player from the list
    list_res = client.get("/api/v1/players?page_size=1")
    player_id = list_res.json()["players"][0]["id"]

    res = client.get(f"/api/v1/players/{player_id}/batting")
    assert res.status_code == 200
    bat = res.json()
    assert bat["player_id"] == player_id
    assert "runs" in bat
    assert "balls_faced" in bat

    # Phases
    phase_res = client.get(f"/api/v1/players/{player_id}/phases?role=batting")
    assert phase_res.status_code == 200
    phases = phase_res.json()
    assert len(phases) >= 3


def test_scouting_search():
    payload = {
        "format": "T20",
        "minimum_innings": 5,
        "minimum_balls_faced": 50,
        "priorities": {
            "batting_average": 0.3,
            "strike_rate": 0.3,
            "middle_over_scoring": 0.2,
            "death_over_scoring": 0.1,
            "consistency": 0.1
        }
    }
    res = client.post("/api/v1/scouting/search", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert "candidates" in data
    assert "total_eligible" in data
    assert data["total_eligible"] > 0
    top = data["candidates"][0]
    assert top["rank"] == 1
    assert "suitability_score" in top
    assert len(top["strengths"]) >= 0


def test_venues_listing():
    res = client.get("/api/v1/venues")
    assert res.status_code == 200
    venues = res.json()
    assert isinstance(venues, list)
    assert len(venues) > 0
    assert "venue_name" in venues[0]


def test_teams_listing_and_stats():
    res = client.get("/api/v1/teams")
    assert res.status_code == 200
    teams = res.json()
    assert isinstance(teams, list)
    assert len(teams) > 0
    first_team = teams[0]
    assert "id" in first_team
    assert "matches_played" in first_team

    # Query single team stats
    team_id = first_team["id"]
    stats_res = client.get(f"/api/v1/teams/{team_id}")
    assert stats_res.status_code == 200
    stats = stats_res.json()
    assert stats["team_id"] == team_id
    assert "wins" in stats
    assert "batting_first_wins" in stats
    assert stats["filters"]["gender"] == "all"
    assert {"home", "away", "neutral", "unknown"}.issubset(stats["home_away"])
    assert "team_country" in stats

    men = client.get(f"/api/v1/teams/{team_id}", params={"gender": "male"})
    women = client.get(f"/api/v1/teams/{team_id}", params={"gender": "female"})
    assert men.status_code == women.status_code == 200
    assert men.json()["filters"]["gender"] == "male"
    assert women.json()["filters"]["gender"] == "female"


def test_matchup_endpoint():
    # Pick two players
    res = client.get("/api/v1/players?page_size=2")
    p1 = res.json()["players"][0]["id"]
    p2 = res.json()["players"][1]["id"]
    matchup_res = client.get(f"/api/v1/matchups/{p1}/{p2}")
    assert matchup_res.status_code == 200
    m = matchup_res.json()
    assert "balls_faced" in m
    assert "batter_runs" in m
    assert "phases" in m

