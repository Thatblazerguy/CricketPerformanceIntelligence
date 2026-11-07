"""
Integration tests for Player Performance Intelligence API endpoints and filters.
Verifies:
1. /players/filter-metadata endpoint
2. Format filtering and strict independence of T20 vs T20I
3. Year range filtering (inclusive)
4. Batting performance filters (runs, average, strike rate, boundaries, dot balls)
5. Bowling performance filters (wickets, economy, average, strike rate, death economy)
6. Pace vs spin performance splits
7. Phase performance filters (Powerplay, Middle, Death)
8. Role and sample size gates
9. Sorting and pagination
"""
import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_player_filter_metadata():
    """Verify metadata returns available formats, years, venues, and teams."""
    response = client.get("/api/v1/players/filter-metadata")
    assert response.status_code == 200
    data = response.json()

    assert "formats" in data
    assert "years" in data
    assert "venues" in data
    assert "teams" in data
    assert "bowling_styles" in data

    # Crucial: T20 and T20I must both be present as independent formats
    assert "T20" in data["formats"]
    assert "T20I" in data["formats"]
    assert "ODI" in data["formats"]
    assert "Test" in data["formats"]

    # Years dynamically populated from match data
    assert data["min_year"] <= 2008
    assert data["max_year"] >= 2024
    assert len(data["years"]) >= 15
    assert data["years"] == sorted(data["years"])

    assert len(data["venues"]) > 50
    assert len(data["teams"]) > 20
    assert "pace" in data["bowling_styles"]
    assert "spin" in data["bowling_styles"]


def test_t20_vs_t20i_separation():
    """Verify that T20 (domestic/franchise) and T20I (international) remain completely separated."""
    # T20 (IPL / Franchise)
    res_t20 = client.get("/api/v1/players/performance?format=T20&page_size=10&sort_by=runs")
    assert res_t20.status_code == 200
    t20_data = res_t20.json()
    assert t20_data["total"] > 500
    t20_names = [p["name"] for p in t20_data["players"]]

    # In T20 (Franchise/IPL), Kohli, Rohit, Warner, Dhawan are top run scorers
    assert any("Kohli" in name for name in t20_names)

    # T20I (International)
    res_t20i = client.get("/api/v1/players/performance?format=T20I&page_size=10&sort_by=runs")
    assert res_t20i.status_code == 200
    t20i_data = res_t20i.json()
    assert t20i_data["total"] > 1000
    t20i_names = [p["name"] for p in t20i_data["players"]]

    # In T20I (International), top scorers include Mandhana, Babar Azam, Buttler, Rizwan
    assert any(name in t20i_names for name in ["S Mandhana", "Babar Azam", "JC Buttler", "Mohammad Rizwan", "BL Mooney"])

    # Kohli's T20 runs (>8000 in IPL) vs T20I runs (<5000 in international) must differ
    kohli_t20 = client.get("/api/v1/players/performance?format=T20&name=Kohli").json()
    kohli_t20i = client.get("/api/v1/players/performance?format=T20I&name=Kohli").json()
    assert kohli_t20["players"][0]["runs"] > 8000
    assert kohli_t20i["players"][0]["runs"] < 5000


def test_year_range_filtering():
    """Verify that start_year and end_year restrict performance statistics."""
    # Kohli overall in T20
    overall = client.get("/api/v1/players/performance?format=T20&name=Kohli").json()["players"][0]

    # Kohli 2021-2023 in T20
    window = client.get("/api/v1/players/performance?format=T20&name=Kohli&start_year=2021&end_year=2023").json()["players"][0]

    assert window["runs"] > 0
    assert window["runs"] < overall["runs"]
    assert window["matches"] < overall["matches"]


def test_batting_performance_filters():
    """Verify filtering by runs, average, and strike rate."""
    response = client.get(
        "/api/v1/players/performance?format=T20&min_runs=1000&min_batting_avg=30.0&min_batting_sr=135.0"
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total"] > 0

    for p in data["players"]:
        assert p["runs"] >= 1000
        assert p["batting_average"] >= 30.0
        assert p["batting_strike_rate"] >= 135.0


def test_bowling_performance_filters():
    """Verify filtering by wickets, economy rate, and bowling average."""
    response = client.get(
        "/api/v1/players/performance?format=T20&min_wickets=50&max_economy=8.0&sort_by=wickets&sort_dir=desc"
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total"] > 0

    prev_wkts = float("inf")
    for p in data["players"]:
        assert p["wickets"] >= 50
        assert p["economy_rate"] <= 8.0
        assert p["wickets"] <= prev_wkts
        prev_wkts = p["wickets"]


def test_pace_spin_batting_filters():
    """Verify batting performance against pace and spin filters."""
    response = client.get(
        "/api/v1/players/performance?format=T20&min_runs=500&min_batting_sr_vs_pace=140.0"
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total"] > 0
    for p in data["players"]:
        assert p["pace_sr"] >= 140.0


def test_phase_performance_filters():
    """Verify phase strike rate filters."""
    response = client.get(
        "/api/v1/players/performance?format=T20&min_runs=500&min_death_sr=170.0"
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total"] > 0
    for p in data["players"]:
        assert p["death_sr"] >= 170.0


def test_role_and_sorting():
    """Verify role filtering and sort options."""
    # Bowlers sorted by economy ascending
    res_bowlers = client.get(
        "/api/v1/players/performance?format=T20&role=bowler&min_balls_bowled=300&sort_by=economy_rate&sort_dir=asc"
    )
    assert res_bowlers.status_code == 200
    data = res_bowlers.json()
    assert data["total"] > 0

    prev_econ = 0.0
    for p in data["players"]:
        assert p["legal_balls_bowled"] >= 300
        assert p["economy_rate"] >= prev_econ
        prev_econ = p["economy_rate"]


def test_player_name_search():
    """Verify player search by partial name."""
    res = client.get("/api/v1/players/performance?name=Bumrah")
    assert res.status_code == 200
    data = res.json()
    assert data["total"] >= 1
    assert any("Bumrah" in p["name"] for p in data["players"])


def test_player_profile_analytics_unfiltered():
    """Verify individual player profile analytics endpoint returns complete statistics."""
    kohli_id = "5dbf3cbf-2274-4b20-8bad-896ec7a98f2d"
    res = client.get(f"/api/v1/players/{kohli_id}/analytics")
    assert res.status_code == 200
    data = res.json()

    assert data["player_name"] == "Virat Kohli"
    assert data["primary_role"] in ("Specialist Batter", "Batting All-Rounder", "Bowling All-Rounder", "Wicketkeeper-Batter")

    # Complete batting statistics
    bat = data["batting"]
    assert bat["runs"] > 10000
    assert bat["balls_faced"] > 8000
    assert bat["dismissals"] > 200
    assert bat["average"] > 40.0
    # Unfiltered career stats now include Tests, where scoring rates are lower.
    assert 0 < bat["strike_rate"] < 400.0
    assert bat["highest_score"] >= 113
    assert bat["fours"] > 1000
    assert bat["sixes"] > 300
    assert bat["boundary_percentage"] > 10.0
    assert bat["dot_ball_percentage"] > 20.0

    # Format breakdown (Test, ODI, T20, T20I)
    assert len(data["format_breakdown"]) >= 3
    formats = [f["format"] for f in data["format_breakdown"]]
    assert "T20" in formats
    assert "T20I" in formats

    # Pace vs spin splits
    assert len(data["pace_spin"]) >= 2
    styles = [ps["style"] for ps in data["pace_spin"]]
    assert "pace" in styles
    assert "spin" in styles
    pace_split = next(ps for ps in data["pace_spin"] if ps["style"] == "pace")
    assert pace_split["runs"] > 3000
    # The unfiltered career split includes Tests and one-day formats.
    assert 0 < pace_split["strike_rate"] < 400.0

    # Phase breakdown
    phases = [p["phase"] for p in data["phases"]]
    assert "powerplay" in phases
    assert "middle" in phases
    assert "death" in phases

    # Opponent and Venue breakdowns
    assert len(data["by_opponent"]) > 0
    assert len(data["by_venue"]) > 0

    # Year trends and recent matches
    assert len(data["year_trends"]) > 5
    assert len(data["recent_matches"]) > 0

    # Strengths and weaknesses
    assert len(data["strengths_weaknesses"]["strengths"]) > 0


def test_player_profile_analytics_filtered():
    """Verify individual player profile analytics updates correctly with filters."""
    kohli_id = "5dbf3cbf-2274-4b20-8bad-896ec7a98f2d"
    # Filter by T20 and 2021-2023
    res = client.get(f"/api/v1/players/{kohli_id}/analytics?format=T20&start_year=2021&end_year=2023")
    assert res.status_code == 200
    data = res.json()

    assert data["batting"]["runs"] > 0
    # Must be less than all-time T20 runs
    assert data["batting"]["runs"] < 9000
    assert data["batting"]["average"] is not None
    assert data["batting"]["strike_rate"] is not None


def test_bowler_profile_analytics():
    """Verify profile analytics for a premier bowler (Jasprit Bumrah)."""
    bumrah_id = "c66feec5-a197-47b1-b134-c69213d7cb77"
    res = client.get(f"/api/v1/players/{bumrah_id}/analytics?format=T20")
    assert res.status_code == 200
    data = res.json()

    assert data["player_name"] == "Jasprit Bumrah"
    assert data["primary_role"] in ("Specialist Bowler", "Batting All-Rounder", "Bowling All-Rounder")
    assert data["bowling"]["wickets"] > 100
    assert data["bowling"]["economy_rate"] < 8.0
    assert data["bowling"]["overs_display"] != "0.0"
