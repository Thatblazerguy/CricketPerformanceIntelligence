"""Ingestion management endpoint."""
from fastapi import APIRouter, Depends, BackgroundTasks
from sqlalchemy.orm import Session
from pydantic import BaseModel
from pathlib import Path
from typing import Optional

from app.db.session import get_db
from app.core.config import settings

router = APIRouter()


class IngestionStatusResponse(BaseModel):
    status: str
    message: str
    details: Optional[dict] = None


@router.post("/ingestion/run", response_model=IngestionStatusResponse)
def trigger_ingestion(
    background_tasks: BackgroundTasks,
    limit: Optional[int] = None,
    db: Session = Depends(get_db),
):
    """
    Trigger a data ingestion run.
    Runs in the background. Check /dataset/coverage for updated counts.
    """
    from app.ingestion.sync import IngestionOrchestrator

    ipl_dir = Path(settings.IPL_DATA_DIR)
    t20i_dir = Path(settings.T20I_DATA_DIR)

    def run_ingestion():
        from app.db.session import SessionLocal
        with SessionLocal() as bg_db:
            orch = IngestionOrchestrator(bg_db, ipl_dir, t20i_dir)
            orch.run(limit=limit)

    background_tasks.add_task(run_ingestion)

    return IngestionStatusResponse(
        status="started",
        message="Ingestion started in background. Check /api/v1/dataset/coverage for status.",
    )


@router.post("/ingestion/run-sync", response_model=IngestionStatusResponse)
def trigger_ingestion_sync(
    limit: Optional[int] = 100,
    db: Session = Depends(get_db),
):
    """
    Trigger ingestion synchronously (for testing/CLI use). Returns when complete.
    """
    from app.ingestion.sync import IngestionOrchestrator

    ipl_dir = Path(settings.IPL_DATA_DIR)
    t20i_dir = Path(settings.T20I_DATA_DIR)
    orch = IngestionOrchestrator(db, ipl_dir, t20i_dir)
    result = orch.run(limit=limit)

    return IngestionStatusResponse(
        status="complete",
        message=(
            f"Ingestion complete: {result['inserted']} inserted, "
            f"{result['updated']} updated, {result['skipped']} skipped, "
            f"{result['failed']} failed."
        ),
        details=result,
    )

