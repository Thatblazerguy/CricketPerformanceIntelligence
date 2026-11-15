"""Scouting intelligence against the real CPI database.

Validates the persisted per-innings aggregates against raw deliveries for real
players, then exercises the ranking, report and comparison endpoints.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.analytics.scouting_aggregates import tables_exist
from app.db.session import SessionLocal
from app.main import app

client = TestClient(app)
API = "/api/v1/scouting/v2"


@pytest.fixture(scope="module")
def db():
    session = SessionLocal()
    if not tables_exist(session) or not session.execute(text("SELECT 1 FROM scouting_bat_innings LIMIT 1")).scalar():
        pytest.skip("scouting aggregates not built")
    yield session
    session.close()


def _top_player(db, table, fmt, measure):
    return db.execute(text(f"""
        SELECT player_id FROM {table} WHERE match_format = :f AND gender = 'male'
        GROUP BY player_id ORDER BY SUM({measure}) DESC LIMIT 1"""), {"f": fmt}).scalar()


@pytest.mark.parametrize("fmt", ["T20", "ODI", "Test"])
def test_batting_aggregates_reconcile_with_raw_deliveries(db, fmt):
    pid = _top_player(db, "scouting_bat_innings", fmt, "balls")
    agg = db.execute(text("""
        SELECT SUM(runs) runs, SUM(balls) balls, SUM(dismissed::int) outs, SUM(fours) fours, SUM(sixes) sixes,
               SUM(dots) dots, SUM(pp_balls + mid_balls + death_balls) phase_balls, COUNT(*) innings
        FROM scouting_bat_innings WHERE player_id = :p AND match_format = :f"""), {"p": pid, "f": fmt}).mappings().one()
    raw = db.execute(text("""
        SELECT SUM(d.batter_runs) runs,
               COUNT(*) FILTER (WHERE d.is_ball_faced_by_batter) balls,
               COUNT(*) FILTER (WHERE d.is_ball_faced_by_batter AND d.is_boundary_four) fours,
               COUNT(*) FILTER (WHERE d.is_ball_faced_by_batter AND d.is_boundary_six) sixes,
               COUNT(*) FILTER (WHERE d.is_ball_faced_by_batter AND d.batter_runs = 0) dots,
               COUNT(*) FILTER (WHERE d.is_ball_faced_by_batter AND d.phase IN ('powerplay','middle','death')) phase_balls
        FROM deliveries d JOIN match_innings mi ON mi.id = d.innings_id JOIN matches m ON m.id = mi.match_id
        WHERE d.batter_id = :p AND m.match_format = :f AND NOT mi.is_super_over"""), {"p": pid, "f": fmt}).mappings().one()
    raw_outs = db.execute(text("""
        SELECT COUNT(DISTINCT (d.innings_id)) FROM wickets w JOIN deliveries d ON d.id = w.delivery_id
        JOIN match_innings mi ON mi.id = d.innings_id JOIN matches m ON m.id = mi.match_id
        WHERE w.player_out_id = :p AND w.is_batter_dismissed AND m.match_format = :f AND NOT mi.is_super_over"""),
        {"p": pid, "f": fmt}).scalar()
    raw_innings = db.execute(text("""
        SELECT COUNT(DISTINCT d.innings_id) FROM deliveries d JOIN match_innings mi ON mi.id = d.innings_id
        JOIN matches m ON m.id = mi.match_id
        WHERE (d.batter_id = :p OR d.non_striker_id = :p) AND m.match_format = :f AND NOT mi.is_super_over"""),
        {"p": pid, "f": fmt}).scalar()
    for key in ("runs", "balls", "fours", "sixes", "dots", "phase_balls"):
        assert agg[key] == raw[key], key
    assert agg["outs"] == raw_outs
    assert agg["innings"] == raw_innings
    if fmt == "Test":
        assert agg["phase_balls"] == 0  # no T20/ODI phases in multi-day cricket


def test_bowling_aggregates_reconcile_with_raw_deliveries(db):
    pid = _top_player(db, "scouting_bowl_innings", "T20", "legal_balls")
    agg = db.execute(text("""
        SELECT SUM(legal_balls) balls, SUM(runs) runs, SUM(wickets) wkts, SUM(dots) dots, SUM(wides) wides,
               SUM(noballs) noballs, SUM(pp_wkts + mid_wkts + death_wkts) phase_wkts,
               SUM(wk_bowled + wk_lbw + wk_caught + wk_stumped + wk_other) typed_wkts
        FROM scouting_bowl_innings WHERE player_id = :p AND match_format = 'T20'"""), {"p": pid}).mappings().one()
    raw = db.execute(text("""
        SELECT COUNT(*) FILTER (WHERE d.is_legal_ball) balls, SUM(d.bowling_runs) runs,
               COUNT(*) FILTER (WHERE d.is_legal_ball AND d.bowling_runs = 0) dots,
               COUNT(*) FILTER (WHERE NOT d.is_ball_faced_by_batter) wides,
               COUNT(*) FILTER (WHERE d.is_ball_faced_by_batter AND NOT d.is_legal_ball) noballs
        FROM deliveries d JOIN match_innings mi ON mi.id = d.innings_id JOIN matches m ON m.id = mi.match_id
        WHERE d.bowler_id = :p AND m.match_format = 'T20' AND NOT mi.is_super_over"""), {"p": pid}).mappings().one()
    raw_wkts = db.execute(text("""
        SELECT COUNT(*) FROM wickets w JOIN deliveries d ON d.id = w.delivery_id
        JOIN match_innings mi ON mi.id = d.innings_id JOIN matches m ON m.id = mi.match_id
        WHERE d.bowler_id = :p AND w.is_bowler_wicket AND m.match_format = 'T20' AND NOT mi.is_super_over"""),
        {"p": pid}).scalar()
    for key in ("balls", "runs", "dots", "wides", "noballs"):
        assert agg[key] == raw[key], key
    assert agg["wkts"] == raw_wkts == agg["phase_wkts"] == agg["typed_wkts"]


def test_batting_positions_are_unique_and_openers_enter_together(db):
    dup = db.execute(text("""
        SELECT COUNT(*) FROM (SELECT innings_id, batting_position FROM scouting_bat_innings
        WHERE match_format = 'T20' GROUP BY 1, 2 HAVING COUNT(*) > 1) s""")).scalar()
    assert dup == 0
    openers = db.execute(text("""
        SELECT MAX(entry_wickets), MAX(entry_over) FROM scouting_bat_innings
        WHERE match_format = 'T20' AND batting_position <= 2""")).one()
    assert openers == (0, 0)
    # A batter at #k cannot enter with more than k-1 wickets down (k-1 only when two batters
    # left on the same delivery, e.g. run out + retired out), and normally enters with k-2.
    bad = db.execute(text("""SELECT COUNT(*) FROM scouting_bat_innings
        WHERE batting_position >= 3 AND entry_wickets > batting_position - 1""")).scalar()
    assert bad == 0
    typical = db.execute(text("""SELECT AVG((entry_wickets = batting_position - 2)::int) FROM scouting_bat_innings
        WHERE batting_position >= 3""")).scalar()
    assert typical > 0.95


def test_pace_spin_splits_never_exceed_balls_faced(db):
    bad = db.execute(text("""SELECT COUNT(*) FROM scouting_bat_innings
        WHERE pace_balls + spin_balls > balls OR pp_balls + mid_balls + death_balls > balls""")).scalar()
    assert bad == 0


def test_options_report_coverage_limits(db):
    res = client.get(f"{API}/options")
    assert res.status_code == 200
    data = res.json()
    assert {r["key"] for r in data["roles"]} >= {"opener", "middle_order", "finisher", "pace_bowler", "spin_bowler",
                                                 "all_rounder", "wicketkeeper_batter"}
    assert any("Batting hand" in note for note in data["coverage"]["notes"])
    assert "Left-arm Orthodox" in data["bowling_styles"]


def test_target_query_middle_order_indian_t20_batters(db):
    res = client.post(f"{API}/rank", json={
        "format": "T20", "role": "middle_order", "nationality": "India", "min_innings": 30,
        "requirements": [{"metric": "spin_sr", "op": "min", "value": 115}],
        "weights": {"mid_sr_index": 2, "spin_sr": 2, "spin_avg": 1, "significant_pct": 1},
    })
    assert res.status_code == 200
    data = res.json()
    assert data["total_candidates"] > 5
    scores = [c["score"] for c in data["candidates"]]
    assert scores == sorted(scores, reverse=True)
    for cand in data["candidates"]:
        assert cand["identity"]["nationality"] == "India"
        assert cand["sample"]["batting"]["innings"] >= 30
        spin = next(m for m in cand["metrics"] if m["metric"] == "spin_sr")
        assert spin["value"] >= 115
        assert sum(m["weight"] for m in cand["metrics"]) == pytest.approx(1.0, abs=1e-3)
    assert {e["reason"] for e in data["exclusions"]} >= {"nationality"}
    weights = {w["metric"]: w["weight"] for w in data["weights"]["bat"]}
    assert weights["mid_sr_index"] == pytest.approx(2 / 6, abs=1e-3)


def test_metric_values_match_underlying_sample(db):
    data = client.post(f"{API}/rank", json={"format": "T20", "role": "batter", "min_innings": 50, "limit": 5}).json()
    cand = data["candidates"][0]
    pid = cand["identity"]["player_id"]
    row = db.execute(text("""SELECT SUM(runs) r, SUM(balls) b FROM scouting_bat_innings
        WHERE player_id = :p AND match_format = 'T20' AND gender = 'male'"""), {"p": pid}).one()
    assert cand["sample"]["batting"]["runs"] == row.r and cand["sample"]["batting"]["balls"] == row.b
    boundary = next(m for m in cand["metrics"] if m["metric"] == "boundary_pct")
    assert boundary["n"] == row.b
    assert boundary["ci"][0] <= boundary["value"] <= boundary["ci"][1]


def test_report_sections_and_match_evidence(db):
    rank = client.post(f"{API}/rank", json={"format": "T20", "role": "middle_order", "min_innings": 40, "limit": 1}).json()
    pid = rank["candidates"][0]["identity"]["player_id"]
    rep = client.get(f"{API}/player/{pid}/report", params={"format": "T20", "role": "middle_order"}).json()
    assert rep["available"]
    for section in ("overview", "role", "batting", "strengths", "weaknesses", "reliability", "recruitment"):
        assert section in rep
    bat = rep["batting"]
    assert [p["phase"] for p in bat["phases"]] == ["Powerplay", "Middle overs", "Death overs"]
    assert bat["summary"]["innings"] == sum(b["innings"] for b in bat["consistency"]["distribution"])
    top = bat["evidence"]["top_innings"][0]
    assert top["match_id"] and top["date"] and top["runs"] == bat["summary"]["highest"]
    assert any(r["role"] == "middle_order" for r in rep["recruitment"]["role_fit"])
    fmts = client.get(f"{API}/player/{pid}/formats").json()
    assert all(f["format"] in ("T20", "T20I", "ODI", "ODM", "Test", "MDM") for f in fmts["formats"])


def test_compare_and_validation_errors(db):
    rank = client.post(f"{API}/rank", json={"format": "T20", "role": "spin_bowler", "min_innings": 20, "limit": 3}).json()
    ids = [c["identity"]["player_id"] for c in rank["candidates"]]
    assert all(c["identity"]["bowling_type"].lower() == "spin" for c in rank["candidates"])
    cmp = client.post(f"{API}/compare", json={"format": "T20", "role": "spin_bowler", "player_ids": ids}).json()
    assert [p["player_id"] for p in cmp["players"]] == ids
    assert all(p["bowling"]["career"]["legal_balls"] > 0 for p in cmp["players"])
    assert client.post(f"{API}/rank", json={"format": "Test", "role": "finisher"}).status_code == 422
    assert client.post(f"{API}/rank", json={"format": "T20", "role": "batter",
                                            "requirements": [{"metric": "nope", "op": "min", "value": 1}]}).status_code == 422
    assert client.post(f"{API}/rank", json={"format": "Test", "role": "batter",
                                            "requirements": [{"metric": "death_sr", "op": "min", "value": 1}]}).status_code == 422
