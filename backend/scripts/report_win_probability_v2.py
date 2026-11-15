"""Render ``artifacts/win_probability/v2/REPORT.md`` from ``evaluation.json``.

Run from backend/: ``.venv/bin/python scripts/report_win_probability_v2.py``
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts" / "win_probability" / "v2"
ROWS = [("model", "**v2 model (calibrated, deployed)**"), ("model_uncalibrated", "v2 model, uncalibrated"),
        ("model_sigmoid", "v2 + Platt/sigmoid"), ("model_isotonic", "v2 + isotonic"),
        ("best_logistic", "best logistic regression (new features)"),
        ("legacy_v1_logistic", "legacy v1 logistic (C=1e-4, team1 features)"),
        ("venue_par", "venue-par baseline"), ("elo", "Elo-only baseline"), ("prior", "constant prior")]


def ci(m, key):
    c = m.get("ci95", {}).get(key)
    return f" [{c['low']:.3f}, {c['high']:.3f}]" if c else ""


def metric_table(ev: dict, multi: bool) -> list:
    head = "| Model | Log loss [95% CI] | Brier [95% CI] | " + ("RPS | " if multi else "") + \
           "ECE | Skill vs prior [95% CI] | Skill vs Elo | Skill vs venue-par |"
    lines = [head, "|" + "---|" * (head.count("|") - 1)]
    for key, label in ROWS:
        m = ev.get(key)
        if not m:
            continue
        def skill(base):
            if f"skill_vs_{base}" not in m:
                return "—"
            return f"{m[f'skill_vs_{base}']:+.3f}" + (ci(m, f"skill_vs_{base}") if base == "prior" else "")
        lines.append(f"| {label} | {m['log_loss']:.4f}{ci(m, 'log_loss')} | {m['brier']:.4f}{ci(m, 'brier')} | "
                     + (f"{m['rps']:.4f} | " if multi else "") + f"{m['ece']:.4f} | {skill('prior')} | {skill('elo')} | {skill('venue_par')} |")
    return lines


def segment_tables(segments: dict) -> list:
    out = []
    for name, rows in segments.items():
        if not rows:
            continue
        out += [f"*{name.replace('_', ' ')}*", "",
                "| Segment | States | v2 log loss | v2 Brier | Prior LL | Elo LL | Venue-par LL | Legacy v1 LL | Skill vs prior | Skill vs Elo | Skill vs venue-par |",
                "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
        for r in rows:
            out.append(f"| {r['segment']} | {r['states']:,} | {r['model_log_loss']:.4f} | {r['model_brier']:.4f} | "
                       f"{r['prior_log_loss']:.4f} | {r['elo_log_loss']:.4f} | {r['venue_par_log_loss']:.4f} | "
                       f"{r['legacy_v1_logistic_log_loss']:.4f} | {r['skill_vs_prior']:+.3f} | {r['skill_vs_elo']:+.3f} | "
                       f"{r['skill_vs_venue_par']:+.3f} |")
        out.append("")
    return out


def selection_table(sel: dict) -> list:
    lines = ["| Candidate | Validation log loss | Validation Brier |", "|---|---:|---:|"]
    for name, r in sel["candidates"].items():
        if "error" in r:
            lines.append(f"| {name} | not supported: {r['error'][:90]} | |")
        else:
            mark = " ✅" if name == sel["selected"] else ""
            lines.append(f"| {name}{mark} | {r['validation_log_loss']:.4f} | {r['validation_brier']:.4f} |")
    cv = ", ".join(f"{k} {v:.4f}" for k, v in sel["calibration_cv_log_loss"].items())
    lines += ["", f"Calibration chosen by match-grouped 4-fold CV inside the calibration partition: **{sel['calibration_method']}** ({cv})."]
    return lines


def main():
    report = json.loads((OUT / "evaluation.json").read_text())
    md = ["# CPI Win Probability v2 — Evaluation Report", "",
          f"Generated {report['generated']} · data fingerprint `{report['data_fingerprint']}` · "
          f"partitions (by match date): " + ", ".join(f"{k} {v:.0%}" for k, v in report["partitions"].items()), "",
          "All numbers are on the **held-out test partition** (the most recent 15% of labelled matches), which was not "
          "used for feature construction, model selection or calibration. Metrics weight every match-innings equally "
          "(limited overs) or every match equally (multi-day). CIs are 95% match-level bootstrap intervals. "
          "Skill = 1 − model log loss / baseline log loss.", ""]
    md += ["## Summary", "", "| Group | Test matches | v2 log loss | Legacy v1 | Elo-only | Venue-par | Prior | Skill vs prior | v2 Brier |",
           "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for group, g in report["groups"].items():
        ev = g["evaluation"].get("overall") or g["evaluation"]["all"]["overall"]
        md.append(f"| {group} | {g['splits']['test']['matches']:,} | {ev['model']['log_loss']:.4f} | "
                  f"{ev['legacy_v1_logistic']['log_loss']:.4f} | {ev['elo']['log_loss']:.4f} | {ev['venue_par']['log_loss']:.4f} | "
                  f"{ev['prior']['log_loss']:.4f} | {ev['model']['skill_vs_prior']:+.3f} | {ev['model']['brier']:.4f} |")
    md.append("")
    for group, g in report["groups"].items():
        multi = "all" in g["evaluation"]
        md += [f"## {group} ({', '.join(g['formats'])})", ""]
        md += ["| Partition | From | To | Matches |", "|---|---|---|---:|"]
        for p in ("train", "validation", "calibration", "test"):
            s = g["splits"][p]
            md.append(f"| {p} | {s['from']} | {s['to']} | {s['matches']:,} |")
        md += ["", f"Unlabelled (excluded from training/evaluation): {g['splits']['unlabelled']['matches']:,} matches "
                   f"({g['splits']['unlabelled']['reason']}).", "",
               "State audit: " + ", ".join(f"{k.replace('_', ' ')} {v:,}" for k, v in g["audit"].items()), ""]
        if multi:
            ev = g["evaluation"]["all"]
            md += ["### Test partition (three-class: batting win / bowling win / draw)", ""] + metric_table(ev["overall"], True)
            md += ["", "Per-class calibration error (ECE) of the deployed model: " +
                   ", ".join(f"{k} {v:.4f}" for k, v in ev["overall"]["model"]["ece_by_class"].items()), ""]
            md += [f"Calibration plots: " + ", ".join(f"[{c}](plots/{group.lower()}_{c}.svg)"
                                                    for c in ("batting_win", "bowling_win", "draw")), ""]
            md += ["### Segments (test partition)", ""] + segment_tables(ev["segments"])
            md += ["### Model selection (validation partition)", ""] + selection_table(ev["selection"]) + [""]
        else:
            md += ["### Test partition, both innings", ""] + metric_table(g["evaluation"]["overall"], False) + [""]
            for inn in ("1", "2"):
                ev = g["evaluation"][inn]
                md += [f"### Innings {inn}", "", f"Calibration plot: [plots/{group.lower()}_innings{inn}.svg](plots/{group.lower()}_innings{inn}.svg)", ""]
                md += metric_table(ev, False) + [""]
                if "by_source_format" in ev:
                    md += ["By source format:", "", "| Format | States | v2 LL | Legacy v1 LL | Prior LL | Skill vs prior |", "|---|---:|---:|---:|---:|---:|"]
                    for fmt, e in ev["by_source_format"].items():
                        md.append(f"| {fmt} | {e['model']['states']:,} | {e['model']['log_loss']:.4f} | "
                                  f"{e['legacy_v1_logistic']['log_loss']:.4f} | {e['prior']['log_loss']:.4f} | {e['model']['skill_vs_prior']:+.3f} |")
                    md.append("")
                md += ["#### Segments", ""] + segment_tables(ev["segments"])
                md += ["#### Model selection (validation partition)", ""] + selection_table(ev["selection"]) + [""]
            if "resource_table_preview" in g:
                md += ["### Resource table (expected runs remaining, training first innings)", "",
                       "| Balls remaining | 0 down | 2 down | 4 down | 6 down | 8 down |", "|---:|---:|---:|---:|---:|---:|"]
                for k, row in g["resource_table_preview"].items():
                    md.append(f"| {k.split('_')[0]} | " + " | ".join(f"{v:.1f}" for v in row.values()) + " |")
                md.append("")
    (OUT / "REPORT.md").write_text("\n".join(md) + "\n")
    print(f"wrote {OUT / 'REPORT.md'}")


if __name__ == "__main__":
    main()
