"""
Cricsheet automatic synchronisation service.

Used by both the background worker (``backend/worker.py``) and the manual
``POST /data-sync/trigger`` endpoint, so there is exactly one code path.

Per enabled source archive, a cycle runs these phases (persisted on the
``sync_history`` row so the UI can show progress):

  checking_source  HTTP HEAD; compare ETag / Last-Modified with stored values
  downloading      only when changed (or when no HTTP metadata: download and
                   compare the archive SHA-256)
  extracting       validate the ZIP (paths, sizes, CRC) and stage only the
                   members whose SHA-256 differs from ``raw_matches.checksum``
  validating       parse staged JSON with the existing ``CricsheetParser``
  importing        existing ``MatchImporter``; one DB transaction per match,
                   so a failure rolls back that match and leaves the
                   previously imported version intact
  refreshing_statistics  recompute persisted derived data for affected matches

Concurrency: a PostgreSQL session-level advisory lock held on a dedicated
connection for the whole cycle. A second caller gets ``already_running``.
"""
from __future__ import annotations

import hashlib
import logging
import os
import shutil
import stat
import threading
import time
import uuid
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple

import httpx
from sqlalchemy import func, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.core.config import resolve_backend_path, settings
from app.db.session import SessionLocal
from app.db.session import engine as default_engine
from app.domain.entities import CanonicalMatch
from app.ingestion.importer import MatchImporter
from app.ingestion.providers.cricsheet import CricsheetParser
from app.models.models import (
    Delivery,
    Match,
    MatchInnings,
    Provider,
    RawMatch,
    SyncHistory,
    SyncMatchRevision,
    SyncSettings,
    SyncSource,
    SyncWorkerState,
)

logger = logging.getLogger(__name__)

# Advisory-lock keys ("CPI" in ASCII + suffix). Locks are scoped per database.
SYNC_LOCK_KEY = 0x43504901
WORKER_LOCK_KEY = 0x43504902

PHASES = (
    "checking_source", "downloading", "extracting", "validating",
    "importing", "refreshing_statistics", "completed", "failed",
)
CHUNK_SIZE = 1024 * 1024
PROGRESS_EVERY = 25
WORKER_STALE_AFTER = timedelta(minutes=2)
USER_AGENT = "CPI-local-sync/1.0 (+https://cricsheet.org/downloads/)"


# ---------------------------------------------------------------------------
# Source configuration
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SourceSpec:
    key: str
    label: str
    url: str
    target_dir: Path      # local mirror of the archive's JSON files
    enabled_by_config: bool = True


def default_sources() -> List[SourceSpec]:
    """Archives CPI was built from: all_json (gamedata/) plus the IPL and T20I archives in data/raw."""
    return [
        SourceSpec("cricsheet_all", "All matches (all_json.zip)",
                   "https://cricsheet.org/downloads/all_json.zip",
                   resolve_backend_path(settings.GAMEDATA_DIR), settings.SYNC_ENABLE_ALL_JSON),
        SourceSpec("cricsheet_ipl", "Indian Premier League (ipl_json.zip)",
                   "https://cricsheet.org/downloads/ipl_json.zip",
                   resolve_backend_path(settings.IPL_DATA_DIR), settings.SYNC_ENABLE_IPL_JSON),
        # Cricsheet publishes T20 internationals as t20s_json.zip (t20i_json.zip is a 404).
        SourceSpec("cricsheet_t20i", "T20 Internationals (t20s_json.zip)",
                   "https://cricsheet.org/downloads/t20s_json.zip",
                   resolve_backend_path(settings.T20I_DATA_DIR), settings.SYNC_ENABLE_T20I_JSON),
    ]


class ArchiveValidationError(Exception):
    """The downloaded archive is not a safe, valid Cricsheet ZIP."""


class SyncInterrupted(Exception):
    """A stop was requested (worker shutdown) between matches."""


# ---------------------------------------------------------------------------
# Advisory lock on a dedicated connection
# ---------------------------------------------------------------------------

class AdvisoryLock:
    """Session-level pg advisory lock pinned to one connection (never returned to the pool while held)."""

    def __init__(self, engine: Engine, key: int):
        self.engine, self.key, self.conn = engine, key, None

    def acquire(self) -> bool:
        conn = self.engine.connect()
        try:
            got = bool(conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": self.key}).scalar())
            conn.commit()
        except Exception:
            conn.close()
            raise
        if not got:
            conn.close()
            return False
        self.conn = conn
        return True

    def is_alive(self) -> bool:
        if self.conn is None:
            return False
        try:
            self.conn.execute(text("SELECT 1"))
            self.conn.commit()
            return True
        except Exception:
            return False

    def release(self) -> None:
        if self.conn is None:
            return
        try:
            self.conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": self.key})
            self.conn.commit()
        except Exception:  # connection already gone: server released the lock with it
            logger.debug("advisory unlock failed", exc_info=True)
        finally:
            try:
                self.conn.close()
            finally:
                self.conn = None


def advisory_lock_held(engine: Engine, key: int = SYNC_LOCK_KEY) -> bool:
    """True if any session in this database currently holds the advisory lock."""
    with engine.connect() as conn:
        return bool(conn.execute(text("""
            SELECT EXISTS (SELECT 1 FROM pg_locks l JOIN pg_database d ON d.oid = l.database
                           WHERE l.locktype = 'advisory' AND l.granted AND d.datname = current_database()
                             AND l.classid = 0 AND l.objid = :k AND l.objsubid = 1)
        """), {"k": key}).scalar())


# ---------------------------------------------------------------------------
# Bootstrap / settings helpers (shared with the API and worker)
# ---------------------------------------------------------------------------

def ensure_bootstrap(db: Session, sources: Optional[Sequence[SourceSpec]] = None) -> None:
    """Create singleton settings/state rows and one sync_sources row per configured archive."""
    if db.get(SyncSettings, 1) is None:
        db.add(SyncSettings(id=1, auto_sync_enabled=True,
                            interval_hours=float(settings.SYNC_DEFAULT_INTERVAL_HOURS), check_on_start=True))
    if db.get(SyncWorkerState, 1) is None:
        db.add(SyncWorkerState(id=1, state="stopped"))
    existing = {s.source_key: s for s in db.execute(select(SyncSource)).scalars()}
    for spec in sources or default_sources():
        row = existing.get(spec.key)
        if row is None:
            db.add(SyncSource(source_key=spec.key, label=spec.label, archive_url=spec.url,
                              enabled=spec.enabled_by_config))
        else:
            if row.archive_url != spec.url:
                # A different URL means stored ETag/checksum no longer describe it.
                row.archive_url, row.etag, row.last_modified, row.latest_checksum = spec.url, None, None, None
            row.label = spec.label
    db.commit()


def get_sync_settings(db: Session) -> SyncSettings:
    row = db.get(SyncSettings, 1)
    if row is None:
        ensure_bootstrap(db)
        row = db.get(SyncSettings, 1)
    return row


def utcnow() -> datetime:
    return datetime.utcnow()


# ---------------------------------------------------------------------------
# Staged member bookkeeping
# ---------------------------------------------------------------------------

@dataclass
class StagedFile:
    source_match_id: str
    file_name: str
    path: Path
    checksum: str
    previous_checksum: Optional[str]
    match: Optional[CanonicalMatch] = None


@dataclass
class SourceOutcome:
    source_key: str
    history_id: int
    status: str
    new_matches: int = 0
    updated_matches: int = 0
    unchanged_matches: int = 0
    failed_records: int = 0
    error: Optional[str] = None
    inserted_ids: Set[str] = field(default_factory=set)
    corrected_ids: Set[str] = field(default_factory=set)


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class CricsheetSyncService:
    def __init__(
        self,
        session_factory: Callable[[], Session] = SessionLocal,
        engine: Optional[Engine] = None,
        sources: Optional[Sequence[SourceSpec]] = None,
        archive_dir: Optional[Path] = None,
        staging_dir: Optional[Path] = None,
        http_timeout: Optional[float] = None,
        retry_delays: Sequence[float] = (2.0, 8.0),
        refresh_statistics: bool = True,
        stop_event: Optional[threading.Event] = None,
        max_archive_bytes: Optional[int] = None,
        max_uncompressed_bytes: Optional[int] = None,
        max_member_bytes: Optional[int] = None,
    ):
        self.session_factory = session_factory
        self.engine = engine or default_engine
        self.sources = list(sources) if sources is not None else default_sources()
        self.archive_dir = Path(archive_dir) if archive_dir else resolve_backend_path(settings.SYNC_ARCHIVE_DIR)
        self.staging_dir = Path(staging_dir) if staging_dir else resolve_backend_path(settings.SYNC_STAGING_DIR)
        self.http_timeout = http_timeout or settings.SYNC_HTTP_TIMEOUT_SECONDS
        self.retry_delays = tuple(retry_delays)
        self.refresh_statistics = refresh_statistics
        self.stop_event = stop_event or threading.Event()
        self.max_archive_bytes = max_archive_bytes or settings.SYNC_MAX_ARCHIVE_BYTES
        self.max_uncompressed_bytes = max_uncompressed_bytes or settings.SYNC_MAX_UNCOMPRESSED_BYTES
        self.max_member_bytes = max_member_bytes or settings.SYNC_MAX_MEMBER_BYTES
        self.parser = CricsheetParser()

    # ------------------------------------------------------------------ run

    def run_sync(self, triggered_by: str = "scheduler") -> Dict[str, Any]:
        """Run one cycle over all enabled sources. Never raises for per-source failures."""
        lock = AdvisoryLock(self.engine, SYNC_LOCK_KEY)
        if not lock.acquire():
            logger.info("Sync requested (%s) but another sync holds the lock", triggered_by)
            return {"status": "already_running"}
        run_id = str(uuid.uuid4())
        started = utcnow()
        t0 = time.monotonic()
        outcomes: List[SourceOutcome] = []
        try:
            with self.session_factory() as db:
                ensure_bootstrap(db, self.sources)
                self._mark_interrupted_runs(db)
                state = db.get(SyncWorkerState, 1)
                state.last_run_started_at = started
                enabled = {s.source_key for s in db.execute(select(SyncSource).where(SyncSource.enabled.is_(True))).scalars()}
                db.commit()
            logger.info("Sync run %s started (%s); sources: %s", run_id, triggered_by, sorted(enabled))
            for spec in self.sources:
                if spec.key not in enabled:
                    continue
                if self.stop_event.is_set():
                    break
                outcomes.append(self._sync_source(spec, run_id, triggered_by))
        finally:
            lock.release()

        ok = bool(outcomes) and all(o.status in ("completed", "no_changes") for o in outcomes)
        if ok:
            with self.session_factory() as db:
                db.get(SyncWorkerState, 1).last_success_at = utcnow()
                db.commit()
        if any(o.inserted_ids or o.corrected_ids for o in outcomes):
            from app.services.data_version import clear_analytics_caches
            clear_analytics_caches()  # no-op cost in the worker; immediate in the API process
        statuses = {o.status for o in outcomes}
        overall = ("failed" if statuses == {"failed"} else
                   "interrupted" if statuses == {"interrupted"} else
                   "partial" if statuses & {"failed", "partial", "interrupted"} else
                   "completed" if "completed" in statuses else
                   "no_changes" if statuses else "skipped")
        result = {
            "status": overall,
            "run_id": run_id,
            "triggered_by": triggered_by,
            "started_at": started.isoformat(),
            "duration_seconds": round(time.monotonic() - t0, 2),
            "sources": {o.source_key: {
                "status": o.status, "history_id": o.history_id, "new_matches": o.new_matches,
                "updated_matches": o.updated_matches, "unchanged_matches": o.unchanged_matches,
                "failed_records": o.failed_records, "error": o.error,
            } for o in outcomes},
        }
        logger.info("Sync run %s finished: %s in %.1fs", run_id, overall, result["duration_seconds"])
        return result

    def _mark_interrupted_runs(self, db: Session) -> None:
        """We hold the lock, so any row still 'running' belongs to a process that died."""
        for row in db.execute(select(SyncHistory).where(SyncHistory.status == "running")).scalars():
            row.status, row.phase = "interrupted", "failed"
            row.completed_at = row.completed_at or utcnow()
            row.error_detail = (row.error_detail or "") + "Sync process stopped before completion; previously imported data was kept."
        db.flush()

    # ------------------------------------------------------------------ history helpers

    def _new_history(self, run_id: str, source_key: str, triggered_by: str) -> int:
        with self.session_factory() as db:
            row = SyncHistory(run_id=run_id, source_key=source_key, triggered_by=triggered_by,
                              started_at=utcnow(), status="running", phase="checking_source")
            db.add(row)
            db.commit()
            return row.id

    def _update_history(self, history_id: int, **fields: Any) -> None:
        with self.session_factory() as db:
            row = db.get(SyncHistory, history_id)
            for k, v in fields.items():
                setattr(row, k, v)
            db.commit()

    def _update_source(self, source_key: str, **fields: Any) -> None:
        with self.session_factory() as db:
            row = db.execute(select(SyncSource).where(SyncSource.source_key == source_key)).scalar_one()
            for k, v in fields.items():
                setattr(row, k, v)
            db.commit()

    def _check_stop(self) -> None:
        if self.stop_event.is_set():
            raise SyncInterrupted("Stop requested; remaining matches will be processed on the next sync.")

    # ------------------------------------------------------------------ per source

    def _sync_source(self, spec: SourceSpec, run_id: str, triggered_by: str) -> SourceOutcome:
        history_id = self._new_history(run_id, spec.key, triggered_by)
        outcome = SourceOutcome(spec.key, history_id, "running")
        t0 = time.monotonic()
        workdir = self.staging_dir / run_id / spec.key
        failed_files: List[Dict[str, str]] = []
        try:
            with self.session_factory() as db:
                src = db.execute(select(SyncSource).where(SyncSource.source_key == spec.key)).scalar_one()
                stored = {"etag": src.etag, "last_modified": src.last_modified,
                          "checksum": src.latest_checksum, "imported": src.last_imported_at}

            # 1. checking_source
            probe = self._probe(spec.url)
            self._update_source(spec.key, last_checked_at=utcnow())
            has_meta = bool(probe.get("etag") or probe.get("last_modified"))
            if has_meta and stored["imported"] is not None and \
                    probe.get("etag") == stored["etag"] and probe.get("last_modified") == stored["last_modified"]:
                self._update_source(spec.key, last_error=None)
                return self._finish(outcome, t0, "no_changes", archive_changed=False)

            # 2. downloading
            self._update_history(history_id, phase="downloading", progress_current=0,
                                 progress_total=int(probe.get("size") or 0))
            workdir.mkdir(parents=True, exist_ok=True)
            archive_path, checksum, meta = self._download(spec.url, workdir, history_id)
            self._update_history(history_id, archive_checksum=checksum)
            if checksum == stored["checksum"] and stored["imported"] is not None:
                # Headers moved (or were absent) but the bytes are identical.
                self._update_source(spec.key, etag=meta.get("etag"), last_modified=meta.get("last_modified"),
                                    archive_size_bytes=archive_path.stat().st_size, last_error=None)
                return self._finish(outcome, t0, "no_changes", archive_changed=False)

            # 3. extracting (validate archive + stage only new/changed members)
            self._update_history(history_id, phase="extracting", archive_changed=True)
            staged, discovered, unchanged = self._extract_changed(archive_path, workdir / "matches", history_id)
            outcome.unchanged_matches = unchanged
            self._update_history(history_id, matches_discovered=discovered, unchanged_matches=unchanged)

            # 4. validating
            self._update_history(history_id, phase="validating", progress_current=0, progress_total=len(staged))
            valid: List[StagedFile] = []
            for i, item in enumerate(staged, 1):
                try:
                    item.match, _warnings = self.parser.parse_file(item.path)
                    if item.match.source_match_id != item.source_match_id:
                        raise ValueError("parsed match id does not match file name")
                    valid.append(item)
                except Exception as exc:
                    failed_files.append({"file": item.file_name, "stage": "validating", "error": str(exc)[:500]})
                if i % PROGRESS_EVERY == 0:
                    self._update_history(history_id, progress_current=i)
            outcome.failed_records = len(failed_files)

            # 5. importing
            self._update_history(history_id, phase="importing", progress_current=0, progress_total=len(valid),
                                 failed_records=outcome.failed_records)
            imported, previous_players = self._import(valid, spec.key, history_id, outcome, failed_files)

            # Keep the local JSON mirror in step with what is now in PostgreSQL.
            self._mirror(imported, spec.target_dir)

            # 6. refreshing_statistics
            self._update_history(history_id, phase="refreshing_statistics",
                                 new_matches=outcome.new_matches, updated_matches=outcome.updated_matches,
                                 failed_records=outcome.failed_records, failed_files=failed_files[:200] or None)
            stats: Dict[str, Any] = {}
            if self.refresh_statistics and (outcome.inserted_ids or outcome.corrected_ids):
                from app.ingestion.dependent_refresh import refresh_dependent_statistics
                with self.session_factory() as db:
                    try:
                        stats = refresh_dependent_statistics(db, outcome.inserted_ids, outcome.corrected_ids,
                                                             previous_players)
                    except Exception as exc:
                        db.rollback()
                        logger.exception("%s: dependent statistics refresh failed", spec.key)
                        stats = {"error": str(exc)[:500]}
                        outcome.error = f"Statistics refresh failed: {exc}"

            # Archive processed: keep it as the reference copy and advance stored metadata.
            # Matches that failed are absent from raw_matches (or keep their old checksum),
            # so they are retried automatically the next time the archive changes.
            self.archive_dir.mkdir(parents=True, exist_ok=True)
            final_archive = self.archive_dir / f"{spec.key}.zip"
            os.replace(archive_path, final_archive)
            clean = not failed_files and not outcome.error
            # ETag/Last-Modified always advance (avoids re-downloading every cycle). The archive
            # checksum is recorded only after a clean import, so the next refresh of the
            # archive - even byte-identical under a new ETag - re-attempts failed matches.
            source_fields: Dict[str, Any] = dict(
                etag=meta.get("etag"), last_modified=meta.get("last_modified"),
                archive_size_bytes=final_archive.stat().st_size,
                last_error=None if clean else (outcome.error or f"{outcome.failed_records} match file(s) failed"),
            )
            if clean:
                source_fields["latest_checksum"] = checksum
                source_fields["last_imported_at"] = utcnow()  # last *fully* successful import
            self._update_source(spec.key, **source_fields)
            status = "completed" if clean else "partial"
            return self._finish(outcome, t0, status, stats_refresh=stats or None,
                                failed_files=failed_files[:200] or None, error_detail=outcome.error)
        except SyncInterrupted as exc:
            outcome.error = str(exc)
            return self._finish(outcome, t0, "interrupted", phase="failed", error_detail=str(exc),
                                failed_files=failed_files[:200] or None)
        except Exception as exc:
            logger.exception("%s: sync failed", spec.key)
            outcome.error = f"{type(exc).__name__}: {exc}"
            try:
                self._update_source(spec.key, last_error=outcome.error[:2000])
            except Exception:
                logger.debug("could not record source error", exc_info=True)
            return self._finish(outcome, t0, "failed", phase="failed", error_detail=outcome.error[:4000],
                                failed_files=failed_files[:200] or None)
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
            try:
                workdir.parent.rmdir()
            except OSError:
                pass

    def _finish(self, outcome: SourceOutcome, t0: float, status: str, phase: str = "completed", **fields: Any) -> SourceOutcome:
        outcome.status = status
        self._update_history(
            outcome.history_id, status=status, phase=phase, completed_at=utcnow(),
            duration_seconds=round(time.monotonic() - t0, 3),
            new_matches=outcome.new_matches, updated_matches=outcome.updated_matches,
            unchanged_matches=outcome.unchanged_matches, failed_records=outcome.failed_records,
            **fields,
        )
        logger.info("%s: %s (new=%d corrected=%d unchanged=%d failed=%d)", outcome.source_key, status,
                    outcome.new_matches, outcome.updated_matches, outcome.unchanged_matches, outcome.failed_records)
        return outcome

    # ------------------------------------------------------------------ network

    def _client(self) -> httpx.Client:
        return httpx.Client(timeout=self.http_timeout, follow_redirects=True, headers={"User-Agent": USER_AGENT})

    def _with_retries(self, fn: Callable[[], Any]) -> Any:
        delays = list(self.retry_delays)
        while True:
            try:
                return fn()
            except (httpx.TransportError, ArchiveIncomplete) as exc:
                if not delays:
                    raise
                delay = delays.pop(0)
                logger.warning("Network problem (%s); retrying in %.0fs", exc, delay)
                if self.stop_event.wait(delay):
                    raise SyncInterrupted("Stop requested during network retry")

    def _probe(self, url: str) -> Dict[str, Any]:
        """HEAD the archive. Returns etag/last_modified/size (any may be None)."""
        def do():
            with self._client() as client:
                resp = client.head(url)
                if resp.status_code in (405, 501):  # HEAD unsupported: fall back to checksum
                    return {}
                resp.raise_for_status()
                size = resp.headers.get("Content-Length")
                return {"etag": resp.headers.get("ETag"), "last_modified": resp.headers.get("Last-Modified"),
                        "size": int(size) if size and size.isdigit() else None}
        return self._with_retries(do)

    def _download(self, url: str, workdir: Path, history_id: int) -> Tuple[Path, str, Dict[str, Any]]:
        target = workdir / "archive.zip"
        # Survives retries so an interrupted transfer resumes with a Range request.
        state: Dict[str, Any] = {"received": 0, "hasher": hashlib.sha256(), "validator": None, "total": None}

        def do():
            headers = {}
            if state["received"] and state["validator"]:
                # If-Range: the server sends the remainder only if the archive is unchanged,
                # otherwise a full 200 response and we start over.
                headers = {"Range": f"bytes={state['received']}-", "If-Range": state["validator"]}
            last_report = state["received"]
            with self._client() as client, client.stream("GET", url, headers=headers) as resp:
                resp.raise_for_status()
                resuming = resp.status_code == 206 and (resp.headers.get("Content-Range") or "").startswith(
                    f"bytes {state['received']}-")
                if resuming:
                    total = (resp.headers.get("Content-Range") or "").rsplit("/", 1)[-1]
                    expected_n = int(total) if total.isdigit() else state["total"]
                    logger.info("Resuming download at %d bytes", state["received"])
                else:
                    state.update(received=0, hasher=hashlib.sha256())
                    expected = resp.headers.get("Content-Length")
                    expected_n = int(expected) if expected and expected.isdigit() else None
                    state["validator"] = resp.headers.get("ETag") or resp.headers.get("Last-Modified")
                state["total"] = expected_n
                if expected_n and expected_n > self.max_archive_bytes:
                    raise ArchiveValidationError(f"Archive is {expected_n} bytes; limit is {self.max_archive_bytes}")
                with open(target, "ab" if resuming else "wb") as fh:
                    # Network-sized chunks: everything received before a drop is kept for resume.
                    for chunk in resp.iter_bytes():
                        if self.stop_event.is_set():
                            raise SyncInterrupted("Stop requested during download")
                        if state["received"] + len(chunk) > self.max_archive_bytes:
                            raise ArchiveValidationError("Archive exceeds the configured size limit")
                        fh.write(chunk)
                        state["hasher"].update(chunk)
                        state["received"] += len(chunk)
                        if state["received"] - last_report >= 8 * CHUNK_SIZE:
                            last_report = state["received"]
                            self._update_history(history_id, progress_current=state["received"],
                                                 progress_total=expected_n or 0)
                received = state["received"]
                if expected_n is not None and received != expected_n:
                    raise ArchiveIncomplete(f"Download truncated: received {received} of {expected_n} bytes")
                meta = {"etag": resp.headers.get("ETag"), "last_modified": resp.headers.get("Last-Modified")}
            self._update_history(history_id, progress_current=received, progress_total=expected_n or received)
            return target, state["hasher"].hexdigest(), meta
        try:
            return self._with_retries(do)
        except Exception:
            target.unlink(missing_ok=True)
            raise

    # ------------------------------------------------------------------ archive

    def validate_archive(self, archive_path: Path) -> List[zipfile.ZipInfo]:
        """Structural validation; returns the JSON members. CRCs are verified while reading."""
        try:
            zf = zipfile.ZipFile(archive_path)
        except (zipfile.BadZipFile, OSError) as exc:
            raise ArchiveValidationError(f"Not a valid ZIP archive: {exc}") from exc
        with zf:
            members: List[zipfile.ZipInfo] = []
            seen: Set[str] = set()
            total = 0
            for info in zf.infolist():
                if info.is_dir():
                    continue
                name = info.filename
                parts = PurePosixPath(name.replace("\\", "/")).parts
                if name.startswith(("/", "\\")) or ".." in parts or (parts and ":" in parts[0]):
                    raise ArchiveValidationError(f"Unsafe path in archive: {name!r}")
                if stat.S_ISLNK(info.external_attr >> 16):
                    raise ArchiveValidationError(f"Symbolic link in archive: {name!r}")
                base = parts[-1] if parts else ""
                if not base.lower().endswith(".json"):
                    continue  # README.txt / LICENSE.txt
                if info.file_size > self.max_member_bytes:
                    raise ArchiveValidationError(f"{base} is larger than the per-file limit")
                if info.compress_size and info.file_size / max(info.compress_size, 1) > 1000:
                    raise ArchiveValidationError(f"{base} has a suspicious compression ratio")
                if base in seen:
                    raise ArchiveValidationError(f"Duplicate match file in archive: {base}")
                seen.add(base)
                total += info.file_size
                members.append(info)
            if total > self.max_uncompressed_bytes:
                raise ArchiveValidationError("Archive expands beyond the configured size limit")
            if not members:
                raise ArchiveValidationError("Archive contains no match JSON files")
            return members

    def _known_checksums(self) -> Dict[str, str]:
        with self.session_factory() as db:
            return dict(db.execute(
                select(RawMatch.source_match_id, RawMatch.checksum)
                .join(Provider, Provider.id == RawMatch.provider_id)
                .where(Provider.name == "cricsheet")
            ).all())

    def _extract_changed(self, archive_path: Path, out_dir: Path, history_id: int) -> Tuple[List[StagedFile], int, int]:
        members = self.validate_archive(archive_path)
        known = self._known_checksums()
        out_dir.mkdir(parents=True, exist_ok=True)
        staged: List[StagedFile] = []
        unchanged = 0
        self._update_history(history_id, progress_current=0, progress_total=len(members))
        with zipfile.ZipFile(archive_path) as zf:
            for i, info in enumerate(members, 1):
                if i % 500 == 0:
                    self._check_stop()
                    self._update_history(history_id, progress_current=i)
                base = PurePosixPath(info.filename.replace("\\", "/")).name
                try:
                    with zf.open(info) as fh:  # raises BadZipFile on CRC mismatch
                        data = fh.read(self.max_member_bytes + 1)
                except (zipfile.BadZipFile, zipfile.LargeZipFile, EOFError, OSError) as exc:
                    raise ArchiveValidationError(f"Corrupt archive member {base}: {exc}") from exc
                if len(data) > self.max_member_bytes:
                    raise ArchiveValidationError(f"{base} is larger than the per-file limit")
                checksum = hashlib.sha256(data).hexdigest()
                source_match_id = Path(base).stem
                previous = known.get(source_match_id)
                if previous == checksum:
                    unchanged += 1
                    continue
                path = out_dir / base
                path.write_bytes(data)
                staged.append(StagedFile(source_match_id, base, path, checksum, previous))
        self._update_history(history_id, progress_current=len(members))
        logger.info("%s: %d members, %d unchanged, %d staged (new or corrected)",
                    archive_path.name, len(members), unchanged, len(staged))
        return staged, len(members), unchanged

    # ------------------------------------------------------------------ import

    def _import(self, items: List[StagedFile], source_key: str, history_id: int, outcome: SourceOutcome,
                failed_files: List[Dict[str, str]]) -> Tuple[List[StagedFile], Set[str]]:
        imported: List[StagedFile] = []
        previous_players: Set[str] = set()
        db = self.session_factory()
        try:
            importer = MatchImporter(db)
            for i, item in enumerate(items, 1):
                self._check_stop()
                try:
                    old_players: Set[str] = set()
                    existing_id = db.execute(
                        select(Match.id).join(Provider, Provider.id == Match.provider_id)
                        .where(Provider.name == item.match.provider_name, Match.source_match_id == item.source_match_id)
                    ).scalar()
                    if existing_id is not None:
                        old_players = set(db.execute(
                            select(Delivery.batter_id).join(MatchInnings, MatchInnings.id == Delivery.innings_id)
                            .where(MatchInnings.match_id == existing_id)
                            .union(select(Delivery.bowler_id).join(MatchInnings, MatchInnings.id == Delivery.innings_id)
                                   .where(MatchInnings.match_id == existing_id))
                        ).scalars()) - {None}

                    result = importer.import_match(item.match)  # replaces innings/deliveries when checksum changed
                    match_id = existing_id or db.execute(
                        select(Match.id).join(Provider, Provider.id == Match.provider_id)
                        .where(Provider.name == item.match.provider_name, Match.source_match_id == item.source_match_id)
                    ).scalar_one()
                    if result == "updated":
                        db.add(SyncMatchRevision(match_id=match_id, source_match_id=item.source_match_id,
                                                 source_key=source_key, sync_history_id=history_id,
                                                 previous_checksum=item.previous_checksum,
                                                 new_checksum=item.checksum, revised_at=utcnow()))
                    db.commit()  # match, innings, deliveries and revision row commit together
                    if result == "inserted":
                        outcome.new_matches += 1
                        outcome.inserted_ids.add(match_id)
                    elif result == "updated":
                        outcome.updated_matches += 1
                        outcome.corrected_ids.add(match_id)
                        previous_players |= old_players
                    else:
                        outcome.unchanged_matches += 1
                    imported.append(item)
                except Exception as exc:
                    db.rollback()
                    # The importer caches ids of rows created inside the rolled-back transaction.
                    importer = MatchImporter(db)
                    outcome.failed_records += 1
                    failed_files.append({"file": item.file_name, "stage": "importing",
                                         "error": f"{type(exc).__name__}: {str(exc)[:400]}"})
                    logger.error("%s: failed to import %s: %s", source_key, item.file_name, exc)
                if i % PROGRESS_EVERY == 0 or i == len(items):
                    self._update_history(history_id, progress_current=i, new_matches=outcome.new_matches,
                                         updated_matches=outcome.updated_matches,
                                         failed_records=outcome.failed_records)
        finally:
            db.close()
        return imported, previous_players

    @staticmethod
    def _mirror(items: List[StagedFile], target_dir: Path) -> None:
        if not items:
            return
        target_dir.mkdir(parents=True, exist_ok=True)
        for item in items:
            tmp = target_dir / f".{item.file_name}.tmp"
            shutil.copyfile(item.path, tmp)
            os.replace(tmp, target_dir / item.file_name)


class ArchiveIncomplete(Exception):
    """Download ended before Content-Length bytes arrived (treated as a transient network error)."""


# ---------------------------------------------------------------------------
# Status (used by the API and worker CLI)
# ---------------------------------------------------------------------------

_counts_cache: Dict[str, Any] = {"marker": object(), "at": 0.0, "value": None}


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() + "Z" if dt else None


def history_to_dict(h: SyncHistory) -> Dict[str, Any]:
    return {
        "id": h.id, "run_id": h.run_id, "source_key": h.source_key, "triggered_by": h.triggered_by,
        "started_at": _iso(h.started_at), "completed_at": _iso(h.completed_at),
        "status": h.status, "phase": h.phase,
        "progress_current": h.progress_current, "progress_total": h.progress_total,
        "archive_changed": h.archive_changed, "matches_discovered": h.matches_discovered,
        "new_matches": h.new_matches, "updated_matches": h.updated_matches,
        "unchanged_matches": h.unchanged_matches, "failed_records": h.failed_records,
        "error_detail": h.error_detail, "failed_files": h.failed_files, "stats_refresh": h.stats_refresh,
        "duration_seconds": h.duration_seconds,
    }


def dataset_counts(db: Session) -> Dict[str, int]:
    """Exact table counts, cached until the data marker moves (or 10 minutes pass)."""
    from app.services.data_version import current_data_marker
    marker = current_data_marker(db)
    now = time.monotonic()
    if _counts_cache["value"] is not None and _counts_cache["marker"] == marker and now - _counts_cache["at"] < 600:
        return _counts_cache["value"]
    value = {
        "total_matches": int(db.execute(select(func.count()).select_from(Match)).scalar_one()),
        "total_innings": int(db.execute(select(func.count()).select_from(MatchInnings)).scalar_one()),
        "total_deliveries": int(db.execute(select(func.count()).select_from(Delivery)).scalar_one()),
    }
    _counts_cache.update(marker=marker, at=now, value=value)
    return value


def worker_health(state: Optional[SyncWorkerState], now: Optional[datetime] = None) -> Dict[str, Any]:
    now = now or utcnow()
    if state is None:
        return {"healthy": False, "state": "unknown", "pid": None, "hostname": None, "heartbeat_at": None,
                "started_at": None, "last_success_at": None, "last_error": None, "seconds_since_heartbeat": None}
    age = (now - state.heartbeat_at).total_seconds() if state.heartbeat_at else None
    healthy = state.state != "stopped" and age is not None and age <= WORKER_STALE_AFTER.total_seconds()
    return {
        "healthy": healthy,
        "state": state.state if healthy or state.state == "stopped" else "unresponsive",
        "pid": state.pid, "hostname": state.hostname, "started_at": _iso(state.started_at),
        "heartbeat_at": _iso(state.heartbeat_at), "seconds_since_heartbeat": round(age, 1) if age is not None else None,
        "last_success_at": _iso(state.last_success_at), "last_error": state.last_error,
    }


def _summarise_run(rows: List[SyncHistory]) -> Optional[Dict[str, Any]]:
    if not rows:
        return None
    statuses = {r.status for r in rows}
    status = ("running" if "running" in statuses else
              "failed" if statuses <= {"failed"} else
              "interrupted" if statuses <= {"interrupted"} else
              "partial" if statuses & {"failed", "partial", "interrupted"} else
              "completed" if "completed" in statuses else "no_changes")
    done = [r.completed_at for r in rows if r.completed_at]
    return {
        "run_id": rows[0].run_id, "status": status, "triggered_by": rows[0].triggered_by,
        "started_at": _iso(min(r.started_at for r in rows)),
        "completed_at": _iso(max(done)) if done and status != "running" else None,
        "new_matches": sum(r.new_matches for r in rows),
        "updated_matches": sum(r.updated_matches for r in rows),
        "unchanged_matches": sum(r.unchanged_matches for r in rows),
        "failed_records": sum(r.failed_records for r in rows),
        "sources": [history_to_dict(r) for r in sorted(rows, key=lambda r: r.id)],
    }


def build_status(db: Session, engine: Optional[Engine] = None) -> Dict[str, Any]:
    ensure_bootstrap(db)
    cfg = get_sync_settings(db)
    state = db.get(SyncWorkerState, 1)
    sources = list(db.execute(select(SyncSource).order_by(SyncSource.id)).scalars())

    latest_rows = list(db.execute(select(SyncHistory).order_by(SyncHistory.id.desc()).limit(1)).scalars())
    current = None
    latest_completed = None
    if latest_rows:
        run_rows = list(db.execute(select(SyncHistory).where(SyncHistory.run_id == latest_rows[0].run_id)).scalars())
        summary = _summarise_run(run_rows)
        if summary and summary["status"] == "running":
            current = summary
            prev = db.execute(select(SyncHistory.run_id).where(SyncHistory.status != "running")
                              .order_by(SyncHistory.id.desc()).limit(1)).scalar()
            if prev:
                latest_completed = _summarise_run(list(db.execute(
                    select(SyncHistory).where(SyncHistory.run_id == prev)).scalars()))
        else:
            latest_completed = summary

    last_checked = max((s.last_checked_at for s in sources if s.last_checked_at), default=None)
    last_imported = max((s.last_imported_at for s in sources if s.last_imported_at), default=None)
    data_through = db.execute(select(func.max(Match.start_date))).scalar()
    worker = worker_health(state)
    running = current is not None
    if engine is not None:
        try:
            running = running or advisory_lock_held(engine)
        except Exception:
            pass

    return {
        "data_updated_through": data_through.isoformat() if data_through else None,
        "last_checked_at": _iso(last_checked),
        "last_imported_at": _iso(last_imported),
        **dataset_counts(db),
        "latest_sync": latest_completed,
        "current_sync": current,
        "sync_running": running,
        "new_matches_latest_sync": latest_completed["new_matches"] if latest_completed else 0,
        "corrected_matches_latest_sync": latest_completed["updated_matches"] if latest_completed else 0,
        "next_check_at": _iso(state.next_check_at) if (state and cfg.auto_sync_enabled and worker["healthy"]) else None,
        "manual_sync_requested_at": _iso(cfg.manual_requested_at),
        "worker": worker,
        "settings": {"auto_sync_enabled": cfg.auto_sync_enabled, "interval_hours": cfg.interval_hours,
                     "check_on_start": cfg.check_on_start, "updated_at": _iso(cfg.updated_at)},
        "sources": [{
            "source_key": s.source_key, "label": s.label, "archive_url": s.archive_url, "enabled": s.enabled,
            "etag": s.etag, "last_modified": s.last_modified, "latest_checksum": s.latest_checksum,
            "archive_size_bytes": s.archive_size_bytes, "last_checked_at": _iso(s.last_checked_at),
            "last_imported_at": _iso(s.last_imported_at), "last_error": s.last_error,
        } for s in sources],
    }
