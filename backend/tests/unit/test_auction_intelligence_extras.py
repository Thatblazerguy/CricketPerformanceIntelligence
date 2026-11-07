import pytest
import asyncio
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from app.auction_intelligence import parse_rules_text, validate_composition, build_predicted_xi
from app.models.models import Base, Player, PlayerAlias, PlayerAttribute, PlayerExternalProfile, Provider
from app.services import cricket_database

def test_parse_uploaded_ipl_rules():
    assert parse_rules_text("Maximum squad size: 25. Maximum overseas players in squad: 8. Maximum overseas players in Playing XI: 4.") == {
        "maximum_squad_size": 25, "overseas_squad_limit": 8, "overseas_xi_limit": 4}

def test_composition_rejects_overseas_limits():
    players = [{"overseas": i < 5} for i in range(11)]
    with pytest.raises(ValueError, match="Playing XI"):
        validate_composition(players, {"maximum_squad_size": 25, "overseas_squad_limit": 8, "overseas_xi_limit": 4})

def test_xi_uses_only_given_squad_and_includes_keeper():
    players = [{"player_id": str(i), "name": str(i), "bat_score": .4, "bowl_score": .3,
                "overseas": i < 5, "wicketkeeper": i == 10, "data_complete": True} for i in range(15)]
    result = build_predicted_xi(players, {"maximum_squad_size": 25, "overseas_squad_limit": 8, "overseas_xi_limit": 4})
    assert len(result["players"]) == 11
    assert "10" in {p["player_id"] for p in result["players"]}
    assert sum(p["player_id"] in {"0", "1", "2", "3", "4"} for p in result["players"]) <= 4
    assert set(p["player_id"] for p in result["players"]).issubset({p["player_id"] for p in players})

def test_xi_rejects_less_than_eleven():
    with pytest.raises(ValueError, match="Fewer than 11"):
        build_predicted_xi([{"player_id": "1", "name": "One"}], {"maximum_squad_size": 25, "overseas_squad_limit": 8, "overseas_xi_limit": 4})

def test_missing_metrics_are_not_fabricated_or_crashing():
    pool = [{"player_id": str(i), "name": f"Player {i}", "bat_score": None, "bowl_score": None,
             "data_complete": False, "confidence": "low"} for i in range(11)]
    result = build_predicted_xi(pool, {"maximum_squad_size": 25, "overseas_squad_limit": 8, "overseas_xi_limit": 4})
    assert result["confidence"] == "low"
    assert result["players"][0]["confidence"] == "low"

def test_unknown_player_fallback_is_cached_and_keeps_minimal_status(monkeypatch):
    monkeypatch.setattr(cricket_database.settings, "CRICKET_DATABASE_API_KEY", None)
    engine = create_engine("sqlite://")
    for table in (Provider.__table__, Player.__table__, PlayerAlias.__table__, PlayerAttribute.__table__, PlayerExternalProfile.__table__):
        table.create(engine)
    with Session(engine) as db:
        first, source, status = asyncio.run(cricket_database.enrich_player(db, "New Player", {"primary_role": "Bowler"}))
        db.commit()
        second, source2, status2 = asyncio.run(cricket_database.enrich_player(db, "New Player"))
        assert first.id == second.id
        assert (source, status) == ("auction_upload", "minimal")
        assert status2 == "minimal"
        assert db.scalar(select(PlayerAttribute.attribute_value).where(PlayerAttribute.player_id == first.id,
            PlayerAttribute.attribute_type == "primary_role")) == "Bowler"
        assert len(db.scalars(select(Player)).all()) == 1
