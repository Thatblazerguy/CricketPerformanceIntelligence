"""Build (or rebuild) the match simulator's format calibrations from CPI deliveries.

Run from backend/: ``.venv/bin/python scripts/train_match_simulator.py [T20 ODI Test]``

Each family scans its modern-era deliveries once (roughly 30-70 seconds) and
writes ``artifacts/simulator/calibration_<family>.json``: baseline outcome
counts by innings / over bucket / wickets lost, chase-pressure bands, league
references by phase, bowling type and season, batting-position priors, extras
and run-out distributions, dismissal mixes and toss tendencies. Player and
venue rates are not stored here; they are read per request so new matches from
the sync worker are reflected immediately. The API builds a missing
calibration on first use, so running this is optional; rerun it periodically
(e.g. after a season) to refresh the baselines.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.session import SessionLocal  # noqa: E402
from app.ml import sim_calibration as cal  # noqa: E402


def main(families):
    db = SessionLocal()
    try:
        for family in families:
            if family not in cal.FAMILY_FORMATS:
                raise SystemExit(f"Unknown family {family!r}; use T20, ODI or Test")
            started = time.time()
            data = cal.build_format_calibration(db, family)
            cal.ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
            path = cal.calibration_path(family)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, separators=(",", ":")))
            tmp.replace(path)
            cal._CAL_CACHE.pop(family, None)
            summary = {g: {"deliveries": v["deliveries"], "historical_innings": v["innings_totals"]} for g, v in data["genders"].items()}
            print(json.dumps({"family": family, "path": str(path), "seconds": round(time.time() - started, 1), "genders": summary}, indent=2))
    finally:
        db.close()


if __name__ == "__main__":
    main(sys.argv[1:] or ["T20", "ODI", "Test"])
