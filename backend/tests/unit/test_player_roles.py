from app.analytics.player_roles import classify_player_role


def test_role_classification_requires_repeated_usage_in_each_discipline():
    assert classify_player_role(0, 0, 36, 6)[0] == "Unclassified"
    assert classify_player_role(420, 32, 24, 4)[0] == "Specialist Batter"
    assert classify_player_role(100, 15, 240, 20)[0] == "Specialist Bowler"
    role = classify_player_role(420, 32, 240, 20)
    assert role == ("Batting All-Rounder", "delivery usage", "medium")


def test_explicit_wicketkeeper_metadata_takes_precedence():
    role = classify_player_role(400, 30, 0, 0, "wicketkeeper_batter")
    assert role == ("Wicketkeeper-Batter", "verified player metadata", "high")
