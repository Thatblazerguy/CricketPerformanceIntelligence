"""
Ingestion Sync Orchestrator
Coordinates discovery, parsing, and import with logging.
"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from sqlalchemy.orm import Session

from app.ingestion.providers.cricsheet_file import CricsheetFileProvider
from app.ingestion.importer import MatchImporter
from app.models.models import IngestionRun, Provider
from sqlalchemy import select

logger = logging.getLogger(__name__)


class IngestionOrchestrator:
    """
    Orchestrates a full ingestion run for the Cricsheet provider.
    Records the run in the ingestion_runs table.
    """

    def __init__(self, db: Session, ipl_dir: Path, t20i_dir: Path):
        self.db = db
        self.provider = CricsheetFileProvider([ipl_dir, t20i_dir])

    def run(self, limit: Optional[int] = None) -> dict:
        """
        Run ingestion. If limit is set, processes only that many files.
        Returns a summary dict.
        """
        # Get or create provider record
        db_provider = self.db.execute(
            select(Provider).where(Provider.name == "cricsheet")
        ).scalar_one_or_none()
        if not db_provider:
            db_provider = Provider(name="cricsheet")
            self.db.add(db_provider)
            self.db.flush()

        run = IngestionRun(
            provider_id=db_provider.id,
            started_at=datetime.utcnow(),
            status="running",
        )
        self.db.add(run)
        self.db.commit()

        inserted = updated = skipped = failed = discovered = 0
        errors: List[str] = []

        try:
            importer = MatchImporter(self.db)
            count = 0
            for path, match, warnings in self.provider.iter_all():
                discovered += 1
                if limit and count >= limit:
                    break
                try:
                    result = importer.import_match(match)
                    self.db.commit()
                    if result == "inserted":
                        inserted += 1
                    elif result == "updated":
                        updated += 1
                    else:
                        skipped += 1

                    if warnings:
                        for w in warnings:
                            logger.warning("[%s] %s", path.name, w)

                    count += 1
                    if count % 100 == 0:
                        logger.info("Processed %d matches...", count)

                except Exception as exc:
                    self.db.rollback()
                    failed += 1
                    err_msg = f"{path.name}: {exc}"
                    errors.append(err_msg)
                    logger.error("Failed to import %s: %s", path.name, exc)

        except Exception as exc:
            errors.append(f"Fatal error: {exc}")
            logger.exception("Fatal ingestion error")

        finally:
            run.finished_at = datetime.utcnow()
            run.status = "success" if failed == 0 else "partial"
            run.matches_discovered = discovered
            run.matches_inserted = inserted
            run.matches_updated = updated
            run.matches_skipped = skipped
            run.matches_failed = failed
            run.error_summary = "\n".join(errors[:20]) if errors else None
            self.db.commit()

        return {
            "discovered": discovered,
            "inserted": inserted,
            "updated": updated,
            "skipped": skipped,
            "failed": failed,
            "errors": errors[:5],
        }

