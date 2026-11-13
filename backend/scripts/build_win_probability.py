"""Train format-family models and precompute historical delivery probabilities/WPA.

Run from backend/: ``.venv/bin/python scripts/build_win_probability.py``.
The job is resumable by model version and only reads source match/delivery rows.
"""
from __future__ import annotations

import gzip
import hashlib
import argparse
import json
import math
import sys
from collections import defaultdict, deque
from datetime import date
from pathlib import Path

import numpy as np
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
import joblib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.core.config import settings
from app.db.session import SessionLocal
from app.ml.win_probability import FEATURES, FORMAT_FAMILY, MODEL_VERSION_PREFIX, format_family, match_state_features, result_label, multiclass_metrics
from app.models.models import MatchWinProbability, PlayerWinProbabilityImpact

ARTIFACT_DIR = ROOT / "artifacts" / "win_probability"
MATCH_SQL_TEMPLATE = """
SELECT m.id AS match_id, m.match_format, m.gender, m.start_date, m.team1_id, m.team2_id,
       m.winner_id, m.result_type, i.id AS innings_id, i.innings_number,
       i.batting_team_id, i.target_runs, i.target_overs, i.is_super_over,
       d.id AS delivery_id, d.over_number, d.delivery_sequence, d.batter_id,
       d.bowler_id, d.batter_runs, d.total_runs, d.is_legal_ball,
       d.is_boundary_four, d.is_boundary_six, coalesce(w.dismissals, 0) AS wickets
FROM matches m
JOIN match_innings i ON i.match_id=m.id
JOIN deliveries d ON d.innings_id=i.id
LEFT JOIN (SELECT delivery_id, count(*) FILTER (WHERE is_batter_dismissed) AS dismissals
           FROM wickets GROUP BY delivery_id) w ON w.delivery_id=d.id
WHERE m.match_format = ANY(:formats)
  {match_filter}
ORDER BY m.start_date, m.id, i.innings_number, d.over_number, d.delivery_sequence
"""
MATCH_SQL = text(MATCH_SQL_TEMPLATE.format(match_filter=""))
# Same query restricted to specific matches (used by the incremental Cricsheet sync).
MATCH_SUBSET_SQL = text(MATCH_SQL_TEMPLATE.format(match_filter="AND m.id = ANY(:match_ids)"))


def _matrix(rows, family):
    matrix = np.asarray([[np.nan if row.get(k) is None else row[k] for k in FEATURES[family]] for row in rows], dtype=np.float32)
    # Keep bad source outliers from destabilizing the optimizer while preserving missingness.
    matrix = np.where(np.isinf(matrix), np.sign(matrix) * 10000.0, matrix)
    return np.clip(matrix, -10000.0, 10000.0)


def _predict_three(model, x):
    raw = model.predict_proba(x)
    raw = np.nan_to_num(raw, nan=1.0 / 3.0, posinf=1.0, neginf=0.0)
    raw = np.clip(raw, 1e-9, 1.0)
    # Keep metric inputs in float64 so sklearn's strict multiclass normalization
    # check is not tripped by float32 summation noise.
    result = np.zeros((len(x), 3), dtype=np.float64)
    for idx, cls in enumerate(model.classes_):
        result[:, int(cls)] = raw[:, idx]
    # Models are required to be three-class, but normalize defensively for numerical drift.
    sums = result.sum(axis=1, keepdims=True)
    return result / np.where(sums == 0, 1, sums)


def _pipeline():
    return Pipeline([
        ("imputer", SimpleImputer(strategy="median", add_indicator=True)),
        ("scale", StandardScaler()),
        ("classifier", LogisticRegression(solver="lbfgs", max_iter=500, C=0.0001, random_state=29)),
    ])


def _split_dates(db: Session, formats: list[str]):
    rows = db.execute(text("""
        SELECT DISTINCT start_date FROM matches
        WHERE match_format = ANY(:formats) AND
          (winner_id IS NOT NULL OR lower(coalesce(result_type,'')) IN ('tie','tied','draw','drawn'))
        ORDER BY start_date
    """), {"formats": formats}).scalars().all()
    if len(rows) < 10:
        raise RuntimeError(f"Only {len(rows)} distinct labeled match dates for {formats}")
    validation_index = max(2, int(len(rows) * .85))
    return (rows[max(1, int(len(rows) * .70)) - 1], rows[validation_index - 1],
            rows[min(validation_index, len(rows) - 1)])


def _iter_matches(db: Session, formats: list[str], match_ids=None):
    # Keep the server-side read cursor on its own connection so checkpoint commits
    # on the writer session do not invalidate the stream.
    sql, params = MATCH_SQL, {"formats": formats}
    if match_ids is not None:
        sql, params = MATCH_SUBSET_SQL, {"formats": formats, "match_ids": list(match_ids)}
    with db.get_bind().connect() as connection:
        result = connection.execution_options(stream_results=True, yield_per=12000).execute(sql, params)
        current_id, buffer = None, []
        try:
            for row in result:
                record = row._mapping
                if current_id is not None and record["match_id"] != current_id:
                    yield buffer
                    buffer = []
                current_id = record["match_id"]
                buffer.append(record)
            if buffer:
                yield buffer
        finally:
            result.close()


def _walk_match(records, family, collect_training=False):
    """Make pre-delivery train states and/or all pre/post delivery states for a match."""
    first = records[0]
    label = result_label(first["result_type"], first["winner_id"], first["team1_id"])
    training = []
    delivery_states = []
    totals = defaultdict(int)
    innings_state = {}
    prior_by_team = defaultdict(int)
    previous_innings = None
    for row in records:
        inn_id = row["innings_id"]
        if inn_id != previous_innings:
            if previous_innings is not None:
                finished = innings_state[previous_innings]
                if not finished["is_super_over"] and finished["batting_team_id"]:
                    prior_by_team[finished["batting_team_id"]] += finished["runs"]
            innings_state.setdefault(inn_id, {
                "runs": 0, "wickets": 0, "legal": 0,
                "recent": deque(),
                "batting_team_id": row["batting_team_id"],
                "is_super_over": bool(row["is_super_over"]),
            })
            previous_innings = inn_id
        state = innings_state[inn_id]
        batting_id = row["batting_team_id"]
        team1_batting = batting_id == first["team1_id"]
        batting_prior = prior_by_team[batting_id] if batting_id else 0
        opposition_prior = prior_by_team[first["team2_id"] if team1_batting else first["team1_id"]]
        recent_runs = sum(item[0] for item in state["recent"])
        recent_wickets = sum(item[1] for item in state["recent"])
        common = dict(
            match_format=first["match_format"], gender=first["gender"],
            team1_batting=team1_batting, is_super_over=bool(row["is_super_over"]),
            innings_number=int(row["innings_number"]), innings_runs=state["runs"],
            wickets_lost=state["wickets"], legal_balls=state["legal"],
            batting_team_prior_runs=batting_prior, opposition_prior_runs=opposition_prior,
            target_runs=row["target_runs"], target_overs=row["target_overs"],
            recent_runs=recent_runs, recent_wickets=recent_wickets,
        )
        pre = match_state_features(family, **common)
        if collect_training and label is not None and (
            state["legal"] == 0 or state["legal"] % 12 == 0 or row["wickets"] > 0
        ):
            training.append(pre)

        state["runs"] += int(row["total_runs"] or 0)
        state["wickets"] += int(row["wickets"] or 0)
        state["legal"] += int(bool(row["is_legal_ball"]))
        state["recent"].append((int(row["total_runs"] or 0), int(row["wickets"] or 0), int(bool(row["is_legal_ball"]))))
        while sum(item[2] for item in state["recent"]) > 12:
            state["recent"].popleft()
        post_common = dict(common)
        post_common.update(innings_runs=state["runs"], wickets_lost=state["wickets"], legal_balls=state["legal"])
        post = match_state_features(family, **post_common)
        delivery_states.append((pre, post, row, team1_batting))

    if previous_innings is not None:
        finished = innings_state[previous_innings]
        if not finished["is_super_over"] and finished["batting_team_id"]:
            prior_by_team[finished["batting_team_id"]] += finished["runs"]
    return label, training, delivery_states


def _benchmark(db, family, formats, train_cut, valid_cut, test_start, report):
    training_x, training_y, training_w = [], [], []
    validation_x, validation_y, validation_w = [], [], []
    heldout_x, heldout_y, heldout_w = [], [], []
    labeled_matches = defaultdict(int)
    delivery_total = 0
    for records in _iter_matches(db, formats):
        first = records[0]
        delivery_total += len(records)
        label, states, _ = _walk_match(records, family, collect_training=True)
        if label is None:
            continue
        labeled_matches["all"] += 1
        if not states:
            continue
        weight = 1.0 / len(states)
        if first["start_date"] <= train_cut:
            dest = (training_x, training_y, training_w)
        elif first["start_date"] <= valid_cut:
            dest = (validation_x, validation_y, validation_w)
        else:
            dest = (heldout_x, heldout_y, heldout_w)
        dest[0].append(_matrix(states, family))
        dest[1].extend([label] * len(states))
        dest[2].extend([weight] * len(states))
        labeled_matches["train" if first["start_date"] <= train_cut else "validation" if first["start_date"] <= valid_cut else "test"] += 1

    if len(set(training_y)) < 3 or not validation_y or not heldout_y:
        raise RuntimeError(f"{family} needs all three outcomes in training and non-empty chronological validation/test splits")
    train_x, valid_x, test_x = np.concatenate(training_x), np.concatenate(validation_x), np.concatenate(heldout_x)
    train_y, valid_y, test_y = np.asarray(training_y), np.asarray(validation_y), np.asarray(heldout_y)
    train_w, valid_w, test_w = np.asarray(training_w), np.asarray(validation_w), np.asarray(heldout_w)
    candidate_factories = {"LogisticRegression": _pipeline}
    available = {}
    try:
        from lightgbm import LGBMClassifier
        candidate_factories["LightGBM"] = lambda: Pipeline([
            ("imputer", SimpleImputer(strategy="median", add_indicator=True)),
            ("classifier", LGBMClassifier(objective="multiclass", num_class=3, n_estimators=250,
                                           learning_rate=.05, max_depth=-1, random_state=29, verbosity=-1)),
        ])
        available["LightGBM"] = "available"
    except ImportError:
        available["LightGBM"] = "not installed"
    try:
        from xgboost import XGBClassifier
        candidate_factories["XGBoost"] = lambda: Pipeline([
            ("imputer", SimpleImputer(strategy="median", add_indicator=True)),
            ("classifier", XGBClassifier(objective="multi:softprob", num_class=3, n_estimators=250,
                                          max_depth=6, learning_rate=.05, subsample=.85, colsample_bytree=.85,
                                          n_jobs=-1, random_state=29, eval_metric="mlogloss")),
        ])
        available["XGBoost"] = "available"
    except ImportError:
        available["XGBoost"] = "not installed"
    for name, factory in candidate_factories.items():
        model = factory()
        final_name = "classifier" if name != "LogisticRegression" else "classifier"
        model.fit(train_x, train_y, **{f"{final_name}__sample_weight": train_w})
        probs = _predict_three(model, valid_x)
        metrics = multiclass_metrics(valid_y, probs)
        metrics["validation_match_weighted_log_loss"] = float(
            np.average(-np.log(np.clip(probs[np.arange(len(valid_y)), valid_y], 1e-9, 1)), weights=valid_w)
        )
        report["benchmarks"][name] = {"validation": metrics,
                                      "validation_match_weighted": multiclass_metrics(valid_y, probs, valid_w)}
        available.setdefault(name, "available and evaluated")
    chosen = min(candidate_factories, key=lambda n: report["benchmarks"][n]["validation"]["validation_match_weighted_log_loss"])
    final = candidate_factories[chosen]()
    full_x = np.concatenate([train_x, valid_x])
    full_y = np.concatenate([train_y, valid_y])
    full_w = np.concatenate([train_w, valid_w])
    final.fit(full_x, full_y, classifier__sample_weight=full_w)
    test_probabilities = _predict_three(final, test_x)
    report.update({
        "selected_model": chosen, "candidate_availability": available,
        "chronological_split": {"train_end": str(train_cut), "validation_end": str(valid_cut),
                                "test_start": str(test_start), "matches": dict(labeled_matches)},
        "samples": {"train_states": len(train_y), "validation_states": len(valid_y),
                    "test_states": len(test_y), "test_match_weighted_count": labeled_matches.get("test", 0)},
        "test": multiclass_metrics(test_y, test_probabilities),
        "test_match_weighted": multiclass_metrics(test_y, test_probabilities, test_w),
        "database_delivery_rows_scanned": delivery_total,
    })
    return final


def _precompute_matches(db, family, formats, model, version, existing_versions, match_ids=None):
    saved = 0
    for records in _iter_matches(db, formats, match_ids):
        first = records[0]
        match_id = first["match_id"]
        if existing_versions.get(match_id) == version:
            continue
        label, _, states = _walk_match(records, family)
        if label is None:
            db.merge(MatchWinProbability(
                match_id=match_id, match_format=first["match_format"], format_family=family,
                model_version=version, status="unlabelled_no_result", delivery_count=0,
                predictions_gzip=None, exclusion_reason="Abandoned/no-result or unresolved match outcome.",
            ))
            saved += 1
            if saved % 250 == 0: db.commit()
            continue
        if not states:
            continue
        before_x = _matrix([s[0] for s in states], family)
        after_x = _matrix([s[1] for s in states], family)
        before = _predict_three(model, before_x)
        after = _predict_three(model, after_x)
        packed = []
        for idx, (pre, post, row, team1_batting) in enumerate(states):
            flags = (1 if row["is_boundary_four"] else 0) | (2 if row["is_boundary_six"] else 0) | (4 if row["wickets"] else 0)
            packed.append([
                int(row["innings_number"]), int(row["over_number"] + 1), int(row["delivery_sequence"] + 1),
                row["batter_id"], row["bowler_id"], int(team1_batting),
                *[round(float(v), 6) for v in before[idx]], *[round(float(v), 6) for v in after[idx]],
                int(row["total_runs"] or 0), int(row["wickets"] or 0), flags,
            ])
        blob = gzip.compress(json.dumps(packed, separators=(",", ":")).encode(), compresslevel=6)
        db.merge(MatchWinProbability(
            match_id=match_id, match_format=first["match_format"], format_family=family,
            model_version=version, status="available", delivery_count=len(packed),
            predictions_gzip=blob, exclusion_reason=None,
        ))
        saved += 1
        if saved % 100 == 0: db.commit()
    db.commit()
    return saved


def _rebuild_player_impacts(db, player_ids=None):
    """Rebuild player WPA aggregates; with ``player_ids`` only those players' rows are replaced."""
    wanted = set(player_ids) if player_ids is not None else None
    delete_q = db.query(PlayerWinProbabilityImpact)
    rows = db.query(MatchWinProbability.match_id, MatchWinProbability.match_format, MatchWinProbability.predictions_gzip).filter(
        MatchWinProbability.status == "available", MatchWinProbability.predictions_gzip.isnot(None)
    )
    if wanted is not None:
        if not wanted:
            return 0
        delete_q = delete_q.filter(PlayerWinProbabilityImpact.player_id.in_(wanted))
        player_matches = db.execute(text("""
            SELECT DISTINCT i.match_id FROM match_innings i JOIN deliveries d ON d.innings_id = i.id
            WHERE d.batter_id = ANY(:pids) OR d.bowler_id = ANY(:pids)
        """), {"pids": list(wanted)}).scalars().all()
        rows = rows.filter(MatchWinProbability.match_id.in_(player_matches))
    delete_q.delete(synchronize_session=False)
    rows = rows.yield_per(100)
    totals = defaultdict(lambda: {"matches": set(), "bat": 0.0, "bowl": 0.0, "max_delivery": 0.0, "per_match": defaultdict(float)})
    for match_id, match_format, blob in rows:
        for item in json.loads(gzip.decompress(blob)):
            batter, bowler, team1_batting = item[3], item[4], bool(item[5])
            pre, post = item[6:9], item[9:12]
            delta_team1 = post[0] - pre[0]
            bat_wpa = delta_team1 if team1_batting else -delta_team1
            if batter and (wanted is None or batter in wanted):
                entry = totals[(batter, match_format)]
                entry["matches"].add(match_id)
                entry["bat"] += bat_wpa
                entry["max_delivery"] = max(entry["max_delivery"], abs(bat_wpa))
                entry["per_match"][match_id] += bat_wpa
            if bowler and (wanted is None or bowler in wanted):
                entry = totals[(bowler, match_format)]
                entry["matches"].add(match_id)
                entry["bowl"] -= bat_wpa
                entry["max_delivery"] = max(entry["max_delivery"], abs(bat_wpa))
                entry["per_match"][match_id] -= bat_wpa
    for (player_id, match_format), entry in totals.items():
        peak_match = max(entry["per_match"], key=lambda m: abs(entry["per_match"][m]), default=None)
        db.add(PlayerWinProbabilityImpact(
            player_id=player_id, match_format=match_format, matches=len(entry["matches"]),
            batting_wpa=entry["bat"], bowling_wpa=entry["bowl"],
            peak_delivery_impact=entry["max_delivery"],
            peak_match_id=peak_match,
        ))
        if len(totals) and len(totals) % 10000 == 0: db.flush()
    db.commit()
    return len(totals)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--family", choices=("T20", "ODI", "Test"), help="Rebuild one format family only")
    args = parser.parse_args()
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    db: Session = SessionLocal()
    try:
        prior_report = {}
        existing_report_path = ARTIFACT_DIR / "coverage_and_evaluation.json"
        if args.family and existing_report_path.exists():
            try:
                prior_report = json.loads(existing_report_path.read_text())
            except (OSError, json.JSONDecodeError):
                prior_report = {}
        formats_by_family = {"T20": ["T20", "T20I"], "ODI": ["ODI", "ODM"], "Test": ["Test", "MDM"]}
        if args.family:
            formats_by_family = {args.family: formats_by_family[args.family]}
        coverage = db.execute(text("""
            SELECT m.match_format, count(DISTINCT m.id) matches, count(d.id) deliveries
            FROM matches m LEFT JOIN match_innings i ON i.match_id=m.id
            LEFT JOIN deliveries d ON d.innings_id=i.id
            GROUP BY m.match_format ORDER BY m.match_format
        """)).all()
        all_formats = {"T20": ["T20", "T20I"], "ODI": ["ODI", "ODM"], "Test": ["Test", "MDM"]}
        report = {
            "model_version_prefix": MODEL_VERSION_PREFIX,
            "coverage": {fmt: {"matches": int(matches), "deliveries": int(deliveries)} for fmt, matches, deliveries in coverage},
            "supported_families": list(all_formats), "families": {},
            "unsupported_formats": [{"format": fmt, **counts, "reason": "No format-family feature definition is configured."}
                                    for fmt, counts in {fmt: {"matches": int(matches), "deliveries": int(deliveries)}
                                                        for fmt, matches, deliveries in coverage}.items()
                                    if fmt not in FORMAT_FAMILY],
            "limitations": [
                "Match records do not contain Test declarations, follow-on decisions, scheduled match duration, remaining-time estimates, or sessions; Test features use innings progression and score state only.",
                "DLS revised targets are used only when present in MatchInnings.target_runs/target_overs; revision timestamps are not stored, so historical revisions cannot be replayed exactly.",
                "Matches without a resolved winner or explicit tie/draw are excluded from outcome training and saved as no-result/unlabelled.",
                "Super-over deliveries carry an explicit feature and are included separately; the recorded final match outcome is used as the label.",
                "Historical predictions are retrospective model estimates; calibration is assessed on later-held-out matches, not a claim of future certainty.",
            ],
        }
        report["families"] = {**prior_report.get("families", {}), **report["families"]}
        versions = {}
        for family, formats in formats_by_family.items():
            train_cut, valid_cut, test_start = _split_dates(db, formats)
            family_report = {"formats": formats, "features": list(FEATURES[family]), "benchmarks": {}}
            model = _benchmark(db, family, formats, train_cut, valid_cut, test_start, family_report)
            signature = json.dumps({"family": family, "train_end": str(train_cut), "valid_end": str(valid_cut),
                                    "matches": family_report["chronological_split"]["matches"],
                                    "selected": family_report["selected_model"], "logistic_c": 0.0001,
                                    "feature_names": list(FEATURES[family])}, sort_keys=True)
            version = f"{MODEL_VERSION_PREFIX}-{family.lower()}-{hashlib.sha1(signature.encode()).hexdigest()[:12]}"
            versions[family] = version
            family_report["model_version"] = version
            family_report["feature_preprocessing"] = "Per-family median imputation (missingness indicators), StandardScaler, multinomial LogisticRegression; tree models use imputation without scaling when installed."
            joblib.dump({"model": model, "features": FEATURES[family], "family": family,
                         "version": version, "outcomes": ["team1_win", "team2_win", "draw_or_tie"]},
                        ARTIFACT_DIR / f"{family.lower()}.joblib", compress=3)
            existing = dict(db.query(MatchWinProbability.match_id, MatchWinProbability.model_version).filter(
                MatchWinProbability.format_family == family
            ).all())
            family_report["matches_precomputed_this_run"] = _precompute_matches(
                db, family, formats, model, version, existing
            )
            report["families"][family] = family_report
            db.commit()
        report["player_impact_rows"] = _rebuild_player_impacts(db)
        report["precomputed_match_status"] = dict(db.query(
            MatchWinProbability.status, text("count(*)")
        ).group_by(MatchWinProbability.status).all())
        report["match_status_by_format"] = {
            fmt: {status: int(count) for status, count in db.execute(text(
                "SELECT status, count(*) FROM match_win_probabilities WHERE match_format=:fmt GROUP BY status"
            ), {"fmt": fmt}).all()}
            for fmt, *_ in coverage
        }
        report["outcome_counts_by_format"] = {
            fmt: {result_type or "unresolved": int(count) for result_type, count in db.execute(text(
                "SELECT result_type, count(*) FROM matches WHERE match_format=:fmt GROUP BY result_type"
            ), {"fmt": fmt}).all()}
            for fmt, *_ in coverage
        }
        report["source_metadata_gaps"] = dict(db.execute(text("""
            SELECT count(*) AS matches,
                   count(*) FILTER (WHERE venue_id IS NULL) AS missing_venue,
                   count(*) FILTER (WHERE team1_id IS NULL OR team2_id IS NULL) AS missing_team_identity
            FROM matches
        """)).mappings().one())
        report["total_deliveries_precomputed"] = int(db.execute(text("SELECT coalesce(sum(delivery_count),0) FROM match_win_probabilities")).scalar() or 0)
        report["training_run_scope"] = args.family or "all"
        output = ARTIFACT_DIR / "coverage_and_evaluation.json"
        output.write_text(json.dumps(report, indent=2, default=str))
        markdown = ["# CPI Win Probability Coverage & Evaluation", "", "Generated by the offline training and precomputation job.", "",
                    f"Supported format families: {', '.join(report['supported_families'])}", "",
                    "| Source format | Matches | Deliveries |", "|---|---:|---:|"]
        markdown.extend(f"| {fmt} | {counts['matches']:,} | {counts['deliveries']:,} |" for fmt, counts in report["coverage"].items())
        markdown += ["", f"Precomputed deliveries: {report['total_deliveries_precomputed']:,}", "",
                     f"Matches processed: {sum(report['precomputed_match_status'].values()):,} · probability available: {report['precomputed_match_status'].get('available', 0):,} · no-result/unlabelled: {report['precomputed_match_status'].get('unlabelled_no_result', 0):,}",
                     f"Player-format impact aggregates: {report.get('player_impact_rows', 0):,}", "",
                     "## Held-out chronological evaluation", "",
                     "Each match is split wholly into one chronological partition. Headline metrics weight each match equally across its sampled delivery states; JSON also includes unweighted state metrics and per-outcome calibration bins.", "",
                     "| Family | Model | Test matches | Test states | Brier | Log loss | Accuracy | ROC-AUC OVR |", "|---|---|---:|---:|---:|---:|---:|---:|"]
        for family, item in report["families"].items():
            metric = item["test_match_weighted"]
            markdown.append(f"| {family} | {item['selected_model']} | {item['samples']['test_match_weighted_count']:,} | {metric['samples']:,} | {metric['brier_score']:.4f} | {metric['log_loss']:.4f} | {metric['accuracy']:.4f} | {metric['roc_auc_ovr'] if metric['roc_auc_ovr'] is not None else 'N/A'} |")
        markdown += ["", "## Exclusions and limitations", ""] + [f"- {item}" for item in report["limitations"]]
        markdown += ["", "## Candidate availability", ""]
        for family, item in report["families"].items():
            markdown.append(f"### {family}")
            markdown.extend(f"- {name}: {status}" for name, status in item["candidate_availability"].items())
        (ARTIFACT_DIR / "COVERAGE_REPORT.md").write_text("\n".join(markdown) + "\n")
        print(f"Report: {output}")
        print(f"Precomputed delivery states: {report['total_deliveries_precomputed']:,}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
