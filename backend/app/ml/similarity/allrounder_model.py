"""Balanced all-rounder similarity using independent batting and bowling spaces."""
from typing import Dict, List, Optional
import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.preprocessing import StandardScaler

from app.ml.features.player_features import FEATURE_COLUMNS
from app.ml.features.bowling_features import BOWLING_FEATURE_COLUMNS


class AllRounderSimilarityEngine:
    version = "allrounder-two-discipline-cosine-v1.0"

    def __init__(self):
        self.bat_imputer = SimpleImputer(strategy="median", keep_empty_features=True)
        self.bowl_imputer = SimpleImputer(strategy="median", keep_empty_features=True)
        self.bat_scaler = StandardScaler()
        self.bowl_scaler = StandardScaler()
        self.batting: Optional[pd.DataFrame] = None
        self.bowling: Optional[pd.DataFrame] = None
        self.bat_vectors: Optional[np.ndarray] = None
        self.bowl_vectors: Optional[np.ndarray] = None

    def fit(self, batting: pd.DataFrame, bowling: pd.DataFrame) -> bool:
        common = batting.index.intersection(bowling.index)
        if len(common) < 2:
            return False
        self.batting, self.bowling = batting.loc[common], bowling.loc[common]
        bx = self.batting[FEATURE_COLUMNS].astype(float).mask(~np.isfinite(self.batting[FEATURE_COLUMNS].astype(float)))
        wx = self.bowling[BOWLING_FEATURE_COLUMNS].astype(float).mask(~np.isfinite(self.bowling[BOWLING_FEATURE_COLUMNS].astype(float)))
        self.bat_vectors = self.bat_scaler.fit_transform(self.bat_imputer.fit_transform(bx))
        self.bowl_vectors = self.bowl_scaler.fit_transform(self.bowl_imputer.fit_transform(wx))
        return True

    def find_similar_players(self, player_id: str, n_neighbors: int = 5) -> List[Dict]:
        if self.batting is None or player_id not in self.batting.index:
            return []
        index = self.batting.index.get_loc(player_id)
        bat_scores = cosine_similarity(self.bat_vectors[index:index + 1], self.bat_vectors)[0]
        bowl_scores = cosine_similarity(self.bowl_vectors[index:index + 1], self.bowl_vectors)[0]
        combined = (np.clip(bat_scores, -1, 1) + np.clip(bowl_scores, -1, 1)) / 2
        order = np.argsort(-combined)
        results = []
        for other in order:
            if other == index:
                continue
            bid, wid = self.batting.index[other], self.bowling.index[other]
            btarget, bcandidate = self.batting.iloc[index], self.batting.iloc[other]
            wtarget, wcandidate = self.bowling.iloc[index], self.bowling.iloc[other]
            bat_gaps = np.abs(self.bat_vectors[index] - self.bat_vectors[other])
            bowl_gaps = np.abs(self.bowl_vectors[index] - self.bowl_vectors[other])
            def explain(columns, gaps, left, right):
                out = []
                for col_idx in np.argsort(gaps)[:3]:
                    field = columns[col_idx]
                    lv, rv = left[field], right[field]
                    if pd.notna(lv) and pd.notna(rv):
                        out.append(f"{field.replace('_', ' ')}: {lv:g} vs {rv:g}")
                return out
            results.append({
                "player_id": bid, "player_name": bcandidate["player_name"],
                "similarity_score": round(float(np.clip(combined[other], 0, 1) * 100), 1),
                "batting_similarity": round(float(np.clip(bat_scores[other], 0, 1) * 100), 1),
                "bowling_similarity": round(float(np.clip(bowl_scores[other], 0, 1) * 100), 1),
                "batting_innings": int(bcandidate["innings"]), "bowling_innings": int(wcandidate["innings"]),
                "batting_explanations": explain(FEATURE_COLUMNS, bat_gaps, btarget, bcandidate),
                "bowling_explanations": explain(BOWLING_FEATURE_COLUMNS, bowl_gaps, wtarget, wcandidate),
                "weighting": {"batting": 0.5, "bowling": 0.5},
            })
            if len(results) >= n_neighbors:
                break
        return results
