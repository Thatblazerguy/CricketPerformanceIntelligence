"""Ablation of the v1 defects on the v2 partitions (validation partition only).

Run from backend/: ``.venv/bin/python scripts/audit_win_probability_v1.py [--groups T20 ODI ODM]``

Isolates the contribution of each v1 problem using the *same* states and labels:

A. v1 as shipped: team1-oriented 3-class LR, C=1e-4, missing targets left missing
B. A with C=1 (regularisation fixed only)
C. B with batting-side orientation (label = batting side wins; team1 flag dropped)
D. C with missing targets derived from first-innings total + 1
E. v2 features, LR C=1 (no gradient boosting, no calibration)

Writes ``artifacts/win_probability/v2/v1_ablation.json``.
"""
from __future__ import annotations

import argparse
import json
import sys
import warnings
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
warnings.filterwarnings("ignore", message=".*encountered in matmul", category=RuntimeWarning)

from app.db.session import SessionLocal  # noqa: E402
from app.ml.wp import context, data, features as F, modeling as M  # noqa: E402
from app.ml.wp.constants import GROUPS  # noqa: E402
from scripts.train_win_probability_v2 import CACHE, OUT, legacy_limited, match_weights  # noqa: E402


def fit_eval(x_tr, y_tr, w_tr, x_va, C, multiclass=False):
    model = M.fit(M.logistic(C), x_tr, y_tr, w_tr)
    raw = model.predict_proba(x_va)
    out = np.zeros((len(x_va), 3 if multiclass else 2))
    for i, c in enumerate(model.classes_):
        out[:, int(c)] = raw[:, i]
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--groups", nargs="*", default=["T20", "ODI", "ODM"])
    args = parser.parse_args()
    db = SessionLocal()
    results = {}
    try:
        matches = data.load_matches(db)
        innings = data.load_innings_summary(db)
        elo, _ = context.compute_elo(matches)
        pars, _ = context.compute_pars(matches, innings)
        table = F.build_match_table(matches, elo, pars)
        for group in args.groups:
            sub = table[table["group"] == group]
            part = dict(zip(sub["match_id"], F.assign_partitions(sub, sub["has_winner"])))
            frame = F.add_innings_context(F.delivery_frame(data.load_deliveries(db, GROUPS[group], CACHE), innings, table), innings)
            frame = frame[frame["innings_number"].isin([1, 2])]
            st = F.sample_states(frame, 1).reset_index(drop=True)
            raw = F.limited_raw_states(st, group)
            p = raw["match_id"].map(part).fillna("unlabelled").to_numpy()
            keep = (F.validate_limited(raw, group) & np.isnan(F.limited_terminal(raw)) & st["label_bat_win"].notna().to_numpy()
                    & np.isin(p, ["train", "validation"]) & (raw["legal_balls"].to_numpy() % 2 == 0))
            st, raw, p = st[keep].reset_index(drop=True), raw[keep].reset_index(drop=True), p[keep]
            y = st["label_bat_win"].to_numpy(int)
            t1 = st["batting_is_team1"].to_numpy(bool)
            w = match_weights(st["innings_id"].astype(str).to_numpy())
            tr, va = p == "train", p == "validation"
            leg = legacy_limited(st, group)
            y_team = np.where(t1, 1 - y, y)  # v1 classes: 0 team1 wins, 1 team2 wins
            group_out = {}
            for inn in (1, 2):
                m = raw["innings"].to_numpy() == inn
                a, b = m & tr, m & va
                def bat_ll(p2):  # team1/team2 probabilities -> batting-side log loss
                    bat = np.where(t1[b], p2[:, 0], p2[:, 1])
                    return M.log_loss(y[b], np.clip(bat / np.clip(p2[:, 0] + p2[:, 1], 1e-9, None), 1e-6, 1 - 1e-6), w[b])
                row = {"A_v1_as_shipped_C=1e-4": bat_ll(fit_eval(leg[a], y_team[a], w[a], leg[b], 1e-4)),
                       "B_v1_C=1": bat_ll(fit_eval(leg[a], y_team[a], w[a], leg[b], 1.0))}
                oriented = leg[:, 1:]  # drop team1_batting
                row["C_batting_oriented_C=1"] = M.log_loss(y[b], fit_eval(oriented[a], y[a], w[a], oriented[b], 1.0)[:, 1], w[b])
                fixed = oriented.copy()
                if inn == 2:  # columns shift by one after dropping team1_batting: target=11, runs_required=12, rrr=13
                    tgt = raw["target"].to_numpy(float)
                    runs = raw["runs"].to_numpy(float)
                    balls = raw["max_balls"].to_numpy(float) - raw["legal_balls"].to_numpy(float)
                    fixed[:, 11] = tgt
                    fixed[:, 12] = np.maximum(0, tgt - runs)
                    with np.errstate(divide="ignore", invalid="ignore"):
                        fixed[:, 13] = np.where(balls > 0, fixed[:, 12] * 6 / balls, np.nan)
                row["D_plus_derived_targets"] = M.log_loss(y[b], fit_eval(fixed[a], y[a], w[a], fixed[b], 1.0)[:, 1], w[b])
                X = F.limited_features(raw, inn, F.fit_resource_table(  # resource table from training first innings
                    _rt_states(raw, st, innings, group, tr), F.FULL_BALLS[group])).to_numpy(np.float64)
                row["E_v2_features_LR_C=1"] = M.log_loss(y[b], fit_eval(X[a], y[a], w[a], X[b], 1.0)[:, 1], w[b])
                row["validation_states"] = int(b.sum())
                group_out[f"innings_{inn}"] = row
                print(group, inn, {k: round(v, 4) if isinstance(v, float) else v for k, v in row.items()}, flush=True)
            results[group] = group_out
    finally:
        db.close()
    (OUT / "v1_ablation.json").write_text(json.dumps(results, indent=2))


def _rt_states(raw, st, innings, group, train_mask):
    import pandas as pd
    full = F.FULL_BALLS[group]
    tot = innings.set_index(innings["innings_id"].astype(str))
    ids = st["innings_id"].astype(str)
    complete = (ids.map(tot["wickets"]).to_numpy() >= 10) | (ids.map(tot["legal_balls"]).to_numpy() >= full)
    m = train_mask & (raw["innings"].to_numpy() == 1) & complete
    return pd.DataFrame({"balls_remaining": full - raw.loc[m, "legal_balls"].to_numpy(),
                         "wickets_lost": raw.loc[m, "wickets_lost"].to_numpy(),
                         "runs_remaining": ids[m].map(tot["runs"]).to_numpy() - raw.loc[m, "runs"].to_numpy()})


if __name__ == "__main__":
    main()
