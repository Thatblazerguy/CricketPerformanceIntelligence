import pandas as pd

from app.ml.features.player_features import FEATURE_COLUMNS
from app.ml.features.bowling_features import BOWLING_FEATURE_COLUMNS
from app.ml.similarity.allrounder_model import AllRounderSimilarityEngine


def test_all_rounder_similarity_combines_independent_disciplines_equally():
    bat = pd.DataFrame(index=["a", "b", "c"])
    bat["player_name"] = ["A", "B", "C"]
    bat["innings"] = [40, 39, 38]
    for i, feature in enumerate(FEATURE_COLUMNS):
        bat[feature] = [10.0 + i, 10.1 + i, 40.0 + i]
    bowl = pd.DataFrame(index=["a", "b", "c"])
    bowl["player_name"] = ["A", "B", "C"]
    bowl["innings"] = [35, 34, 33]
    for i, feature in enumerate(BOWLING_FEATURE_COLUMNS):
        bowl[feature] = [20.0 + i, 20.2 + i, 50.0 + i]
    engine = AllRounderSimilarityEngine()
    assert engine.fit(bat, bowl)
    result = engine.find_similar_players("a", 2)
    assert result[0]["player_id"] == "b"
    assert result[0]["batting_similarity"] > result[1]["batting_similarity"]
    assert result[0]["bowling_similarity"] > result[1]["bowling_similarity"]
    assert result[0]["similarity_score"] == round((result[0]["batting_similarity"] + result[0]["bowling_similarity"]) / 2, 1)


def test_all_rounder_engine_requires_both_roles():
    bat = pd.DataFrame([{**{f: 1.0 for f in FEATURE_COLUMNS}, "player_name": "A", "innings": 10}], index=["a"])
    bowl = pd.DataFrame([{**{f: 1.0 for f in BOWLING_FEATURE_COLUMNS}, "player_name": "A", "innings": 10}], index=["a"])
    assert not AllRounderSimilarityEngine().fit(bat, bowl)
