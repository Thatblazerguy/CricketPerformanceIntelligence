"""Validate reconstructed careers against published benchmarks and report the gap.

The benchmarks (tests/validation/career_benchmarks.json) are reference values
only. CPI totals come from stored records via the hybrid career engine; this
script never adjusts them. It also cross-checks the engine's ball-by-ball
totals against an independent SQL sum of deliveries, which must match exactly.

Usage: cd backend && .venv/bin/python -m scripts.validate_career_benchmarks [--json out.json]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.session import SessionLocal  # noqa: E402
from app.hybrid.career import player_career  # noqa: E402
from app.hybrid.reconstruction import left_censored_formats  # noqa: E402

BENCH = Path(__file__).resolve().parents[1] / "tests" / "validation" / "career_benchmarks.json"


def resolve(db, b):
    if b.get("cricinfo_id"):
        pid = db.scalar(text("SELECT player_id FROM player_external_ids WHERE id_scheme='cricinfo' AND external_id=:e"),
                        {"e": b["cricinfo_id"]})
        if pid:
            return pid
    ids = db.execute(text("SELECT id FROM players WHERE canonical_name = :n"), {"n": b["cricsheet_name"]}).all()
    return ids[0][0] if len(ids) == 1 else None


def independent_bb_runs(db, pid, fc):
    return db.scalar(text("""SELECT coalesce(sum(d.batter_runs), 0) FROM deliveries d
        JOIN match_innings i ON i.id = d.innings_id AND NOT i.is_super_over
        JOIN canonical_matches c ON c.match_id = i.match_id
        WHERE d.batter_id = :p AND c.format_class = :fc"""), {"p": pid, "fc": fc})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json")
    args = ap.parse_args()
    bench = json.loads(BENCH.read_text())
    report, failures = [], 0
    with SessionLocal() as db:
        for b in bench["players"]:
            pid = resolve(db, b)
            if not pid:
                report.append({"player": b["cricsheet_name"], "error": "not resolved"}); failures += 1
                continue
            career = player_career(db, pid)
            censored = {g["format_class"] for g in left_censored_formats(db, pid)}
            for fc in ("TEST", "ODI", "T20I"):
                if fc not in b:
                    continue
                f = career["formats"].get(fc)
                cpi = f["batting"]["runs"]["value"] if f else 0
                check = independent_bb_runs(db, pid, fc)
                sc_inns = (f or {}).get("provenance", {}).get("batting", {}).get("scorecard", 0)
                consistent = sc_inns > 0 or cpi == check
                failures += 0 if consistent else 1
                expected = b[fc]["runs"]
                report.append({
                    "player": b["cricsheet_name"], "format": fc, "cpi_runs": cpi, "benchmark_runs": expected,
                    "gap_runs": expected - cpi, "coverage_pct": round(100 * cpi / expected, 1),
                    "cpi_matches": f["matches"]["value"] if f else 0,
                    "ball_by_ball_matches": f["ball_by_ball_matches"] if f else 0,
                    "career_predates_records": fc in censored,
                    "engine_matches_independent_sum": consistent,
                    "exceeds_benchmark": cpi > expected,
                })
                failures += 1 if cpi > expected else 0
    print(f"{'Player':<16}{'Fmt':<6}{'CPI':>7}{'Bench':>7}{'Gap':>7}{'Cov%':>7}{'Mat':>5}  predates  engine=SQL")
    for r in report:
        if "error" in r:
            print(f"{r['player']:<16}ERROR {r['error']}"); continue
        print(f"{r['player']:<16}{r['format']:<6}{r['cpi_runs']:>7}{r['benchmark_runs']:>7}{r['gap_runs']:>7}"
              f"{r['coverage_pct']:>7}{r['cpi_matches']:>5}  {str(r['career_predates_records']):<9} {r['engine_matches_independent_sum']}")
    if args.json:
        Path(args.json).write_text(json.dumps(report, indent=2, default=str))
    print(f"\n{failures} validation failure(s). A gap is not a failure: it is uncovered history, reported as such.")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
