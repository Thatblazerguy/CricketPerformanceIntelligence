"""Add held-out evaluations for each original source format to the coverage report."""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

import numpy as np
import joblib
from sqlalchemy import text
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.db.session import SessionLocal
from app.ml.win_probability import FEATURES, format_family, multiclass_metrics, result_label
from scripts.build_win_probability import ARTIFACT_DIR, _iter_matches, _matrix, _predict_three, _walk_match


def main():
    report_path = ARTIFACT_DIR / "coverage_and_evaluation.json"
    report = json.loads(report_path.read_text())
    grouped = defaultdict(lambda: {"x": [], "y": [], "w": [], "matches": 0, "test_start": None})
    db: Session = SessionLocal()
    try:
        for family_info in report["families"].values():
            family = family_info["formats"]
            family_name = format_family(family[0])
            split_date = date.fromisoformat(family_info["chronological_split"]["validation_end"])
            model_package = joblib.load(ARTIFACT_DIR / f"{family_name.lower()}.joblib")
            for source_format in family:
                for records in _iter_matches(db, [source_format]):
                    first = records[0]
                    if first["start_date"] <= split_date:
                        continue
                    label = result_label(first["result_type"], first["winner_id"], first["team1_id"])
                    if label is None:
                        continue
                    _, _, delivery_states = _walk_match(records, family_name)
                    if not delivery_states:
                        continue
                    states = [item[0] for item in delivery_states]
                    group = grouped[source_format]
                    group["x"].append(_matrix(states, family_name))
                    group["y"].extend([label] * len(states))
                    group["w"].extend([1.0 / len(states)] * len(states))
                    group["matches"] += 1
                    if group["test_start"] is None or first["start_date"] < group["test_start"]:
                        group["test_start"] = first["start_date"]
        output = {}
        for source_format, data in grouped.items():
            family_name = format_family(source_format)
            model = joblib.load(ARTIFACT_DIR / f"{family_name.lower()}.joblib")["model"]
            x, y, weights = np.concatenate(data["x"]), np.asarray(data["y"], dtype=int), np.asarray(data["w"])
            probs = _predict_three(model, x)
            output[source_format] = {
                "format_family": family_name,
                "test_matches": data["matches"],
                "test_states": len(y),
                "test_start": str(data["test_start"]),
                "state_weighted_metrics": multiclass_metrics(y, probs),
                "match_weighted_metrics": multiclass_metrics(y, probs, weights),
                "note": "Uses the family model and the same chronological held-out date boundary; matches remain intact within the held-out set.",
            }
        report["source_format_evaluations"] = output
        report["outcome_counts_by_format"] = {
            fmt: {result_type or "unresolved": int(count) for result_type, count in db.execute(text(
                "SELECT result_type, count(*) FROM matches WHERE match_format=:fmt GROUP BY result_type"
            ), {"fmt": fmt}).all()}
            for fmt in report["coverage"]
        }
        report_path.write_text(json.dumps(report, indent=2, default=str))
        lines = ["", "## Held-out evaluation by source format", "",
                 "These rows apply each family model to its original source formats separately. Metrics are match-weighted; state-level metrics and per-outcome reliability bins are in the JSON report.", "",
                 "| Source format | Model family | Test matches | States | Brier | Log loss | Accuracy | ROC-AUC OVR |", "|---|---|---:|---:|---:|---:|---:|---:|"]
        for source_format, item in output.items():
            m = item["match_weighted_metrics"]
            auc = "N/A" if m["roc_auc_ovr"] is None else f"{m['roc_auc_ovr']:.4f}"
            lines.append(f"| {source_format} | {item['format_family']} | {item['test_matches']:,} | {item['test_states']:,} | {m['brier_score']:.4f} | {m['log_loss']:.4f} | {m['accuracy']:.4f} | {auc} |")
        report_md = ARTIFACT_DIR / "COVERAGE_REPORT.md"
        current_markdown = report_md.read_text()
        if "\n## Held-out evaluation by source format" in current_markdown:
            current_markdown = current_markdown.split("\n## Held-out evaluation by source format", 1)[0]
        report_md.write_text(current_markdown.rstrip() + "\n" + "\n".join(lines) + "\n")
        print({fmt: {"matches": item["test_matches"], "states": item["test_states"],
                     "brier": item["match_weighted_metrics"]["brier_score"],
                     "log_loss": item["match_weighted_metrics"]["log_loss"]}
               for fmt, item in output.items()})
    finally:
        db.close()


if __name__ == "__main__":
    main()
