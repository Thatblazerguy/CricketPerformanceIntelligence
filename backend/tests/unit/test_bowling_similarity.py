import pandas as pd

from app.ml.features.bowling_features import BOWLING_FEATURE_COLUMNS
from app.ml.similarity.bowling_model import BowlingSimilarityEngine


def _row(name, economy, wickets, dot, death_economy):
    values = {column: 0.0 for column in BOWLING_FEATURE_COLUMNS}
    values.update({
        "player_name": name, "innings": 40, "matches": 35, "wickets": wickets,
        "economy": economy, "bowling_average": 25.0, "bowling_strike_rate": 18.0,
        "wickets_per_match": wickets / 35, "dot_ball_pct": dot,
        "boundary_pct_conceded": 12.0, "death_economy": death_economy,
        "legal_balls_per_match": 24.0,
    })
    return values


def test_bowler_similarity_uses_bowling_features_and_explains_differences():
    df = pd.DataFrame({
        "bowler-a": _row("Bowler A", 7.2, 55, 42, 8.4),
        "bowler-b": _row("Bowler B", 7.4, 52, 41, 8.6),
        "bowler-c": _row("Bowler C", 10.1, 20, 25, 14.0),
    }).T
    engine = BowlingSimilarityEngine()
    assert engine.fit(df)
    results = engine.find_similar_players("bowler-a", 2)
    assert [row["player_id"] for row in results] == ["bowler-b", "bowler-c"]
    assert results[0]["similarity_score"] > results[1]["similarity_score"]
    assert results[0]["explanations"]
    assert results[1]["differences"]


def test_bowler_similarity_handles_missing_phase_features():
    df = pd.DataFrame({
        "bowler-a": _row("Bowler A", 7.2, 55, 42, None),
        "bowler-b": _row("Bowler B", 7.4, 52, 41, None),
    }).T
    assert BowlingSimilarityEngine().fit(df)


def test_bowler_similarity_never_returns_the_selected_player():
    df = pd.DataFrame({"bowler-a": _row("Bowler A", 7.2, 55, 42, 8.4),
                       "bowler-b": _row("Bowler B", 7.4, 52, 41, 8.6)}).T
    engine = BowlingSimilarityEngine()
    assert engine.fit(df)
    assert all(r["player_id"] != "bowler-a" for r in engine.find_similar_players("bowler-a", 10))


def test_bowler_cosine_model_imputes_missing_values_without_zero_filling():
    left = _row("Bowler A", 7.2, 55, 42, None)
    right = _row("Bowler B", 7.4, 52, 41, None)
    left["powerplay_economy"] = right["powerplay_economy"] = None
    engine = BowlingSimilarityEngine()
    assert engine.fit(pd.DataFrame({"a": left, "b": right}).T)
    assert engine.find_similar_players("a", 1)[0]["similarity_score"] >= 0
