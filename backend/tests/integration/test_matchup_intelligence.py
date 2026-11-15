"""Matchup intelligence against the real CPI database.

Every headline number is re-derived independently from raw tables (matches,
match_innings, deliveries, wickets) and compared with the API output.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.analytics.competition_common import clear_cache
from app.db.session import SessionLocal
from app.main import app

client = TestClient(app)
API = "/api/v1/matchups"


@pytest.fixture(scope="module")
def db():
    session = SessionLocal()
    if not session.execute(text("SELECT to_regclass('public.team_innings_summary') IS NOT NULL")).scalar():
        pytest.skip("team_innings_summary not built")
    clear_cache()
    yield session
    session.close()


@pytest.fixture(scope="module")
def rivalry(db):
    """The most-played men's T20 fixture in the database."""
    row = db.execute(text("""
        SELECT LEAST(team1_id, team2_id) a, GREATEST(team1_id, team2_id) b, COUNT(*) n
        FROM matches WHERE match_format = 'T20' AND lower(gender) = 'male' AND team1_id IS NOT NULL AND team2_id IS NOT NULL
        GROUP BY 1, 2 ORDER BY n DESC LIMIT 1""")).one()
    return row.a, row.b


@pytest.fixture(scope="module")
def pair(db):
    """The batter/bowler pair with the most balls between them in T20."""
    row = db.execute(text("""
        SELECT d.batter_id, d.bowler_id FROM deliveries d
        JOIN match_innings mi ON mi.id = d.innings_id JOIN matches m ON m.id = mi.match_id
        WHERE m.match_format = 'T20' AND d.is_ball_faced_by_batter AND m.start_date >= '2022-01-01'
        GROUP BY 1, 2 ORDER BY COUNT(*) DESC LIMIT 1""")).one()
    return row.batter_id, row.bowler_id


def test_team_record_matches_raw_results(db, rivalry):
    a, b = rivalry
    r = client.get(f"{API}/team-analysis", params={"a": a, "b": b, "format": "T20", "gender": "male"})
    assert r.status_code == 200, r.text
    d = r.json()
    raw = db.execute(text("""
        SELECT COUNT(*) n,
               COUNT(*) FILTER (WHERE winner_id = :a AND lower(coalesce(result_type,'')) NOT IN ('tie','tied','no result','abandoned','draw')) a_won,
               COUNT(*) FILTER (WHERE winner_id = :b AND lower(coalesce(result_type,'')) NOT IN ('tie','tied','no result','abandoned','draw')) b_won,
               COUNT(*) FILTER (WHERE toss_winner_id = winner_id AND winner_id IS NOT NULL
                                AND lower(coalesce(result_type,'')) NOT IN ('tie','tied','no result','abandoned','draw')) toss_won
        FROM matches WHERE match_format = 'T20' AND lower(gender) = 'male'
          AND ((team1_id = :a AND team2_id = :b) OR (team1_id = :b AND team2_id = :a))"""), {"a": a, "b": b}).one()
    o = d["overview"]
    assert o["matches"] == raw.n
    assert o["a"]["won"] == raw.a_won and o["b"]["won"] == raw.b_won
    assert o["a"]["won"] == o["b"]["lost"]  # no double counting
    assert d["toss_innings"]["toss"]["toss_winner_won"]["k"] == raw.toss_won
    assert d["encounters"]["total"] == raw.n
    # Win % uses decided matches as the denominator.
    if o["a"]["decided"]:
        assert o["a"]["win_percentage"] == round(100 * raw.a_won / o["a"]["decided"], 1)


def test_team_highest_total_matches_raw_deliveries(db, rivalry):
    a, b = rivalry
    d = client.get(f"{API}/team-analysis", params={"a": a, "b": b, "format": "T20", "gender": "male"}).json()
    top = d["records"]["highest_totals"][0]
    raw = db.execute(text("""
        SELECT SUM(d.total_runs) FROM deliveries d JOIN match_innings mi ON mi.id = d.innings_id
        WHERE mi.match_id = :m AND mi.innings_number = :i AND mi.is_super_over = FALSE"""),
        {"m": top["match_id"], "i": top["innings_number"]}).scalar()
    assert raw == top["runs"]
    best = db.execute(text("""
        SELECT MAX(t) FROM (SELECT SUM(d.total_runs) t FROM deliveries d JOIN match_innings mi ON mi.id = d.innings_id
        JOIN matches m ON m.id = mi.match_id
        WHERE m.match_format = 'T20' AND lower(m.gender) = 'male' AND mi.is_super_over = FALSE
          AND ((m.team1_id = :a AND m.team2_id = :b) OR (m.team1_id = :b AND m.team2_id = :a)) GROUP BY mi.id) x"""), {"a": a, "b": b}).scalar()
    assert best == top["runs"]


def test_team_filters_narrow_consistently(rivalry):
    a, b = rivalry
    base = {"a": a, "b": b, "format": "T20", "gender": "male"}
    full = client.get(f"{API}/team-analysis", params=base).json()
    first = client.get(f"{API}/team-analysis", params={**base, "order": "a_bat_first"}).json()
    second = client.get(f"{API}/team-analysis", params={**base, "order": "a_chasing"}).json()
    assert first["overview"]["matches"] + second["overview"]["matches"] <= full["overview"]["matches"]
    assert first["overview"]["a"]["won"] == full["toss_innings"]["order_by_team"][a]["batting_first"]["won"]
    recent = client.get(f"{API}/team-analysis", params={**base, "recent": 5}).json()
    assert recent["overview"]["matches"] == min(5, full["overview"]["matches"])
    venue = full["venues"][0]
    at = client.get(f"{API}/team-analysis", params={**base, "venue_id": venue["venue_id"]}).json()
    assert at["overview"]["matches"] == venue["matches"]
    assert at["venue"]["head_to_head"]["matches"] == venue["matches"]
    # Season rows add up to the whole.
    assert sum(s["matches"] for s in full["seasons"]) == full["overview"]["matches"]


def test_team_encounters_pagination_and_ids(db, rivalry):
    a, b = rivalry
    p = {"a": a, "b": b, "format": "T20", "gender": "male", "page_size": 5}
    p1 = client.get(f"{API}/team-encounters", params={**p, "page": 1}).json()
    p2 = client.get(f"{API}/team-encounters", params={**p, "page": 2}).json()
    ids = [i["match_id"] for i in p1["items"] + p2["items"]]
    assert len(ids) == len(set(ids)) == min(10, p1["total"])
    dates = [i["date"] for i in p1["items"] + p2["items"]]
    assert dates == sorted(dates, reverse=True)
    for mid in ids:  # every link resolves to a real match between these teams
        row = db.execute(text("SELECT team1_id, team2_id FROM matches WHERE id = :m"), {"m": mid}).one()
        assert {row.team1_id, row.team2_id} == {a, b}


def test_player_matchup_matches_raw_deliveries(db, pair):
    bat, bowl = pair
    r = client.get(f"{API}/player-analysis", params={"batter_id": bat, "bowler_id": bowl, "format": "T20"})
    assert r.status_code == 200, r.text
    d = r.json()
    raw = db.execute(text("""
        SELECT COUNT(*) FILTER (WHERE d.is_ball_faced_by_batter) balls,
               COALESCE(SUM(d.batter_runs), 0) runs,
               COUNT(*) FILTER (WHERE d.is_boundary_four AND d.is_ball_faced_by_batter) fours,
               COUNT(*) FILTER (WHERE d.is_boundary_six AND d.is_ball_faced_by_batter) sixes,
               COUNT(*) FILTER (WHERE d.is_ball_faced_by_batter AND d.batter_runs = 0) dots,
               COUNT(*) FILTER (WHERE NOT d.is_ball_faced_by_batter) wides,
               COUNT(DISTINCT m.id) matches
        FROM deliveries d JOIN match_innings mi ON mi.id = d.innings_id AND mi.is_super_over = FALSE
        JOIN matches m ON m.id = mi.match_id
        WHERE d.batter_id = :a AND d.bowler_id = :b AND m.match_format = 'T20'"""), {"a": bat, "b": bowl}).one()
    outs = db.execute(text("""
        SELECT COUNT(*) FILTER (WHERE w.is_bowler_wicket) credited, COUNT(*) total
        FROM wickets w JOIN deliveries d ON d.id = w.delivery_id
        JOIN match_innings mi ON mi.id = d.innings_id AND mi.is_super_over = FALSE JOIN matches m ON m.id = mi.match_id
        WHERE d.batter_id = :a AND d.bowler_id = :b AND w.player_out_id = :a AND w.is_batter_dismissed
          AND m.match_format = 'T20'"""), {"a": bat, "b": bowl}).one()
    o = d["overall"]
    assert (o["balls"], o["runs"], o["fours"], o["sixes"], o["dots"], o["wides"]) == \
        (raw.balls, raw.runs, raw.fours, raw.sixes, raw.dots, raw.wides)
    assert o["dismissals"] == outs.credited and o["all_dismissals"] == outs.total
    assert d["matches"] == raw.matches
    assert o["strike_rate"] == round(100 * raw.runs / raw.balls, 2)
    # Every split adds up to the headline.
    for split in ("seasons", "venues", "innings_split", "competitions", "home_away"):
        assert sum(x["balls"] for x in d[split]) == o["balls"], split
        assert sum(x["runs"] for x in d[split]) == o["runs"], split
    assert sum(x["balls"] for x in d["scoring_distribution"]) == o["balls"]
    assert sum(x["runs"] for x in d["scoring_distribution"]) == o["runs"]
    assert sum(x["balls"] for x in d["by_match"]) == o["balls"]
    assert sum(d["dismissals"]["by_type"].values()) == outs.total
    for p in d["phases"]:
        assert sum(x["balls"] for x in p["phases"]) == p["balls"]


def test_player_filters_and_insights_are_grounded(pair):
    bat, bowl = pair
    base = {"batter_id": bat, "bowler_id": bowl, "format": "T20"}
    full = client.get(f"{API}/player-analysis", params=base).json()
    i1 = client.get(f"{API}/player-analysis", params={**base, "innings": 1}).json()
    i2 = client.get(f"{API}/player-analysis", params={**base, "innings": 2}).json()
    assert i1["overall"]["balls"] + i2["overall"]["balls"] == full["overall"]["balls"]
    recent = client.get(f"{API}/player-analysis", params={**base, "recent": 3}).json()
    assert recent["matches"] == min(3, full["matches"])
    for ins in full["insights"]:
        assert ins["basis"] and ins["n"] >= 0 and ins["type"] == "historical"
    assert full["context"]["baseline_formats"] == ["T20"]


def test_validation_errors():
    assert client.get(f"{API}/team-analysis", params={"a": "x", "b": "x"}).status_code == 422
    assert client.get(f"{API}/team-analysis", params={"a": "x", "b": "y", "side": "moon"}).status_code == 422
    assert client.get(f"{API}/team-analysis", params={"a": "x", "b": "y", "date_from": "2020-13-40"}).status_code == 422
    assert client.get(f"{API}/team-analysis", params={"a": "x", "b": "y"}).status_code == 404
    assert client.get(f"{API}/player-analysis", params={"batter_id": "x", "bowler_id": "y"}).status_code == 404
