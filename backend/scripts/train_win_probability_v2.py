"""Train, calibrate and evaluate the v2 win-probability models.

Run from backend/::

    .venv/bin/python scripts/train_win_probability_v2.py            # all groups
    .venv/bin/python scripts/train_win_probability_v2.py --groups T20 ODI

Per format group (T20 [T20+T20I], ODI, ODM, Test, MDM):

1. Reconstruct pre-delivery states from CPI's PostgreSQL delivery tables.
2. Split labelled matches chronologically, whole matches only:
   train 60% / validation 15% / calibration 10% / test 15%.
3. Build the resource table from training first innings only; Elo, era par and
   venue par only use information dated before each match.
4. Fit baselines (constant prior, Elo-only, venue-par) and the legacy v1 logistic
   regression (C=1e-4, team1-oriented features) on the training partition.
5. Select among logistic regression (C grid) and HistGradientBoosting (grid,
   with/without monotonic constraints) on the validation partition.
6. Refit the selected model on train+validation, pick/fit a calibrator on the
   calibration partition (match-grouped CV inside that partition).
7. Report everything on the untouched test partition with match-level bootstrap CIs.

Outputs go to ``artifacts/win_probability/v2/``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import warnings
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db.session import SessionLocal  # noqa: E402
from app.ml.wp import context, data, features as F, modeling as M  # noqa: E402
from app.ml.wp.constants import (ELO_POOL, FULL_BALLS, GROUPS, LIMITED_GROUPS, MODEL_VERSION_PREFIX,  # noqa: E402
                                 MULTI_OUTCOMES, PARTITIONS)

# numpy 2.0 + Apple Accelerate raises spurious FP warnings inside matmul; results are unaffected.
warnings.filterwarnings("ignore", message=".*encountered in matmul", category=RuntimeWarning)

OUT = ROOT / "artifacts" / "win_probability" / "v2"
CACHE = ROOT / "artifacts" / "win_probability" / "cache"
LR_GRID = (0.01, 0.1, 1.0, 10.0)
HGB_GRID = [dict(max_iter=it, max_depth=d) for d in (2, 3, 4, 6) for it in (50, 100, 300, 600)]
LEGACY_C = 0.0001


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# --------------------------------------------------------------------------------------
# Legacy (v1) features, re-implemented vectorised for a like-for-like baseline
# --------------------------------------------------------------------------------------

def legacy_limited(states: pd.DataFrame, group: str) -> np.ndarray:
    full = FULL_BALLS[group]
    inn = states["innings_number"].to_numpy()
    runs = states["pre_runs"].to_numpy(float)
    wk = states["pre_wkts"].to_numpy(float)
    legal = states["pre_legal_count"].to_numpy(float)
    tov = states["target_overs"].to_numpy(float)
    cap = np.where(np.isnan(tov), full, np.minimum(full, tov * 6))
    balls_rem = np.maximum(0, cap - legal)
    target = states["target_runs"].to_numpy(float)  # v1 left missing targets missing
    req = np.where(np.isnan(target), np.nan, np.maximum(0, target - runs))
    with np.errstate(divide="ignore", invalid="ignore"):
        rrr = np.where(balls_rem > 0, req * 6 / balls_rem, np.where(req == 0, 0.0, np.nan))
        rr = np.where(legal > 0, runs * 6 / legal, np.nan)
    g = states.groupby("innings_id", sort=False, observed=True)
    recent_runs = runs - g["pre_runs"].shift(12).fillna(0).to_numpy(float)
    recent_wk = wk - g["pre_wkts"].shift(12).fillna(0).to_numpy(float)
    pp, mid_end = (36, 90) if group == "T20" else (60, 240)
    opp_prior = np.where(inn == 2, states["first_innings_total"].to_numpy(float), 0)
    cols = [states["batting_is_team1"].to_numpy(float), states["female"].to_numpy(float), np.zeros(len(states)),
            inn.astype(float), runs, wk, 10 - wk, legal, balls_rem, rr, np.zeros(len(states)), opp_prior, target,
            req, rrr, recent_runs, recent_wk, (legal < pp).astype(float),
            ((legal >= pp) & (legal < mid_end)).astype(float), (legal >= mid_end).astype(float)]
    return np.column_stack(cols).astype(np.float64)


def legacy_multiday(states: pd.DataFrame) -> np.ndarray:
    runs = states["pre_runs"].to_numpy(float)
    wk = states["pre_wkts"].to_numpy(float)
    legal = states["pre_legal_count"].to_numpy(float)
    t1 = states["batting_is_team1"].to_numpy(bool)
    prior = states["batting_prior_runs"].to_numpy(float)
    opp = states["opposition_runs"].to_numpy(float)
    team1_runs = np.where(t1, prior + runs, opp)
    team2_runs = np.where(t1, opp, prior + runs)
    with np.errstate(divide="ignore", invalid="ignore"):
        rr = np.where(legal > 0, runs * 6 / legal, np.nan)
    cols = [t1.astype(float), states["female"].to_numpy(float), (states["match_format"] == "Test").to_numpy(float),
            np.zeros(len(states)), states["innings_number"].to_numpy(float), runs, wk, 10 - wk, legal, rr,
            team1_runs, team2_runs, team1_runs - team2_runs, team1_runs - team2_runs, prior, opp]
    return np.column_stack(cols).astype(np.float64)


def legacy_pipeline():
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler
    return Pipeline([("impute", SimpleImputer(strategy="median", add_indicator=True)), ("scale", StandardScaler()),
                     ("lr", LogisticRegression(max_iter=500, C=LEGACY_C, random_state=29))])


def legacy_team1_labels(y_multi_bat: np.ndarray, bat_t1: np.ndarray) -> np.ndarray:
    """Batting-side labels (0 bat win, 1 bowl win, 2 draw) -> v1 labels (0 team1, 1 team2, 2 draw)."""
    out = np.where(y_multi_bat == 2, 2, np.where((y_multi_bat == 0) == bat_t1, 0, 1))
    return out.astype(int)


def legacy_to_batting(p3: np.ndarray, bat_t1: np.ndarray):
    bat = np.where(bat_t1, p3[:, 0], p3[:, 1])
    bowl = np.where(bat_t1, p3[:, 1], p3[:, 0])
    return bat, bowl, p3[:, 2]


# --------------------------------------------------------------------------------------
# Shared helpers
# --------------------------------------------------------------------------------------

def match_weights(innings_ids: np.ndarray) -> np.ndarray:
    s = pd.Series(innings_ids)
    return (1.0 / s.map(s.value_counts())).to_numpy(float)


def per_state_loss(y, p):
    m = p if p.ndim == 2 else np.column_stack([1 - p, p])
    return -np.log(np.clip(m[np.arange(len(y)), np.asarray(y, int)], M.EPS, 1))


def per_state_brier(y, p):
    if p.ndim == 1:
        return (p - y) ** 2
    return np.sum((p - np.eye(p.shape[1])[np.asarray(y, int)]) ** 2, axis=1)


def summarise(y, w, mid, preds: dict, kind: str, reps: int, labels=MULTI_OUTCOMES) -> dict:
    """Metrics for each prediction set + match-level bootstrap CIs and skill scores."""
    out = {}
    match_codes, match_index = np.unique(mid, return_inverse=True)
    weight_per_match = np.bincount(match_index, weights=w)
    sums = {}
    for name, p in preds.items():
        metrics = M.binary_metrics(y, p, w) if kind == "binary" else M.multiclass_metrics(y, p, w, labels)
        out[name] = metrics
        sums[f"{name}:log_loss"] = np.bincount(match_index, weights=w * per_state_loss(y, p))
        sums[f"{name}:brier"] = np.bincount(match_index, weights=w * per_state_brier(y, p))
    skill_pairs = {}
    for name in preds:
        for base in ("prior", "elo", "venue_par"):
            if name != base and base in preds:
                skill_pairs[f"{name}:skill_vs_{base}"] = (f"{name}:log_loss", f"{base}:log_loss")
    ci = M.bootstrap_ci(sums, weight_per_match, reps=reps, baselines=skill_pairs)
    for name in preds:
        out[name]["ci95"] = {k.split(":", 1)[1]: v for k, v in ci.items() if k.startswith(name + ":")}
        for base in ("prior", "elo", "venue_par"):
            if base in preds and name != base:
                out[name][f"skill_vs_{base}"] = 1 - out[name]["log_loss"] / out[base]["log_loss"]
    out["_matches"] = int(len(match_codes))
    return out


def segment_table(seg: pd.Series, y, w, preds: dict, kind: str) -> list:
    rows = []
    for value in [v for v in seg.dropna().unique()]:
        m = (seg == value).to_numpy()
        if m.sum() < 50:
            continue
        row = {"segment": str(value), "states": int(m.sum()), "weight": float(w[m].sum())}
        for name, p in preds.items():
            pm = p[m]
            row[f"{name}_log_loss"] = M.log_loss(y[m], pm, w[m])
            row[f"{name}_brier"] = M.brier(y[m], pm, w[m])
        for base in ("prior", "elo", "venue_par"):
            if base in preds:
                row[f"skill_vs_{base}"] = 1 - row["model_log_loss"] / row[f"{base}_log_loss"]
        rows.append(row)
    order = {s: i for i, s in enumerate(getattr(seg, "cat", None).categories)} if hasattr(seg, "cat") else {}
    return sorted(rows, key=lambda r: order.get(r["segment"], r["segment"]))


def select_candidates(candidates, xtr, ytr, wtr, xva, yva, wva, n_classes):
    results = {}
    best = None
    for name, factory in candidates:
        t0 = time.time()
        try:
            model = M.fit(factory(), xtr, ytr, wtr)
        except ValueError as exc:  # e.g. unsupported monotone constraints
            results[name] = {"error": str(exc)}
            continue
        p = M.predict(model, xva, n_classes)
        ll = M.log_loss(yva, p, wva)
        results[name] = {"validation_log_loss": ll, "validation_brier": M.brier(yva, p, wva), "fit_seconds": round(time.time() - t0, 1)}
        log(f"    {name}: valid log loss {ll:.4f}")
        if best is None or ll < results[best[0]]["validation_log_loss"]:
            best = (name, factory)
    return best, results


# --------------------------------------------------------------------------------------
# Limited overs
# --------------------------------------------------------------------------------------

def limited_segments(group, innings, f: pd.DataFrame, raw: pd.DataFrame) -> dict:
    full = FULL_BALLS[group]
    over = raw["legal_balls"] // 6
    if group == "T20":
        phase = pd.cut(over, [-1, 5, 14, 19], labels=["powerplay (1-6)", "middle (7-15)", "death (16-20)"])
        rrr_bins, rrr_labels = [-1, 6, 8, 10, 12, 1e9], ["<6", "6-8", "8-10", "10-12", "12+"]
    else:
        phase = pd.cut(over, [-1, 9, 39, 49], labels=["powerplay (1-10)", "middle (11-40)", "death (41-50)"])
        rrr_bins, rrr_labels = [-1, 4.5, 6, 7.5, 9, 1e9], ["<4.5", "4.5-6", "6-7.5", "7.5-9", "9+"]
    wk = pd.cut(f["wickets_remaining"], [-1, 2, 4, 7, 10], labels=["1-2", "3-4", "5-7", "8-10"])
    seg = {"phase": phase, "wickets_remaining": wk}
    if innings == 2:
        seg["required_run_rate"] = pd.cut(f["required_run_rate"], rrr_bins, labels=rrr_labels)
        seg["situation"] = pd.cut(f["chase_resource_ratio"], [-1, 0.8, 1.2, 1e9],
                                  labels=["ahead of par (<0.8)", "balanced (0.8-1.2)", "behind par (>1.2)"])
    else:
        ratio = f["expected_final_score"] / f["venue_par"]
        seg["situation"] = pd.cut(ratio, [-1, 0.92, 1.08, 1e9], labels=["below par", "near par", "above par"])
    return seg


def run_limited(group, frame, innings_tbl, partition_of, args):
    full = FULL_BALLS[group]
    frame = frame[frame["innings_number"].isin([1, 2])]
    states = F.sample_states(frame, 1).reset_index(drop=True)
    raw = F.limited_raw_states(states, group)
    raw["partition"] = raw["match_id"].map(partition_of).fillna("unlabelled")
    valid = F.validate_limited(raw, group)
    terminal = ~np.isnan(F.limited_terminal(raw))
    label = states["label_bat_win"].to_numpy()
    audit = {
        "pre_delivery_states": int(len(raw)),
        "invalid_states_excluded": int((~valid).sum()),
        "terminal_pre_delivery_states_excluded": int((valid & terminal).sum()),
        "unlabelled_states_excluded": int(np.isnan(label).sum()),
        "second_innings_target_derived_from_first_innings": int(
            raw.loc[raw["innings"] == 2, "target_source"].eq("first_innings_total+1").sum()),
        "chase_states_beyond_rounded_dls_allotment": int(raw["allotment_rounded"].sum()),
    }

    # Resource table: training first innings that ran their natural course only.
    tot = innings_tbl.set_index(innings_tbl["innings_id"].astype(str))
    inn_ids = states["innings_id"].astype(str)
    total_runs = inn_ids.map(tot["runs"]).to_numpy(float)
    complete = (inn_ids.map(tot["wickets"]).to_numpy(float) >= 10) | (inn_ids.map(tot["legal_balls"]).to_numpy(float) >= full)
    rt_mask = valid & (raw["innings"].to_numpy() == 1) & (raw["partition"].to_numpy() == "train") & complete
    rt_states = pd.DataFrame({"balls_remaining": full - raw.loc[rt_mask, "legal_balls"].to_numpy(),
                              "wickets_lost": raw.loc[rt_mask, "wickets_lost"].to_numpy(),
                              "runs_remaining": total_runs[rt_mask] - raw.loc[rt_mask, "runs"].to_numpy()})
    table = F.fit_resource_table(rt_states, full)
    log(f"  resource table from {len(rt_states):,} training states; full-innings expectation {table.full_innings_runs:.1f}")

    stride_ok = (raw["legal_balls"].to_numpy() % args.stride == 0) | np.isin(raw["partition"].to_numpy(), ["calibration", "test"])
    keep = valid & ~terminal & ~np.isnan(label) & (raw["partition"].to_numpy() != "unlabelled") & stride_ok
    raw, states, label = raw[keep].reset_index(drop=True), states[keep].reset_index(drop=True), label[keep].astype(int)
    legacy_x = legacy_limited(states, group)
    legacy_y = np.where(states["batting_is_team1"].to_numpy(), 1 - label, label)  # 0 team1 wins, 1 team2 wins

    family = {"resource_table": table, "models": {}, "evaluation": {}, "audit": audit}
    test_rows = []
    for innings in (1, 2):
        log(f"  innings {innings}")
        m_inn = raw["innings"].to_numpy() == innings
        r = raw[m_inn].reset_index(drop=True)
        st = states[m_inn].reset_index(drop=True)
        y = label[m_inn]
        w = match_weights(st["innings_id"].astype(str).to_numpy())
        X = F.limited_features(r, innings, table)
        names = list(X.columns)
        part = r["partition"].to_numpy()
        P = {p: part == p for p, _ in PARTITIONS}
        x = X.to_numpy(np.float64)

        # ---- baselines (fit on train only)
        prior = float(np.average(y[P["train"]], weights=w[P["train"]]))
        elo_model = M.fit(M.logistic(1.0), X[["elo_diff"]].to_numpy()[P["train"]], y[P["train"]], w[P["train"]])
        if innings == 1:
            naive_proj = np.where(r["legal_balls"] > 0, X["runs"] + X["current_run_rate"].fillna(0) * X["balls_remaining"] / 6,
                                  X["venue_par"])
            vp_feature = (naive_proj - X["venue_par"]).to_numpy()[:, None]
        else:
            vp_feature = X[["target_minus_venue_par"]].to_numpy()
        vp_model = M.fit(M.logistic(1.0), vp_feature[P["train"]], y[P["train"]], w[P["train"]])
        lx, ly = legacy_x[m_inn], legacy_y[m_inn]
        legacy = legacy_pipeline().fit(lx[P["train"]], ly[P["train"]], lr__sample_weight=w[P["train"]])

        # ---- model selection on validation
        mono = F.LIMITED_MONOTONE[innings]
        candidates = [(f"logistic_C={c}", (lambda c=c: M.logistic(c))) for c in LR_GRID]
        candidates += [(f"hgb_depth={g['max_depth']}_iter={g['max_iter']}", (lambda g=g: M.gradient_boosting(names, **g)))
                       for g in HGB_GRID]
        best, results = select_candidates(candidates, x[P["train"]], y[P["train"]], w[P["train"]],
                                          x[P["validation"]], y[P["validation"]], w[P["validation"]], 2)
        best_hgb = min((k for k in results if k.startswith("hgb") and "error" not in results[k]),
                       key=lambda k: results[k]["validation_log_loss"])
        g = HGB_GRID[[f"hgb_depth={c['max_depth']}_iter={c['max_iter']}" for c in HGB_GRID].index(best_hgb)]
        mono_name = best_hgb + "_monotone"
        b2, r2 = select_candidates([(mono_name, lambda g=g: M.gradient_boosting(names, monotone=mono, **g))],
                                   x[P["train"]], y[P["train"]], w[P["train"]],
                                   x[P["validation"]], y[P["validation"]], w[P["validation"]], 2)
        results.update(r2)
        if "error" not in r2[mono_name] and r2[mono_name]["validation_log_loss"] <= results[best[0]]["validation_log_loss"]:
            best = b2
        best_lr = min((k for k in results if k.startswith("logistic")), key=lambda k: results[k]["validation_log_loss"])
        log(f"  selected {best[0]} (best LR {best_lr})")

        trva = P["train"] | P["validation"]
        final = M.fit(best[1](), x[trva], y[trva], w[trva])
        lr_factory = dict(candidates)[best_lr]
        final_lr = M.fit(lr_factory(), x[trva], y[trva], w[trva])
        cal_p = M.predict(final, x[P["calibration"]])
        calibrator, cal_scores = M.choose_calibrator(cal_p, y[P["calibration"]], w[P["calibration"]],
                                                     r.loc[P["calibration"], "match_id"].to_numpy())
        log(f"  calibration: {calibrator.method} {cal_scores}")

        # ---- test
        T = P["test"]
        raw_p = M.predict(final, x[T])
        preds = {
            "model": calibrator.transform(raw_p),
            "model_uncalibrated": raw_p,
            "model_isotonic": M.Calibrator("isotonic").fit(cal_p, y[P["calibration"]], w[P["calibration"]]).transform(raw_p),
            "model_sigmoid": M.Calibrator("sigmoid").fit(cal_p, y[P["calibration"]], w[P["calibration"]]).transform(raw_p),
            "best_logistic": M.predict(final_lr, x[T]),
            "prior": np.full(T.sum(), prior),
            "elo": M.predict(elo_model, X[["elo_diff"]].to_numpy()[T]),
            "venue_par": M.predict(vp_model, vp_feature[T]),
        }
        lp = legacy.predict_proba(lx[T])
        lp3 = np.zeros((T.sum(), 3))
        for i, c in enumerate(legacy.classes_):
            lp3[:, int(c)] = lp[:, i]
        bat, bowl, _ = legacy_to_batting(lp3, st.loc[T, "batting_is_team1"].to_numpy())
        preds["legacy_v1_logistic"] = np.clip(bat / np.clip(bat + bowl, M.EPS, None), M.EPS, 1 - M.EPS)
        yt, wt, mt = y[T], w[T], r.loc[T, "match_id"].to_numpy()
        evaluation = summarise(yt, wt, mt, preds, "binary", args.bootstrap)
        evaluation["calibration_curves"] = {k: M.calibration_bins(yt, preds[k], wt) for k in
                                            ("model", "model_uncalibrated", "legacy_v1_logistic", "elo", "venue_par")}
        seg_preds = {k: preds[k] for k in ("model", "prior", "elo", "venue_par", "legacy_v1_logistic")}
        segs = limited_segments(group, innings, X[T].reset_index(drop=True), r[T].reset_index(drop=True))
        evaluation["segments"] = {name: segment_table(s, yt, wt, seg_preds, "binary") for name, s in segs.items()}
        if group == "T20":
            fmt = st.loc[T, "match_format"].to_numpy()
            evaluation["by_source_format"] = {f_: summarise(yt[fmt == f_], wt[fmt == f_], mt[fmt == f_],
                                                            {k: preds[k][fmt == f_] for k in ("model", "prior", "elo", "venue_par", "legacy_v1_logistic")},
                                                            "binary", 100) for f_ in np.unique(fmt)}
        evaluation["selection"] = {"candidates": results, "selected": best[0], "best_logistic": best_lr,
                                   "calibration_cv_log_loss": cal_scores, "calibration_method": calibrator.method,
                                   "prior_batting_win_rate_train": prior}
        evaluation["partition_sizes"] = {p: {"states": int(P[p].sum()),
                                             "matches": int(r.loc[P[p], "match_id"].nunique())} for p, _ in PARTITIONS}
        family["evaluation"][innings] = evaluation
        support = np.zeros((full + 1, 11))
        np.add.at(support, (np.clip(X.loc[P["train"], "balls_remaining"].to_numpy(int), 0, full),
                            X.loc[P["train"], "wickets_lost"].to_numpy(int)), 1)
        family["models"][innings] = {"model": final, "calibrator": calibrator, "features": names,
                                     "selected": best[0], "support_table": support,
                                     "support_note": f"training states per (balls remaining, wickets lost), stride {args.stride}"}
        test_rows.append(pd.DataFrame({"y": yt, "w": wt, "match_id": mt, **{k: preds[k] for k in
                                       ("model", "model_uncalibrated", "prior", "elo", "venue_par", "legacy_v1_logistic", "best_logistic")}}))
    both = pd.concat(test_rows, ignore_index=True)
    family["evaluation"]["overall"] = summarise(both["y"].to_numpy(), both["w"].to_numpy(), both["match_id"].to_numpy(),
                                                {k: both[k].to_numpy() for k in both.columns if k not in ("y", "w", "match_id")},
                                                "binary", args.bootstrap)
    family["evaluation"]["overall"]["calibration_curves"] = {
        k: M.calibration_bins(both["y"], both[k], both["w"]) for k in ("model", "model_uncalibrated", "legacy_v1_logistic")}
    return family


# --------------------------------------------------------------------------------------
# Multi-day
# --------------------------------------------------------------------------------------

def run_multiday(group, frame, partition_of, args):
    states = F.sample_states(frame[frame["innings_number"].between(1, 4)], 1).reset_index(drop=True)
    raw = F.multiday_raw_states(states)
    raw["partition"] = raw["match_id"].map(partition_of).fillna("unlabelled")
    valid = F.validate_multiday(raw)
    terminal = ~np.isnan(F.multiday_terminal(raw))
    label = states["label_multi"].to_numpy()
    audit = {"pre_delivery_states": int(len(raw)), "invalid_states_excluded": int((~valid).sum()),
             "terminal_pre_delivery_states_excluded": int((valid & terminal).sum()),
             "unlabelled_states_excluded": int(np.isnan(label).sum())}
    stride_ok = raw["legal_balls"].to_numpy() % args.multiday_stride == 0
    keep = valid & ~terminal & ~np.isnan(label) & (raw["partition"].to_numpy() != "unlabelled") & stride_ok
    raw, states, y = raw[keep].reset_index(drop=True), states[keep].reset_index(drop=True), label[keep].astype(int)
    w = match_weights(states["match_id"].astype(str).to_numpy())  # each match counts once
    X = F.multiday_features(raw)
    names = list(X.columns)
    x = X.to_numpy(np.float64)
    part = raw["partition"].to_numpy()
    P = {p: part == p for p, _ in PARTITIONS}
    support = pd.Series(F.multiday_support_key(raw["innings"], raw["wickets_lost"], raw["match_legal_balls"])[P["train"]]).value_counts()

    prior = np.array([np.average(y[P["train"]] == k, weights=w[P["train"]]) for k in range(3)])
    elo_model = M.fit(M.logistic(1.0), X[["elo_diff"]].to_numpy()[P["train"]], y[P["train"]], w[P["train"]])
    vp_x = np.column_stack([X["lead"], X["innings_runs"] - X["venue_par"]])
    vp_model = M.fit(M.logistic(1.0), vp_x[P["train"]], y[P["train"]], w[P["train"]])
    lx = legacy_multiday(states)
    ly = legacy_team1_labels(y, states["batting_is_team1"].to_numpy())
    legacy = legacy_pipeline().fit(lx[P["train"]], ly[P["train"]], lr__sample_weight=w[P["train"]])

    candidates = [(f"logistic_C={c}", (lambda c=c: M.logistic(c))) for c in LR_GRID]
    candidates += [(f"hgb_depth={g['max_depth']}_iter={g['max_iter']}", (lambda g=g: M.gradient_boosting(names, **g)))
                   for g in HGB_GRID]
    # Monotone constraints are not supported by scikit-learn for multiclass targets; record the attempt.
    candidates.append(("hgb_monotone_attempt", lambda: M.gradient_boosting(names, monotone={"lead": 1}, max_iter=50)))
    best, results = select_candidates(candidates, x[P["train"]], y[P["train"]], w[P["train"]],
                                      x[P["validation"]], y[P["validation"]], w[P["validation"]], 3)
    best_lr = min((k for k in results if k.startswith("logistic")), key=lambda k: results[k]["validation_log_loss"])
    log(f"  selected {best[0]} (best LR {best_lr})")
    trva = P["train"] | P["validation"]
    final = M.fit(best[1](), x[trva], y[trva], w[trva])
    final_lr = M.fit(dict(candidates)[best_lr](), x[trva], y[trva], w[trva])
    cal_p = M.predict(final, x[P["calibration"]], 3)
    calibrator, cal_scores = M.choose_calibrator(cal_p, y[P["calibration"]], w[P["calibration"]],
                                                 raw.loc[P["calibration"], "match_id"].to_numpy(), n_classes=3)
    log(f"  calibration: {calibrator.method} {cal_scores}")
    T = P["test"]
    raw_p = M.predict(final, x[T], 3)
    lp = legacy.predict_proba(lx[T])
    lp3 = np.zeros((T.sum(), 3))
    for i, c in enumerate(legacy.classes_):
        lp3[:, int(c)] = lp[:, i]
    bat, bowl, draw = legacy_to_batting(lp3, states.loc[T, "batting_is_team1"].to_numpy())
    preds = {
        "model": calibrator.transform(raw_p),
        "model_uncalibrated": raw_p,
        "model_isotonic": M.Calibrator("isotonic").fit(cal_p, y[P["calibration"]], w[P["calibration"]]).transform(raw_p),
        "model_sigmoid": M.Calibrator("sigmoid").fit(cal_p, y[P["calibration"]], w[P["calibration"]]).transform(raw_p),
        "best_logistic": M.predict(final_lr, x[T], 3),
        "prior": np.tile(prior, (T.sum(), 1)),
        "elo": M.predict(elo_model, X[["elo_diff"]].to_numpy()[T], 3),
        "venue_par": M.predict(vp_model, vp_x[T], 3),
        "legacy_v1_logistic": np.column_stack([bat, bowl, draw]),
    }
    yt, wt, mt = y[T], w[T], raw.loc[T, "match_id"].to_numpy()
    evaluation = {"overall": summarise(yt, wt, mt, preds, "multi", args.bootstrap)}
    evaluation["overall"]["calibration_curves"] = {
        k: {name: M.calibration_bins(yt == j, preds[k][:, j], wt) for j, name in enumerate(MULTI_OUTCOMES)}
        for k in ("model", "model_uncalibrated", "legacy_v1_logistic")}
    Xt, rt = X[T].reset_index(drop=True), raw[T].reset_index(drop=True)
    segs = {
        "innings": rt["innings"].map(lambda v: f"innings {v}"),
        "match_stage_overs": pd.cut(rt["match_legal_balls"] / 6, [-1, 90, 180, 270, 360, 1e9],
                                    labels=["0-90", "90-180", "180-270", "270-360", "360+"]),
        "wickets_remaining": pd.cut(Xt["wickets_remaining"], [-1, 2, 4, 7, 10], labels=["1-2", "3-4", "5-7", "8-10"]),
    }
    seg_preds = {k: preds[k] for k in ("model", "prior", "elo", "venue_par", "legacy_v1_logistic")}
    evaluation["segments"] = {name: segment_table(s, yt, wt, seg_preds, "multi") for name, s in segs.items()}
    evaluation["selection"] = {"candidates": results, "selected": best[0], "best_logistic": best_lr,
                               "calibration_cv_log_loss": cal_scores, "calibration_method": calibrator.method,
                               "prior_train": dict(zip(MULTI_OUTCOMES, prior.tolist()))}
    evaluation["partition_sizes"] = {p: {"states": int(P[p].sum()), "matches": int(raw.loc[P[p], "match_id"].nunique())}
                                     for p, _ in PARTITIONS}
    return {"models": {"all": {"model": final, "calibrator": calibrator, "features": names, "selected": best[0],
                               "support_table": support.to_dict()}},
            "evaluation": {"all": evaluation}, "audit": audit}


# --------------------------------------------------------------------------------------
# Plots (dependency-free SVG reliability diagrams)
# --------------------------------------------------------------------------------------

COLORS = {"model": "#2563eb", "model_uncalibrated": "#93c5fd", "legacy_v1_logistic": "#dc2626",
          "elo": "#16a34a", "venue_par": "#a16207"}


def reliability_svg(title: str, curves: dict, path: Path):
    size, pad = 360, 48
    plot = size - 2 * pad
    sx = lambda v: pad + v * plot  # noqa: E731
    sy = lambda v: size - pad - v * plot  # noqa: E731
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{size + 170}" height="{size}" font-family="sans-serif" font-size="11">',
             f'<rect width="100%" height="100%" fill="white"/>',
             f'<text x="{pad}" y="20" font-size="13" font-weight="bold">{title}</text>',
             f'<line x1="{sx(0)}" y1="{sy(0)}" x2="{sx(1)}" y2="{sy(1)}" stroke="#9ca3af" stroke-dasharray="4 3"/>',
             f'<rect x="{pad}" y="{pad}" width="{plot}" height="{plot}" fill="none" stroke="#374151"/>']
    for t in (0, .25, .5, .75, 1):
        parts.append(f'<text x="{sx(t)}" y="{size - pad + 14}" text-anchor="middle">{t:g}</text>')
        parts.append(f'<text x="{pad - 6}" y="{sy(t) + 4}" text-anchor="end">{t:g}</text>')
    parts.append(f'<text x="{size / 2}" y="{size - 8}" text-anchor="middle">Predicted probability</text>')
    parts.append(f'<text x="12" y="{size / 2}" transform="rotate(-90 12 {size / 2})" text-anchor="middle">Observed frequency</text>')
    for i, (name, bins) in enumerate(curves.items()):
        color = COLORS.get(name, "#6b7280")
        pts = " ".join(f"{sx(b['mean_predicted']):.1f},{sy(b['observed']):.1f}" for b in bins)
        parts.append(f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="2"/>')
        for b in bins:
            parts.append(f'<circle cx="{sx(b["mean_predicted"]):.1f}" cy="{sy(b["observed"]):.1f}" r="2.5" fill="{color}"/>')
        parts.append(f'<rect x="{size + 4}" y="{pad + i * 18 - 9}" width="10" height="10" fill="{color}"/>')
        parts.append(f'<text x="{size + 18}" y="{pad + i * 18}">{name}</text>')
    parts.append("</svg>")
    path.write_text("\n".join(parts))


# --------------------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------------------

def strip_models(family):
    return {k: v for k, v in family.items() if k not in ("models", "resource_table")}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--groups", nargs="*", default=list(GROUPS))
    parser.add_argument("--stride", type=int, default=2, help="legal-ball stride for limited-overs train/validation states")
    parser.add_argument("--multiday-stride", type=int, default=6, help="legal-ball stride for multi-day states (all partitions)")
    parser.add_argument("--bootstrap", type=int, default=300)
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "plots").mkdir(exist_ok=True)
    db = SessionLocal()
    try:
        fingerprint = data.data_fingerprint(db)
        matches = data.load_matches(db)
        innings_tbl = data.load_innings_summary(db)
        elo, elo_snapshot = context.compute_elo(matches)
        pars, par_snapshot = context.compute_pars(matches, innings_tbl)
        table = F.build_match_table(matches, elo, pars)
        report_path = OUT / "evaluation.json"
        report = json.loads(report_path.read_text()) if report_path.exists() else {}
        report.update({"model_version_prefix": MODEL_VERSION_PREFIX, "data_fingerprint": fingerprint,
                       "generated": time.strftime("%Y-%m-%d %H:%M:%S"), "partitions": dict(PARTITIONS)})
        report.setdefault("groups", {})
        for group in args.groups:
            formats = GROUPS[group]
            t0 = time.time()
            log(f"== {group} ({', '.join(formats)})")
            sub = table[table["group"] == group]
            labelled = sub["has_winner"] | (sub["is_draw"] if group not in LIMITED_GROUPS else False)
            partition = F.assign_partitions(sub, labelled)
            partition_of = dict(zip(sub["match_id"], partition))
            deliveries = data.load_deliveries(db, formats, CACHE)
            frame = F.delivery_frame(deliveries, innings_tbl, table)
            frame = F.add_innings_context(frame, innings_tbl)
            log(f"  {len(frame):,} deliveries, {sub.shape[0]:,} matches")
            if group in LIMITED_GROUPS:
                family = run_limited(group, frame, innings_tbl, partition_of, args)
            else:
                family = run_multiday(group, frame, partition_of, args)
            split_dates = {}
            for p, _ in PARTITIONS:
                d = sub.loc[partition == p, "start_date"]
                split_dates[p] = {"from": str(d.min().date()), "to": str(d.max().date()), "matches": int(len(d))}
            split_dates["unlabelled"] = {"matches": int((partition == "unlabelled").sum()),
                                         "reason": "no result, abandoned, or tie without recorded winner" if group in LIMITED_GROUPS else "no result or tie"}
            selected = {k: v["selected"] for k, v in family["models"].items()}
            code = hashlib.sha1(b"".join(Path(mod.__file__).read_bytes() for mod in (F, M, context, data))
                                + Path(__file__).read_bytes()).hexdigest()[:12]
            signature = json.dumps({"group": group, "fingerprint": fingerprint, "splits": split_dates, "selected": selected,
                                    "code": code}, sort_keys=True)
            version = f"{MODEL_VERSION_PREFIX}-{group.lower()}-{hashlib.sha1(signature.encode()).hexdigest()[:10]}"
            pool = ELO_POOL[formats[0]]
            bundle = {
                "version": version, "group": group, "formats": formats,
                "kind": "limited" if group in LIMITED_GROUPS else "multiday",
                "models": family["models"], "resource_table": family.get("resource_table"),
                "context": {"elo": {k: v for k, v in elo_snapshot.items() if k.startswith(pool + "|")},
                            "era": {k: v for k, v in par_snapshot["era"].items() if k.startswith(group + "|")},
                            "venue": {k: v for k, v in par_snapshot["venue"].items() if k.startswith(group + "|")}},
                "partition_of": {k: v for k, v in partition_of.items()},
                "splits": split_dates, "data_fingerprint": fingerprint, "code_hash": code,
                "trained_through": split_dates["validation"]["to"], "calibrated_through": split_dates["calibration"]["to"],
            }
            joblib.dump(bundle, OUT / f"{group.lower()}.joblib", compress=3)
            group_report = {"version": version, "code_hash": code, "formats": formats, "splits": split_dates, **strip_models(family),
                            "features": {str(k): v["features"] for k, v in family["models"].items()},
                            "seconds": round(time.time() - t0, 1)}
            if group in LIMITED_GROUPS:
                rt = family["resource_table"]
                group_report["resource_table_preview"] = {
                    f"{b}_balls_remaining": {f"{w}_down": round(float(rt.expected[b, w]), 1) for w in (0, 2, 4, 6, 8)}
                    for b in (FULL_BALLS[group], FULL_BALLS[group] // 2, FULL_BALLS[group] // 4, 12)}
                for inn in (1, 2):
                    reliability_svg(f"{group} innings {inn} (test partition)",
                                    family["evaluation"][inn]["calibration_curves"], OUT / "plots" / f"{group.lower()}_innings{inn}.svg")
            else:
                curves = family["evaluation"]["all"]["overall"]["calibration_curves"]
                for cls in MULTI_OUTCOMES:
                    reliability_svg(f"{group} {cls} (test partition)", {k: v[cls] for k, v in curves.items()},
                                    OUT / "plots" / f"{group.lower()}_{cls}.svg")
            report["groups"][group] = group_report
            report_path.write_text(json.dumps(report, indent=2, default=lambda o: o.item() if hasattr(o, "item") else str(o)))
            log(f"  done in {time.time() - t0:.0f}s -> {version}")
            del deliveries, frame
    finally:
        db.close()


if __name__ == "__main__":
    main()
