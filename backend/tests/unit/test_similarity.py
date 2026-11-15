"""
Unit test for Player Similarity Engine (ML Cosine Model).
"""
import pytest
import pandas as pd
from app.ml.similarity.model import PlayerSimilarityEngine
from app.ml.features.player_features import FEATURE_COLUMNS


def test_similarity_engine_fit_and_query():
    # Synthetic data resembling real cricket aggregates
    data = [
        {
            "player_id": "p1",
            "player_name": "Anchor Batter",
            "innings": 50,
            "batting_average": 45.0,
            "strike_rate": 128.0,
            "boundary_pct": 14.0,
            "dot_ball_pct": 36.0,
            "powerplay_sr": 120.0,
            "middle_over_sr": 125.0,
            "death_over_sr": 155.0,
        },
        {
            "player_id": "p2",
            "player_name": "Similar Anchor",
            "innings": 45,
            "batting_average": 42.0,
            "strike_rate": 130.0,
            "boundary_pct": 15.0,
            "dot_ball_pct": 35.0,
            "powerplay_sr": 122.0,
            "middle_over_sr": 128.0,
            "death_over_sr": 150.0,
        },
        {
            "player_id": "p3",
            "player_name": "Aggressive Finisher",
            "innings": 40,
            "batting_average": 28.0,
            "strike_rate": 168.0,
            "boundary_pct": 24.0,
            "dot_ball_pct": 42.0,
            "powerplay_sr": 110.0,
            "middle_over_sr": 145.0,
            "death_over_sr": 210.0,
        },
    ]

    df = pd.DataFrame(data).set_index("player_id")
    engine = PlayerSimilarityEngine()
    success = engine.fit(df)
    assert success is True

    # Find similar to p1
    results = engine.find_similar_players("p1", n_neighbors=2)
    assert len(results) == 2
    # p2 should be closer to p1 than p3
    assert results[0]["player_id"] == "p2"
    assert results[0]["similarity_score"] > results[1]["similarity_score"]
    assert len(results[0]["explanations"]) > 0


def test_similarity_engine_handles_undefined_metrics_as_missing():
    data = [
        {"player_id": "p1", "player_name": "A", "innings": 10, "batting_average": None,
         "strike_rate": 90, "boundary_pct": 10, "dot_ball_pct": 40,
         "powerplay_sr": None, "middle_over_sr": 90, "death_over_sr": 90},
        {"player_id": "p2", "player_name": "B", "innings": 11, "batting_average": 25,
         "strike_rate": 91, "boundary_pct": 11, "dot_ball_pct": 39,
         "powerplay_sr": 91, "middle_over_sr": 91, "death_over_sr": None},
    ]
    engine = PlayerSimilarityEngine()
    assert engine.fit(pd.DataFrame(data).set_index("player_id"))
    assert engine.find_similar_players("p1", 1)[0]["player_id"] == "p2"
