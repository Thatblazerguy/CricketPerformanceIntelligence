"""
Background scheduler for Cricsheet synchronisation.

* One worker per database: guarded by a PostgreSQL advisory lock held for the
  worker's lifetime (``WORKER_LOCK_KEY``).
* Schedule state lives in PostgreSQL (``sync_worker_state.next_check_at``,
  ``sync_settings``), so a restarted worker resumes the existing schedule.
* Heartbeat is written every ``heartbeat_seconds`` from a separate thread, so
  it keeps beating during long imports.
* Manual "Sync Now" requests from the API are picked up from
  ``sync_settings.manual_requested_at`` within one tick.
"""
from __future__ import annotations

import logging
import os
import socket
import threading
import time
from datetime import datetime, timedelta
from typing import Callable, Optional

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.ingestion.cricsheet_sync_service import (
    WORKER_LOCK_KEY,
    AdvisoryLock,
    CricsheetSyncService,
    ensure_bootstrap,
    get_sync_settings,
    utcnow,
)
from app.models.models import SyncSource, SyncWorkerState

logger = logging.getLogger("cpi.sync_worker")

# Skip the start-up check if a successful check happened this recently
# (prevents hammering Cricsheet when launchd restarts a crashing worker).
STARTUP_CHECK_MIN_GAP = timedelta(minutes=15)
ALREADY_RUNNING_RETRY = timedelta(minutes=5)
MIN_INTERVAL_HOURS, MAX_INTERVAL_HOURS = 0.25, 168.0


def clamp_interval(hours: float) -> float:
    return max(MIN_INTERVAL_HOURS, min(MAX_INTERVAL_HOURS, float(hours)))


def compute_initial_next_check(db: Session, now: datetime, check_on_start_override: Optional[bool] = None) -> Optional[datetime]:
    """Decide when the first check happens after (re)start, honouring the persisted schedule."""
    cfg = get_sync_settings(db)
    if not cfg.auto_sync_enabled:
        return None
    interval = timedelta(hours=clamp_interval(cfg.interval_hours))
    state = db.get(SyncWorkerState, 1)
    last_check = db.execute(select(SyncSource.last_checked_at).where(SyncSource.enabled.is_(True))
                            .order_by(SyncSource.last_checked_at.desc().nullslast()).limit(1)).scalar()
    check_on_start = cfg.check_on_start if check_on_start_override is None else check_on_start_override
    if check_on_start and (last_check is None or now - last_check >= STARTUP_CHECK_MIN_GAP):
        return now
    if state is not None and state.next_check_at is not None:
        return min(state.next_check_at, (last_check or now) + interval)
    return (last_check + interval) if last_check else now


class SyncWorker:
    def __init__(
        self,
        session_factory: Callable[[], Session],
        engine: Engine,
        service_factory: Optional[Callable[[threading.Event], CricsheetSyncService]] = None,
        tick_seconds: float = 5.0,
        heartbeat_seconds: float = 30.0,
        heartbeat_log_every: int = 60,          # log a heartbeat line every N beats (30 min at 30s)
        check_on_start: Optional[bool] = None,  # None = use sync_settings.check_on_start
        clock: Callable[[], datetime] = utcnow,
    ):
        self.session_factory = session_factory
        self.engine = engine
        self.stop_event = threading.Event()
        self.service_factory = service_factory or (
            lambda stop: CricsheetSyncService(session_factory=session_factory, engine=engine, stop_event=stop))
        self.tick_seconds = tick_seconds
        self.heartbeat_seconds = heartbeat_seconds
        self.heartbeat_log_every = heartbeat_log_every
        self.check_on_start = check_on_start
        self.clock = clock
        self.instance_lock = AdvisoryLock(engine, WORKER_LOCK_KEY)
        self.next_check_at: Optional[datetime] = None
        self._settings_seen: Optional[datetime] = None
        self._state = "idle"
        self._hb_thread: Optional[threading.Thread] = None

    # --------------------------------------------------------------- lifecycle

    def start(self) -> bool:
        """Acquire the single-instance lock and register. Returns False if another worker owns it."""
        if not self.instance_lock.acquire():
            return False
        now = self.clock()
        with self.session_factory() as db:
            ensure_bootstrap(db)
            st = db.get(SyncWorkerState, 1)
            st.state, st.pid, st.hostname = "idle", os.getpid(), socket.gethostname()
            st.started_at = st.heartbeat_at = now
            st.last_error = None
            self.next_check_at = compute_initial_next_check(db, now, self.check_on_start)
            st.next_check_at = self.next_check_at
            self._settings_seen = get_sync_settings(db).updated_at
            db.commit()
            logger.info("Worker started pid=%s; last success=%s; next check=%s",
                        os.getpid(), st.last_success_at, self.next_check_at)
        self._hb_thread = threading.Thread(target=self._heartbeat_loop, name="sync-heartbeat", daemon=True)
        self._hb_thread.start()
        return True

    def stop(self) -> None:
        self.stop_event.set()

    def shutdown(self) -> None:
        self.stop_event.set()
        try:
            with self.session_factory() as db:
                st = db.get(SyncWorkerState, 1)
                if st is not None and st.pid == os.getpid():
                    st.state = "stopped"
                    st.heartbeat_at = self.clock()
                    db.commit()
        except Exception:
            logger.warning("Could not record worker shutdown", exc_info=True)
        self.instance_lock.release()
        logger.info("Worker stopped")

    def run_forever(self) -> None:
        try:
            while not self.stop_event.is_set():
                try:
                    self.tick()
                except Exception as exc:  # DB hiccup etc: log, back off, keep going
                    logger.exception("Worker tick failed: %s", exc)
                    self._record_error(str(exc))
                    self.stop_event.wait(min(60.0, self.tick_seconds * 6))
                    continue
                self.stop_event.wait(self.tick_seconds)
        finally:
            self.shutdown()

    # --------------------------------------------------------------- scheduling

    def tick(self) -> Optional[dict]:
        """One scheduler step. Returns the sync result if a sync ran."""
        if not self.instance_lock.is_alive():
            # The lock died with its connection (e.g. PostgreSQL restart). Re-acquire or yield.
            self.instance_lock.release()
            if not self.instance_lock.acquire():
                logger.error("Lost the worker lock to another worker instance; stopping")
                self.stop_event.set()
                return None
        now = self.clock()
        trigger = None
        with self.session_factory() as db:
            cfg = get_sync_settings(db)
            interval = timedelta(hours=clamp_interval(cfg.interval_hours))
            if cfg.updated_at != self._settings_seen:
                self._settings_seen = cfg.updated_at
                last_check = db.execute(select(SyncSource.last_checked_at)
                                        .order_by(SyncSource.last_checked_at.desc().nullslast()).limit(1)).scalar()
                self.next_check_at = (max(now, (last_check or now) + interval) if cfg.auto_sync_enabled else None)
                logger.info("Settings changed: auto=%s interval=%sh -> next check %s",
                            cfg.auto_sync_enabled, cfg.interval_hours, self.next_check_at)
            if cfg.manual_requested_at is not None:
                cfg.manual_requested_at = None  # consume the request
                trigger = "manual"
            elif cfg.auto_sync_enabled:
                if self.next_check_at is None:
                    self.next_check_at = now + interval
                if now >= self.next_check_at:
                    trigger = "scheduler"
            else:
                self.next_check_at = None
            st = db.get(SyncWorkerState, 1)
            st.next_check_at = self.next_check_at
            db.commit()

        if trigger is None:
            return None
        return self._run(trigger, interval)

    def _run(self, trigger: str, interval: timedelta) -> dict:
        self._set_state("syncing")
        try:
            result = self.service_factory(self.stop_event).run_sync(triggered_by=trigger)
        except Exception as exc:
            logger.exception("Sync run crashed: %s", exc)
            self._record_error(str(exc))
            result = {"status": "failed", "error": str(exc)}
        finally:
            self._set_state("idle")
        now = self.clock()
        if result.get("status") == "already_running":
            self.next_check_at = now + ALREADY_RUNNING_RETRY
        else:
            with self.session_factory() as db:
                auto = get_sync_settings(db).auto_sync_enabled
            self.next_check_at = now + interval if auto else None
        with self.session_factory() as db:
            st = db.get(SyncWorkerState, 1)
            st.next_check_at = self.next_check_at
            if result.get("status") in ("completed", "no_changes"):
                st.last_error = None
            elif result.get("status") != "already_running":
                st.last_error = f"Last sync status: {result.get('status')}"
            db.commit()
        logger.info("Sync (%s) -> %s; next check %s", trigger, result.get("status"), self.next_check_at)
        return result

    # --------------------------------------------------------------- heartbeat

    def _set_state(self, state: str) -> None:
        self._state = state
        with self.session_factory() as db:
            st = db.get(SyncWorkerState, 1)
            st.state, st.heartbeat_at = state, self.clock()
            db.commit()

    def beat(self) -> None:
        with self.session_factory() as db:
            st = db.get(SyncWorkerState, 1)
            st.heartbeat_at = self.clock()
            st.state = self._state
            st.pid = os.getpid()
            db.commit()

    def _heartbeat_loop(self) -> None:
        beats = 0
        while not self.stop_event.wait(self.heartbeat_seconds):
            try:
                self.beat()
                beats += 1
                if beats % self.heartbeat_log_every == 0:
                    with self.session_factory() as db:
                        st = db.get(SyncWorkerState, 1)
                        logger.info("Heartbeat: state=%s last_success=%s next_check=%s",
                                    st.state, st.last_success_at, st.next_check_at)
            except Exception:
                logger.warning("Heartbeat write failed", exc_info=True)

    def _record_error(self, message: str) -> None:
        try:
            with self.session_factory() as db:
                st = db.get(SyncWorkerState, 1)
                st.last_error = message[:2000]
                db.commit()
        except Exception:
            pass
