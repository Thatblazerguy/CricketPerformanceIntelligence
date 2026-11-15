"""Auction Intelligence v2 against the real CPI database.

Checks data integrity of the reconciled auction lots, leakage-freedom of the
point-in-time features, and the simulator / optimiser constraints.
"""
from datetime import date

import pytest
from sqlalchemy import text

from app.db.session import SessionLocal


@pytest.fixture(scope="module")
def db():
    session = SessionLocal()
    try:
        n = session.execute(text("SELECT COUNT(*) FROM auction_lots")).scalar()
    except Exception:
        pytest.skip("auction v2 tables not migrated")
    if not n:
        pytest.skip("auction lots not built (POST /auction/v2/rebuild)")
    yield session
    session.close()


def test_recent_seasons_match_published_counts(db):
    rows = dict(db.execute(text("""SELECT season, COUNT(*) FROM auction_lots WHERE status='SOLD' AND season IN (2024, 2026)
                                    GROUP BY season""")).all())
    assert rows == {2024: 72, 2026: 77}  # Wikipedia infobox / table totals
    spend_2026 = db.execute(text("SELECT SUM(final_price_lakh) FROM auction_lots WHERE season=2026 AND status='SOLD'")).scalar()
    assert float(spend_2026) == pytest.approx(21545, abs=1)


def test_no_duplicate_player_season_outcomes(db):
    dups = db.execute(text("""SELECT season, player_id, acquisition_type, COUNT(*) FROM auction_lots
                              WHERE player_id IS NOT NULL GROUP BY 1, 2, 3 HAVING COUNT(*) > 1""")).all()
    assert dups == []


def test_unsold_lots_have_no_price_and_sold_lots_do(db):
    assert db.execute(text("SELECT COUNT(*) FROM auction_lots WHERE status='UNSOLD' AND final_price_lakh IS NOT NULL")).scalar() == 0
    assert db.execute(text("SELECT COUNT(*) FROM auction_lots WHERE status='SOLD' AND (final_price_lakh IS NULL OR final_price_lakh <= 0)")).scalar() == 0


def test_sold_price_never_below_recorded_base(db):
    bad = db.execute(text("""SELECT player_name, season FROM auction_lots WHERE status='SOLD' AND base_price_lakh IS NOT NULL
                             AND final_price_lakh < base_price_lakh AND verification <> 'conflict'""")).all()
    assert bad == []


def test_sourced_purse_matches_purse_minus_retentions_where_retention_list_is_complete(db):
    from app.auction import sources as src
    from app.auction.identity import PROJECT_ROOT
    purse = {r["franchise"]: r["purse_remaining_lakh"] for r in src.load_all_normalized(PROJECT_ROOT)["purse"] if r["season"] == 2024}
    spend = dict(db.execute(text("""SELECT franchise, SUM(final_price_lakh) FROM auction_lots
                                    WHERE season=2024 AND status='RETAINED' GROUP BY 1""")).all())
    matches = sum(1 for fr, p in purse.items() if abs(10000 - float(spend.get(fr, 0)) - p) < 1)
    assert matches >= 7  # 3 franchises made trades after the listed retentions


def test_features_use_only_matches_before_the_auction(db):
    from app.auction.features import compute_features
    pid = db.execute(text("""SELECT b.player_id FROM scouting_bat_innings b JOIN tournaments t ON t.id=b.tournament_id
                             WHERE t.name='Indian Premier League' GROUP BY 1 ORDER BY MAX(b.start_date) DESC, COUNT(*) DESC LIMIT 1""")).scalar()
    as_of = date(2022, 2, 12)
    f = compute_features(db, [pid], as_of)[pid]
    expected = db.execute(text("""SELECT COUNT(DISTINCT match_id) FROM (
        SELECT match_id, start_date, tournament_id FROM scouting_bat_innings WHERE player_id=:p
        UNION SELECT match_id, start_date, tournament_id FROM scouting_bowl_innings WHERE player_id=:p) x
        JOIN tournaments t ON t.id=x.tournament_id WHERE t.name='Indian Premier League' AND x.start_date < :d"""),
        {"p": pid, "d": as_of}).scalar()
    assert f["ipl_matches_career"] == expected
    assert f["days_since_t20"] is None or f["days_since_t20"] > 0
    later = compute_features(db, [pid], date(2026, 6, 1))[pid]
    assert later["ipl_matches_career"] >= f["ipl_matches_career"]


def test_simulation_respects_purse_squad_and_overseas_limits(db):
    from app.auction import market as mk
    from app.auction.simulator import AuctionRoom
    ctx = mk.build_context(db, "season:2026")
    room = AuctionRoom(db, ctx, AuctionRoom.new_state(db, ctx, "KKR", "balanced", seed=7))
    while room.state["status"] != "COMPLETE":
        if not room.state["lot"] or room.state["lot"]["status"] != "BIDDING":
            room.call_next()
            if room.state["status"] == "COMPLETE":
                break
        room.run_lot(user_autopilot=True)
    for code, f in room.state["franchises"].items():
        assert f["purse_lakh"] >= -1e-6, code
        assert len(f["squad"]) <= ctx.rules.max_squad, code
        assert sum(1 for x in f["squad"] if x.get("overseas")) <= ctx.rules.max_overseas_squad, code
    for r in room.state["results"]:
        if r["status"] == "SOLD":
            assert r["price_lakh"] >= (next(p for p in room.val["players"] if (p.get("player_id") or "name:" + p["name"]) == r["player_key"]).get("base_lakh") or 0)


def test_replay_models_are_trained_only_on_earlier_seasons(db):
    from app.auction import market as mk
    ctx = mk.build_context(db, "season:2024")
    models = mk.models_for(db, ctx)
    assert models["train_seasons"] and max(models["train_seasons"]) < 2024


# ---------------------------------------------------------------- integration with the original module

def test_auction_room_writes_ordinary_session_records(db):
    from fastapi.testclient import TestClient
    from app.main import app
    c = TestClient(app)
    room = c.post("/api/v1/auction/rooms", json={"context": "season:2026", "user_franchise": "KKR", "seed": 3}).json()
    sid = room["id"]
    c.post(f"/api/v1/auction/rooms/{sid}/action", json={"action": "call"})
    c.post(f"/api/v1/auction/rooms/{sid}/action", json={"action": "bid"})
    r = c.post(f"/api/v1/auction/rooms/{sid}/action", json={"action": "auto", "lots": 3}).json()
    events = c.get(f"/api/v1/auction/sessions/{sid}/events").json()
    kinds = {e["event_type"] for e in events}
    assert {"PLAYER_CALLED", "BID_PLACED"} <= kinds and kinds & {"PLAYER_SOLD", "PLAYER_UNSOLD"}
    called = sum(1 for e in events if e["event_type"] == "PLAYER_CALLED")
    closed = sum(1 for e in events if e["event_type"] in ("PLAYER_SOLD", "PLAYER_UNSOLD"))
    assert called == r["cursor"] and closed == r["results_count"]
    sold_value = sum(float(e["bid_amount"]) for e in events if e["event_type"] == "PLAYER_SOLD")
    assert sold_value * 100 == pytest.approx(sum(x["price_lakh"] for x in r["results"] if x["status"] == "SOLD"), abs=0.5)
    # Manual session endpoints refuse to drive an AI room.
    assert c.post(f"/api/v1/auction/sessions/{sid}/call-next").status_code == 409


def test_simulated_purchases_do_not_change_real_squads(db):
    from fastapi.testclient import TestClient
    from app.main import app
    c = TestClient(app)
    ctx = next((x["key"] for x in c.get("/api/v1/auction/contexts").json()["contexts"]
                if x["key"].startswith("scenario:") and x.get("simulatable")), None)
    if ctx is None:
        pytest.skip("no simulatable user scenario")
    sc_id = ctx.split(":", 1)[1]
    before = c.get(f"/api/v1/auction/scenarios/{sc_id}/teams").json()
    sid = c.post("/api/v1/auction/rooms", json={"context": ctx, "seed": 5}).json()["id"]
    c.post(f"/api/v1/auction/rooms/{sid}/action", json={"action": "auto", "lots": 5})
    after = c.get(f"/api/v1/auction/scenarios/{sc_id}/teams").json()
    assert [(t["team_id"], t["squad_count"], t["remaining_purse"]) for t in before] == \
           [(t["team_id"], t["squad_count"], t["remaining_purse"]) for t in after]


def test_run_scenario_keeps_original_shape_with_data_derived_targets(db):
    from app.models.models import AuctionScenario, AuctionRetention, AuctionPlayer
    from sqlalchemy import select as sel, func
    sc = next((s for s in db.scalars(sel(AuctionScenario).where(AuctionScenario.status != "REPLAY")).all()
               if db.scalar(sel(func.count()).select_from(AuctionRetention).where(AuctionRetention.scenario_id == s.id))
               and db.scalar(sel(func.count()).select_from(AuctionPlayer).where(AuctionPlayer.scenario_id == s.id))), None)
    if sc is None:
        pytest.skip("no scenario with retentions and pool")
    from app.analytics.auction_scenario import run_scenario
    r = run_scenario(db, sc)
    assert r["ready"], r.get("message")
    team = r["teams"][0]
    for key in ("team_id", "franchise", "needs", "remaining_purse_cr", "squad_slots_remaining", "recommendations"):
        assert key in team
    assert "fallback" not in r["assumptions"]["role_target_basis"]
    for p in r["player_predictions"][:20]:
        assert p["confidence_interval_cr"]["low"] <= p["predicted_final_price_cr"] <= p["confidence_interval_cr"]["high"] + 1e-9
        if p["model_range_cr"]["p90"] is not None:
            assert p["predicted_final_price_cr"] <= p["model_range_cr"]["p90"] + 0.01
