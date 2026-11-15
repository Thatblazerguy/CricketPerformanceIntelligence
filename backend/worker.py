#!/usr/bin/env python3
"""
CPI Cricsheet synchronisation worker.

Runs independently of the API and browser. Checks Cricsheet on the interval
stored in PostgreSQL (default 6h, editable in Settings -> Data Management).

  cd backend
  .venv/bin/python worker.py              # run forever (normal mode)
  .venv/bin/python worker.py --once       # one sync cycle, then exit
  .venv/bin/python worker.py --status     # print sync/worker status JSON
  .venv/bin/python worker.py --no-initial-check

Logs: backend/logs/sync_worker.log (rotated).
"""
from __future__ import annotations

import argparse
import json
import logging
import logging.handlers
import signal
import sys
import time
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

LOG_DIR = BACKEND_DIR / "logs"


def _configure_logging(level: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    fh = logging.handlers.RotatingFileHandler(LOG_DIR / "sync_worker.log", maxBytes=5 * 1024 * 1024, backupCount=5)
    fh.setFormatter(fmt)
    root.addHandler(fh)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    root.addHandler(sh)
    logging.getLogger("httpx").setLevel(logging.WARNING)


def _wait_for_database(engine, log) -> None:
    """At login launchd may start us before PostgreSQL is accepting connections."""
    from sqlalchemy import text
    delay = 5
    while True:
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return
        except Exception as exc:
            log.warning("Database unavailable (%s); retrying in %ss", exc.__class__.__name__, delay)
            time.sleep(delay)
            delay = min(delay * 2, 120)


def main() -> int:
    parser = argparse.ArgumentParser(description="CPI Cricsheet sync worker")
    parser.add_argument("--once", action="store_true", help="Run one sync cycle and exit")
    parser.add_argument("--status", action="store_true", help="Print status JSON and exit")
    parser.add_argument("--no-initial-check", action="store_true", help="Do not check immediately on start")
    parser.add_argument("--initial-check", action="store_true", help="Always check immediately on start")
    parser.add_argument("--tick", type=float, default=5.0, help="Scheduler poll seconds (default 5)")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    _configure_logging(args.log_level)
    log = logging.getLogger("cpi.sync_worker")

    from app.db.session import SessionLocal, engine
    from app.ingestion.cricsheet_sync_service import CricsheetSyncService, build_status
    from app.ingestion.sync_worker import SyncWorker

    if args.status:
        with SessionLocal() as db:
            print(json.dumps(build_status(db, engine), indent=2, default=str))
        return 0

    _wait_for_database(engine, log)

    if args.once:
        import threading
        stop = threading.Event()
        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, lambda *_: stop.set())
        result = CricsheetSyncService(session_factory=SessionLocal, engine=engine,
                                      stop_event=stop).run_sync(triggered_by="manual")
        print(json.dumps(result, indent=2, default=str))
        return 0 if result.get("status") in ("completed", "no_changes") else 1

    check_on_start = False if args.no_initial_check else (True if args.initial_check else None)
    worker = SyncWorker(SessionLocal, engine, tick_seconds=args.tick, check_on_start=check_on_start)

    def _on_signal(signum, _frame):
        log.info("Received %s; stopping after the current match", signal.Signals(signum).name)
        worker.stop()

    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)

    if not worker.start():
        log.info("Another CPI sync worker is already running for this database; exiting")
        return 0
    worker.run_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
