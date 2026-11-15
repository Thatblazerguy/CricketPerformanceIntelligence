"""(Re)build the scouting per-innings aggregates from deliveries.

    PYTHONPATH=backend backend/.venv/bin/python backend/scripts/build_scouting_aggregates.py [FORMAT ...]

With no arguments every format is rebuilt. Incremental refreshes after imports
happen automatically through ``app.ingestion.dependent_refresh``.
"""
import logging
import sys
import time

from app.analytics.scouting_aggregates import ALL_FORMATS, rebuild_all
from app.db.session import SessionLocal


def main(argv):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    formats = argv or list(ALL_FORMATS)
    db = SessionLocal()
    try:
        started = time.time()
        summary = rebuild_all(db, formats)
        for fmt, counts in summary.items():
            print(f"{fmt:5s} batting innings={counts['bat']:>8,} style rows={counts['style']:>8,} bowling innings={counts['bowl']:>8,}")
        print(f"done in {time.time() - started:.0f}s")
    finally:
        db.close()


if __name__ == "__main__":
    main(sys.argv[1:])
