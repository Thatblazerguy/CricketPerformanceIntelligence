"""Precompute historical v2 win-probability curves and rebuild player WPA aggregates.

Run from backend/ after ``scripts/train_win_probability_v2.py``::

    .venv/bin/python scripts/precompute_win_probability_v2.py [--groups T20 ODI ...] [--skip-impacts]

Deterministic: the same database snapshot and model bundles always produce the same curves.
"""
from __future__ import annotations

import argparse
import sys
import time
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
warnings.filterwarnings("ignore", message=".*encountered in matmul", category=RuntimeWarning)

from app.db.session import SessionLocal  # noqa: E402
from app.ml.wp.constants import GROUPS  # noqa: E402
from app.ml.wp.precompute import precompute  # noqa: E402

CACHE = ROOT / "artifacts" / "win_probability" / "cache"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--groups", nargs="*", default=list(GROUPS))
    parser.add_argument("--skip-impacts", action="store_true")
    args = parser.parse_args()
    db = SessionLocal()
    try:
        for group in args.groups:
            t0 = time.time()
            done = precompute(db, [group], cache_dir=CACHE)
            print(f"{group}: {done.get(group, 0):,} matches in {time.time() - t0:.0f}s", flush=True)
        if not args.skip_impacts:
            from scripts.build_win_probability import _rebuild_player_impacts
            print(f"player impact rows: {_rebuild_player_impacts(db):,}", flush=True)
    finally:
        db.close()


if __name__ == "__main__":
    main()
