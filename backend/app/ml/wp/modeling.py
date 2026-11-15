"""Model factories, post-hoc calibrators and probability metrics."""
from __future__ import annotations

from typing import Dict, List, Optional, Sequence

import numpy as np

EPS = 1e-6


# --------------------------------------------------------------------------------------
# Models
# --------------------------------------------------------------------------------------

def logistic(C: float, multiclass: bool = False):
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    return Pipeline([
        ("impute", SimpleImputer(strategy="median", add_indicator=True)),
        ("scale", StandardScaler()),
        ("lr", LogisticRegression(C=C, max_iter=2000, random_state=29)),
    ])


def gradient_boosting(feature_names: Sequence[str], *, max_iter=300, learning_rate=0.05, max_depth=4,
                      l2_regularization=1.0, min_samples_leaf=200, monotone: Optional[Dict[str, int]] = None):
    from sklearn.ensemble import HistGradientBoostingClassifier

    cst = [int((monotone or {}).get(name, 0)) for name in feature_names] if monotone else None
    return HistGradientBoostingClassifier(
        max_depth=max_depth, learning_rate=learning_rate, max_iter=max_iter, l2_regularization=l2_regularization,
        min_samples_leaf=min_samples_leaf, early_stopping=False, monotonic_cst=cst, random_state=29)


def fit(model, x, y, w):
    if hasattr(model, "steps"):
        model.fit(x, y, lr__sample_weight=w)
    else:
        model.fit(x, y, sample_weight=w)
    return model


def predict(model, x, n_classes: int = 2) -> np.ndarray:
    """Binary: P(class 1). Multiclass: (n, n_classes) in fixed class order."""
    raw = model.predict_proba(x)
    classes = list(model.classes_)
    if n_classes == 2:
        return raw[:, classes.index(1)] if 1 in classes else np.zeros(len(x))
    out = np.zeros((len(x), n_classes))
    for i, c in enumerate(classes):
        out[:, int(c)] = raw[:, i]
    return out / out.sum(axis=1, keepdims=True)


# --------------------------------------------------------------------------------------
# Calibration
# --------------------------------------------------------------------------------------

class Calibrator:
    """Post-hoc calibration fitted on a separate chronological partition.

    ``none``      identity
    ``sigmoid``   Platt scaling on the logit (binary) / multinomial LR on log-probs (multi)
    ``isotonic``  isotonic regression (binary) / one-vs-rest isotonic + renormalise (multi)
    """

    def __init__(self, method: str = "none"):
        self.method = method
        self.model = None

    def fit(self, p, y, w=None):
        from sklearn.isotonic import IsotonicRegression
        from sklearn.linear_model import LogisticRegression

        p = np.asarray(p, float)
        y = np.asarray(y, int)
        if self.method == "none":
            return self
        if p.ndim == 1:
            if self.method == "sigmoid":
                self.model = LogisticRegression(C=1e6, max_iter=1000).fit(_logit(p)[:, None], y, sample_weight=w)
            else:
                self.model = IsotonicRegression(y_min=0, y_max=1, out_of_bounds="clip").fit(p, y, sample_weight=w)
        else:
            k = p.shape[1]
            if self.method == "sigmoid":
                self.model = LogisticRegression(C=1e6, max_iter=2000).fit(np.log(np.clip(p, EPS, 1)), y, sample_weight=w)
            else:
                self.model = [IsotonicRegression(y_min=0, y_max=1, out_of_bounds="clip").fit(p[:, j], (y == j).astype(float), sample_weight=w)
                              for j in range(k)]
        return self

    def transform(self, p):
        p = np.asarray(p, float)
        if self.method == "none" or self.model is None:
            return p
        if p.ndim == 1:
            if self.method == "sigmoid":
                out = self.model.predict_proba(_logit(p)[:, None])[:, 1]
            else:
                out = self.model.predict(p)
            return np.clip(out, EPS, 1 - EPS)
        if self.method == "sigmoid":
            raw = self.model.predict_proba(np.log(np.clip(p, EPS, 1)))
            out = np.zeros_like(p)
            for i, c in enumerate(self.model.classes_):
                out[:, int(c)] = raw[:, i]
        else:
            out = np.column_stack([m.predict(p[:, j]) for j, m in enumerate(self.model)])
        out = np.clip(out, EPS, None)
        return out / out.sum(axis=1, keepdims=True)


def _logit(p):
    p = np.clip(p, EPS, 1 - EPS)
    return np.log(p / (1 - p))


def choose_calibrator(p, y, w, groups, methods=("none", "sigmoid", "isotonic"), folds: int = 4, n_classes: int = 2):
    """Pick a calibration method by match-grouped CV *within* the calibration partition."""
    groups = np.asarray(groups)
    unique = np.unique(groups)
    rng = np.random.default_rng(29)
    fold_of = dict(zip(unique, rng.integers(0, folds, len(unique))))
    fold = np.array([fold_of[g] for g in groups])
    scores = {}
    for method in methods:
        losses, weights = [], []
        for k in range(folds):
            tr, te = fold != k, fold == k
            if te.sum() == 0 or len(np.unique(np.asarray(y)[tr])) < n_classes:
                continue
            cal = Calibrator(method).fit(p[tr], y[tr], w[tr])
            losses.append(log_loss(y[te], cal.transform(p[te]), w[te]) * w[te].sum())
            weights.append(w[te].sum())
        scores[method] = float(np.sum(losses) / np.sum(weights)) if weights else float("inf")
    best = min(scores, key=scores.get)
    return Calibrator(best).fit(p, y, w), scores


# --------------------------------------------------------------------------------------
# Metrics
# --------------------------------------------------------------------------------------

def _as_matrix(p, n_classes):
    p = np.asarray(p, float)
    if p.ndim == 1:
        return np.column_stack([1 - p, p])
    return p


def log_loss(y, p, w=None) -> float:
    y = np.asarray(y, int)
    m = _as_matrix(p, None)
    picked = np.clip(m[np.arange(len(y)), y], EPS, 1)
    return float(np.average(-np.log(picked), weights=w))


def brier(y, p, w=None) -> float:
    y = np.asarray(y, int)
    m = _as_matrix(p, None)
    onehot = np.eye(m.shape[1])[y]
    per = np.sum((m - onehot) ** 2, axis=1)
    if m.shape[1] == 2:
        per = per / 2.0  # conventional binary Brier: (p - y)^2
    return float(np.average(per, weights=w))


def rps(y, p, order: Sequence[int], w=None) -> float:
    """Ranked probability score over an ordinal class order (lower is better)."""
    y = np.asarray(y, int)
    m = np.asarray(p, float)[:, list(order)]
    obs = np.eye(m.shape[1])[[list(order).index(v) for v in y]]
    cp, co = np.cumsum(m, axis=1)[:, :-1], np.cumsum(obs, axis=1)[:, :-1]
    per = np.sum((cp - co) ** 2, axis=1) / (m.shape[1] - 1)
    return float(np.average(per, weights=w))


def calibration_bins(y_event, p_event, w=None, bins: int = 10) -> List[dict]:
    y_event = np.asarray(y_event, float)
    p_event = np.asarray(p_event, float)
    w = np.ones_like(p_event) if w is None else np.asarray(w, float)
    edges = np.linspace(0, 1, bins + 1)
    idx = np.clip(np.digitize(p_event, edges[1:-1]), 0, bins - 1)
    out = []
    for b in range(bins):
        m = idx == b
        if not m.any():
            continue
        out.append({"bin_low": float(edges[b]), "bin_high": float(edges[b + 1]),
                    "mean_predicted": float(np.average(p_event[m], weights=w[m])),
                    "observed": float(np.average(y_event[m], weights=w[m])),
                    "weight": float(w[m].sum()), "states": int(m.sum())})
    return out


def ece(y_event, p_event, w=None, bins: int = 10) -> float:
    rows = calibration_bins(y_event, p_event, w, bins)
    total = sum(r["weight"] for r in rows)
    return float(sum(r["weight"] * abs(r["mean_predicted"] - r["observed"]) for r in rows) / total) if total else float("nan")


def binary_metrics(y, p, w) -> dict:
    return {"log_loss": log_loss(y, p, w), "brier": brier(y, p, w), "ece": ece(y, p, w),
            "states": int(len(y)), "matches_weight": float(np.sum(w))}


def multiclass_metrics(y, p, w, labels: Sequence[str]) -> dict:
    out = {"log_loss": log_loss(y, p, w), "brier": brier(y, p, w), "states": int(len(y)),
           "rps": rps(y, p, order=(0, 2, 1), w=w),  # batting win > draw > bowling win
           "ece_by_class": {name: ece(np.asarray(y) == j, np.asarray(p)[:, j], w) for j, name in enumerate(labels)}}
    out["ece"] = float(np.mean(list(out["ece_by_class"].values())))
    return out


def bootstrap_ci(per_match_values: Dict[str, np.ndarray], per_match_weight: np.ndarray, reps: int = 300,
                 seed: int = 29, baselines: Optional[Dict[str, str]] = None) -> dict:
    """Match-level bootstrap of weighted means and skill scores.

    ``per_match_values[name]`` holds each match's weighted *sum* of a per-state loss.
    """
    rng = np.random.default_rng(seed)
    n = len(per_match_weight)
    draws = {name: [] for name in per_match_values}
    for _ in range(reps):
        idx = rng.integers(0, n, n)
        wsum = per_match_weight[idx].sum()
        for name, vals in per_match_values.items():
            draws[name].append(vals[idx].sum() / wsum)
    out = {name: {"low": float(np.percentile(v, 2.5)), "high": float(np.percentile(v, 97.5))} for name, v in draws.items()}
    for skill_name, (model_key, base_key) in (baselines or {}).items():
        skill = 1 - np.asarray(draws[model_key]) / np.asarray(draws[base_key])
        out[skill_name] = {"low": float(np.percentile(skill, 2.5)), "high": float(np.percentile(skill, 97.5))}
    return out
