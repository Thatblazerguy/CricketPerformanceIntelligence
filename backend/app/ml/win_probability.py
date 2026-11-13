"""Format-aware match-state features and probability evaluation helpers."""
from __future__ import annotations

from typing import Any, Dict

FORMAT_FAMILY = {
    "T20": "T20", "T20I": "T20",
    "ODI": "ODI", "ODM": "ODI",
    "Test": "Test", "MDM": "Test",
}
OUTCOMES = ("team1_win", "team2_win", "draw_or_tie")
MODEL_VERSION_PREFIX = "cpi-wp-v1"

FEATURES = {
    "T20": (
        "team1_batting", "female_match", "is_super_over", "innings_number",
        "score", "wickets_lost", "wickets_remaining", "legal_balls",
        "balls_remaining", "innings_run_rate", "batting_team_prior_runs",
        "opposition_prior_runs", "target_runs", "runs_required", "required_run_rate",
        "recent_runs_12_balls", "recent_wickets_12_balls", "is_powerplay", "is_middle", "is_death",
    ),
    "ODI": (
        "team1_batting", "female_match", "is_super_over", "innings_number",
        "score", "wickets_lost", "wickets_remaining", "legal_balls",
        "balls_remaining", "innings_run_rate", "batting_team_prior_runs",
        "opposition_prior_runs", "target_runs", "runs_required", "required_run_rate",
        "recent_runs_12_balls", "recent_wickets_12_balls", "is_powerplay", "is_middle", "is_death",
    ),
    "Test": (
        "team1_batting", "female_match", "is_test_match", "is_super_over", "innings_number",
        "innings_runs", "wickets_lost", "wickets_remaining", "legal_balls",
        "innings_run_rate", "team1_runs", "team2_runs", "lead_from_team1",
        "current_innings_lead", "batting_team_prior_runs", "opposition_prior_runs",
    ),
}


def format_family(match_format: str) -> str | None:
    return FORMAT_FAMILY.get(match_format)


def result_label(result_type: str | None, winner_id: str | None, team1_id: str | None) -> int | None:
    """Class labels are stable: 0 team1, 1 team2, 2 draw/tie; no-result is unlabelled."""
    result = (result_type or "").strip().casefold().replace("_", " ")
    if winner_id and team1_id:
        return 0 if winner_id == team1_id else 1
    if result in {"tie", "tied", "draw", "drawn"}:
        return 2
    return None


def match_state_features(
    family: str,
    *,
    match_format: str,
    gender: str,
    team1_batting: bool,
    is_super_over: bool,
    innings_number: int,
    innings_runs: int,
    wickets_lost: int,
    legal_balls: int,
    batting_team_prior_runs: int,
    opposition_prior_runs: int,
    target_runs: int | None,
    target_overs: int | None,
    recent_runs: int = 0,
    recent_wickets: int = 0,
) -> Dict[str, float | None]:
    """Build a strictly pre-delivery state; absent targets remain missing, never zero."""
    cap = 120 if family == "T20" else 300 if family == "ODI" else None
    if is_super_over and family in {"T20", "ODI"}:
        cap = 6
    elif family in {"T20", "ODI"} and target_overs:
        cap = min(cap, target_overs * 6)
    balls_remaining = max(0, cap - legal_balls) if cap is not None else None
    run_rate = innings_runs * 6 / legal_balls if legal_balls else None
    required = max(0, target_runs - innings_runs) if target_runs is not None else None
    required_rate = required * 6 / balls_remaining if required is not None and balls_remaining else (
        0.0 if required == 0 else None
    )
    powerplay_balls = 36 if family == "T20" else 60
    middle_end = 90 if family == "T20" else 240
    limited = family in {"T20", "ODI"} and not is_super_over
    team1_runs = batting_team_prior_runs + innings_runs if team1_batting else opposition_prior_runs
    team2_runs = opposition_prior_runs if team1_batting else batting_team_prior_runs + innings_runs
    values: Dict[str, float | None] = {
        "team1_batting": float(team1_batting),
        "female_match": float((gender or "").casefold() in {"female", "women", "women's"}),
        "is_test_match": float(match_format == "Test"),
        "is_super_over": float(is_super_over), "innings_number": float(min(10, innings_number)),
        "score": float(innings_runs), "innings_runs": float(innings_runs),
        "wickets_lost": float(min(10, wickets_lost)),
        "wickets_remaining": float(max(0, 10 - wickets_lost)),
        "legal_balls": float(legal_balls),
        "balls_remaining": float(balls_remaining) if balls_remaining is not None else None,
        "innings_run_rate": run_rate,
        "batting_team_prior_runs": float(batting_team_prior_runs),
        "opposition_prior_runs": float(opposition_prior_runs),
        "target_runs": float(target_runs) if target_runs is not None else None,
        "runs_required": float(required) if required is not None else None,
        "required_run_rate": required_rate,
        "recent_runs_12_balls": float(recent_runs) if family != "Test" else None,
        "recent_wickets_12_balls": float(recent_wickets) if family != "Test" else None,
        "is_powerplay": float(limited and legal_balls < powerplay_balls),
        "is_middle": float(limited and powerplay_balls <= legal_balls < middle_end),
        "is_death": float(limited and legal_balls >= middle_end),
        "team1_runs": float(team1_runs), "team2_runs": float(team2_runs),
        "lead_from_team1": float(team1_runs - team2_runs),
        "current_innings_lead": float(team1_runs - team2_runs),
    }
    return {name: values.get(name) for name in FEATURES[family]}


def multiclass_metrics(y_true, probabilities, sample_weight=None) -> Dict[str, Any]:
    """Compute metrics with fixed class ordering so missing classes are visible."""
    import numpy as np
    from sklearn.metrics import accuracy_score, log_loss, roc_auc_score

    y = np.asarray(y_true, dtype=int)
    p = np.asarray(probabilities, dtype=float)
    weights = None if sample_weight is None else np.asarray(sample_weight, dtype=float)
    onehot = np.eye(3)[y]
    result: Dict[str, Any] = {
        "samples": int(len(y)),
        "brier_score": float(np.average(np.sum((p - onehot) ** 2, axis=1), weights=weights)),
        "log_loss": float(log_loss(y, p, labels=[0, 1, 2], sample_weight=weights)),
        "accuracy": float(accuracy_score(y, p.argmax(axis=1), sample_weight=weights)),
    }
    try:
        auc = float(roc_auc_score(y, p, multi_class="ovr", labels=[0, 1, 2], sample_weight=weights))
        result["roc_auc_ovr"] = auc if np.isfinite(auc) else None
    except ValueError:
        result["roc_auc_ovr"] = None
    calibration = {}
    for idx, name in enumerate(OUTCOMES):
        bins = []
        for low in (0.0, 0.2, 0.4, 0.6, 0.8):
            high = low + 0.2
            mask = (p[:, idx] >= low) & ((p[:, idx] < high) if high < 1 else (p[:, idx] <= high))
            if mask.any():
                bin_weights = None if weights is None else weights[mask]
                bins.append({"mean_predicted": float(np.average(p[mask, idx], weights=bin_weights)),
                             "observed_rate": float(np.average(onehot[mask, idx], weights=bin_weights)), "samples": int(mask.sum())})
        calibration[name] = bins
    result["calibration"] = calibration
    return result
