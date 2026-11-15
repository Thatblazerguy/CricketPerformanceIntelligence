"""
Cricsheet data synchronisation endpoints (Settings -> Data Management).

Mounted at /api/v1/data-sync (CPI convention) and aliased at /api/data-sync.

Manual triggers use the same CricsheetSyncService as the worker. If the worker
is healthy the request is queued for it (picked up within seconds); otherwise
the API runs the service in a background thread. Either way the PostgreSQL
advisory lock guarantees at most one sync at a time.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta
from typing import Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.db.session import SessionLocal, engine, get_db
from app.ingestion.cricsheet_sync_service import (
    CricsheetSyncService,
    advisory_lock_held,
    build_status,
    ensure_bootstrap,
    get_sync_settings,
    history_to_dict,
    utcnow,
    worker_health,
)
from app.ingestion.sync_worker import MAX_INTERVAL_HOURS, MIN_INTERVAL_HOURS
from app.models.models import SyncHistory, SyncSource, SyncWorkerState

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/data-sync")

_api_thread: Optional[threading.Thread] = None
_api_thread_lock = threading.Lock()
# A queued request the worker has not picked up within this window is considered lost.
QUEUE_PICKUP_WINDOW = timedelta(minutes=2)


class SettingsUpdate(BaseModel):
    auto_sync_enabled: Optional[bool] = None
    interval_hours: Optional[float] = Field(None, ge=MIN_INTERVAL_HOURS, le=MAX_INTERVAL_HOURS)
    check_on_start: Optional[bool] = None
    sources: Optional[Dict[str, bool]] = Field(None, description="source_key -> enabled")


@router.get("/status")
def sync_status(db: Session = Depends(get_db)):
    """Data freshness, dataset totals, latest/current sync, schedule and worker health."""
    return build_status(db, engine)


@router.get("/history")
def sync_history(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    source_key: Optional[str] = None,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
):
    q = select(SyncHistory)
    if source_key:
        q = q.where(SyncHistory.source_key == source_key)
    if status:
        q = q.where(SyncHistory.status == status)
    total = db.execute(select(func.count()).select_from(q.subquery())).scalar_one()
    rows = db.execute(q.order_by(SyncHistory.id.desc()).offset((page - 1) * page_size).limit(page_size)).scalars()
    return {
        "items": [history_to_dict(r) for r in rows],
        "total": total, "page": page, "page_size": page_size,
        "pages": max(1, -(-total // page_size)),
    }


def _run_in_api_process() -> None:
    try:
        result = CricsheetSyncService(session_factory=SessionLocal, engine=engine).run_sync(triggered_by="manual")
        logger.info("API-run manual sync finished: %s", result.get("status"))
    except Exception:
        logger.exception("API-run manual sync crashed")


@router.post("/trigger", status_code=202)
def trigger_sync(db: Session = Depends(get_db)):
    """Start a manual sync now (never overlaps a running one)."""
    global _api_thread
    ensure_bootstrap(db)
    if advisory_lock_held(engine):
        return JSONResponse(status_code=409, content={
            "status": "already_running", "message": "A synchronisation is already in progress."})

    cfg = get_sync_settings(db)
    worker = worker_health(db.get(SyncWorkerState, 1))
    now = utcnow()
    if worker["healthy"]:
        if cfg.manual_requested_at and now - cfg.manual_requested_at < QUEUE_PICKUP_WINDOW:
            return {"status": "queued", "handled_by": "worker",
                    "message": "A sync request is already queued for the worker."}
        cfg.manual_requested_at = now
        db.commit()
        return {"status": "queued", "handled_by": "worker",
                "message": "Sync requested; the background worker will start it within a few seconds."}

    with _api_thread_lock:
        if _api_thread is not None and _api_thread.is_alive():
            return JSONResponse(status_code=409, content={
                "status": "already_running", "message": "A synchronisation is already in progress."})
        _api_thread = threading.Thread(target=_run_in_api_process, name="cpi-manual-sync", daemon=True)
        _api_thread.start()
    return {"status": "started", "handled_by": "api",
            "message": "The background worker is not running, so the API started the sync itself."}


@router.get("/settings")
def get_settings(db: Session = Depends(get_db)):
    status = build_status(db, engine)
    return {**status["settings"], "next_check_at": status["next_check_at"],
            "sources": [{"source_key": s["source_key"], "label": s["label"], "enabled": s["enabled"]}
                        for s in status["sources"]]}


@router.post("/settings")
def update_settings(body: SettingsUpdate, db: Session = Depends(get_db)):
    ensure_bootstrap(db)
    cfg = get_sync_settings(db)
    if body.auto_sync_enabled is not None:
        cfg.auto_sync_enabled = body.auto_sync_enabled
    if body.interval_hours is not None:
        cfg.interval_hours = float(body.interval_hours)
    if body.check_on_start is not None:
        cfg.check_on_start = body.check_on_start
    if body.sources:
        known = {s.source_key: s for s in db.execute(select(SyncSource)).scalars()}
        unknown = sorted(set(body.sources) - set(known))
        if unknown:
            raise HTTPException(status_code=422, detail=f"Unknown source(s): {', '.join(unknown)}")
        for key, enabled in body.sources.items():
            known[key].enabled = bool(enabled)
    cfg.updated_at = utcnow()  # tells the worker to reschedule
    db.commit()
    return get_settings(db)


@router.get("/health")
def sync_health():
    """Liveness of the database, worker heartbeat and sync lock."""
    db_ok, worker, running, error = False, worker_health(None), False, None
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
            db_ok = True
            ensure_bootstrap(db)
            worker = worker_health(db.get(SyncWorkerState, 1))
            running = advisory_lock_held(engine)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    status = "ok" if db_ok and worker["healthy"] else ("degraded" if db_ok else "down")
    body = {"status": status, "database": db_ok, "sync_running": running, "worker": worker,
            "checked_at": datetime.utcnow().isoformat() + "Z", "error": error}
    return JSONResponse(status_code=200 if db_ok else 503, content=body)
