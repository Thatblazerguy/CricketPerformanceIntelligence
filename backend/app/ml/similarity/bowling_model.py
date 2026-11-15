"""Dedicated, explainable bowler-to-bowler similarity model."""
from typing import Dict, List, Optional
import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.neighbors import NearestNeighbors
from sklearn.preprocessing import StandardScaler

from app.ml.features.bowling_features import BOWLING_FEATURE_COLUMNS


class BowlingSimilarityEngine:
    version = "bowling-similarity-knn-v1.0"

    def __init__(self):
        self.imputer = SimpleImputer(strategy="median", add_indicator=False, keep_empty_features=True)
        self.scaler = StandardScaler()
        self.model = NearestNeighbors(metric="cosine", algorithm="brute")
        self.feature_df: Optional[pd.DataFrame] = None
        self.scaled: Optional[np.ndarray] = None

    def fit(self, df: pd.DataFrame) -> bool:
        if df.empty or len(df) < 2:
            return False
        self.feature_df = df
        x = df[BOWLING_FEATURE_COLUMNS].astype(float)
        x = x.mask(~np.isfinite(x))
        x = self.imputer.fit_transform(x)
        self.scaled = self.scaler.fit_transform(x)
        self.model.fit(self.scaled)
        return True

    def find_similar_players(self, player_id: str, n_neighbors: int = 5) -> List[Dict]:
        if self.feature_df is None or player_id not in self.feature_df.index:
            return []
        idx = self.feature_df.index.get_loc(player_id)
        distances, indices = self.model.kneighbors(self.scaled[idx:idx + 1], n_neighbors=min(n_neighbors + 1, len(self.feature_df)))
        results = []
        for distance, other_idx in zip(distances[0], indices[0]):
            other_id = self.feature_df.index[other_idx]
            if other_id == player_id:
                continue
            target = self.feature_df.iloc[idx]
            candidate = self.feature_df.iloc[other_idx]
            diffs = np.abs(self.scaled[idx] - self.scaled[other_idx])
            closest = np.argsort(diffs)[:4]
            matches, differences = [], []
            for fi in closest:
                feature = BOWLING_FEATURE_COLUMNS[fi]
                left, right = target[feature], candidate[feature]
                label = feature.replace("_", " ")
                if pd.isna(left) or pd.isna(right):
                    continue
                unit = "%" if feature.endswith("pct") else (" econ" if "economy" in feature else "")
                matches.append(f"Similar {label}: {left:g} vs {right:g}{unit}")
            for feature in ("economy", "bowling_average", "bowling_strike_rate", "death_economy", "powerplay_economy"):
                left, right = target[feature], candidate[feature]
                if pd.notna(left) and pd.notna(right) and abs(left-right) > max(abs(left), abs(right), 1) * .35:
                    differences.append(f"Different {feature.replace('_', ' ')}: {left:g} vs {right:g}")
            results.append({
                "player_id": other_id, "player_name": candidate["player_name"],
                "similarity_score": round(max(0, min(100, (1 - float(distance)) * 100)), 1),
                "innings": int(candidate["innings"]), "matches": int(candidate["matches"]),
                "wickets": int(candidate["wickets"]), "economy": candidate["economy"],
                "bowling_average": candidate["bowling_average"],
                "bowling_strike_rate": candidate["bowling_strike_rate"],
                "dot_ball_pct": candidate["dot_ball_pct"],
                "explanations": matches, "differences": differences,
            })
            if len(results) >= n_neighbors:
                break
        return results
