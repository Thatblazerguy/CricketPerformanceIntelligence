"""(Re)build the per-innings team summary used by Team and Venue Analytics.

    PYTHONPATH=backend backend/.venv/bin/python backend/scripts/build_team_innings_summary.py [FORMAT ...]

With no arguments every format is rebuilt. Incremental refreshes after imports
happen automatically through ``app.ingestion.dependent_refresh``.
"""
import logging
import sys
import time

from app.analytics.team_innings_aggregates import ALL_FORMATS, rebuild_all
from app.db.session import SessionLocal


def main(argv):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    db = SessionLocal()
    try:
        started = time.time()
        for fmt, n in rebuild_all(db, argv or list(ALL_FORMATS)).items():
            print(f"{fmt:5s} innings={n:>8,}")
        print(f"done in {time.time() - started:.0f}s")
    finally:
        db.close()


if __name__ == "__main__":
    main(sys.argv[1:])
