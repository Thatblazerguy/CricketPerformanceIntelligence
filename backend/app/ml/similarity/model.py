"""
Player Similarity Engine
Uses Scikit-learn StandardScaler and NearestNeighbors (cosine metric).
Provides explainable similarity scores and comparison metrics.
"""
from typing import Dict, List, Optional
import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler
from sklearn.neighbors import NearestNeighbors
from sklearn.impute import SimpleImputer

from app.ml.features.player_features import FEATURE_COLUMNS, extract_player_feature_matrix


class PlayerSimilarityEngine:
    def __init__(self):
        self.scaler = StandardScaler()
        self.imputer = SimpleImputer(strategy="median", keep_empty_features=True)
        self.model = NearestNeighbors(metric="cosine", algorithm="brute")
        self.feature_df: Optional[pd.DataFrame] = None
        self.scaled_features: Optional[np.ndarray] = None
        self.version = "similarity-knn-v1.0"

    def fit(self, df: pd.DataFrame):
        """Fit scaler and nearest neighbor index on feature dataframe."""
        if df.empty or len(df) < 2:
            return False

        self.feature_df = df
        X = self.imputer.fit_transform(df[FEATURE_COLUMNS])
        self.scaled_features = self.scaler.fit_transform(X)
        self.model.fit(self.scaled_features)
        return True

    def find_similar_players(
        self,
        player_id: str,
        n_neighbors: int = 5,
    ) -> List[Dict]:
        """
        Find top N most similar players to the target player.
        Returns list with player_id, similarity_score (0-100), key matches and differences.
        """
        if self.feature_df is None or player_id not in self.feature_df.index:
            return []

        idx = self.feature_df.index.get_loc(player_id)
        target_vec = self.scaled_features[idx].reshape(1, -1)
        target_raw = self.feature_df.loc[player_id]

        # Query n_neighbors + 1 to account for self match
        k = min(n_neighbors + 1, len(self.feature_df))
        distances, indices = self.model.kneighbors(target_vec, n_neighbors=k)

        results = []
        for dist, neighbor_idx in zip(distances[0], indices[0]):
            cand_id = self.feature_df.index[neighbor_idx]
            if cand_id == player_id:
                continue

            cand_raw = self.feature_df.iloc[neighbor_idx]
            
            # Cosine distance to similarity percentage: 1 - distance
            # Cosine similarity in [-1, 1], for normalised non-negative vector space typically [0, 1]
            similarity_pct = round(max(0.0, min(100.0, (1.0 - dist) * 100)), 1)

            # Feature-level explanation
            explanations = []
            cand_vec = self.scaled_features[neighbor_idx]
            feature_diffs = np.abs(target_vec[0] - cand_vec)
            
            # Sort features with smallest normalized difference
            closest_feat_idx = np.argsort(feature_diffs)[:3]
            for fi in closest_feat_idx:
                f_name = FEATURE_COLUMNS[fi]
                t_val = target_raw[f_name]
                c_val = cand_raw[f_name]
                if pd.isna(t_val) or pd.isna(c_val):
                    continue
                readable = f_name.replace("_", " ").title()
                explanations.append(f"Similar {readable} ({t_val} vs {c_val})")

            results.append({
                "player_id": cand_id,
                "player_name": cand_raw["player_name"],
                "similarity_score": similarity_pct,
                "innings": int(cand_raw["innings"]),
                "strike_rate": float(cand_raw["strike_rate"]) if pd.notna(cand_raw["strike_rate"]) else None,
                "batting_average": float(cand_raw["batting_average"]) if pd.notna(cand_raw["batting_average"]) else None,
                "boundary_pct": float(cand_raw["boundary_pct"]) if pd.notna(cand_raw["boundary_pct"]) else None,
                "dot_ball_pct": float(cand_raw["dot_ball_pct"]) if pd.notna(cand_raw["dot_ball_pct"]) else None,
                "explanations": explanations,
            })

            if len(results) >= n_neighbors:
                break

        return results
