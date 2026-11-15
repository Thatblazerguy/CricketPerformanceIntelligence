"""Cricsheet inventory: what Cricsheet publishes vs. what CPI holds.

The inventory comes from the README.txt that Cricsheet ships inside every
archive, which lists each match in the archive (date, team type, match type,
gender, id, teams) and states how many matches were withheld. The archive is
the one the existing sync worker already downloads, so no extra scraping of
cricsheet.org is involved.
"""
from __future__ import annotations

import re
import zipfile
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import httpx
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.config import resolve_backend_path, settings
from app.hybrid.registry import log_event
from app.hybrid.sources.base import SourceAdapter, SourceInfo
from app.models.models import SourceInventoryItem, SyncSettings, SyncSource

SOURCE_KEY = "cricsheet"
LINE = re.compile(r"^(\d{4}-\d{2}-\d{2}) - (\w+) - (\S+) - (male|female) - (\S+) - (.+)$")
WITHHELD = re.compile(r"further (\d+) matches have been withheld", re.I)


def parse_readme(content: str) -> Tuple[List[Dict], Optional[int]]:
    items = []
    for line in content.splitlines():
        m = LINE.match(line.strip())
        if m:
            items.append({"start_date": date.fromisoformat(m.group(1)), "team_type": m.group(2),
                          "match_type": m.group(3), "gender": m.group(4), "source_match_id": m.group(5),
                          "teams": m.group(6)[:512]})
    w = WITHHELD.search(content.replace("\n", " "))
    return items, int(w.group(1)) if w else None


class CricsheetInventoryAdapter(SourceAdapter):
    info = SourceInfo(
        key=SOURCE_KEY, name="Cricsheet", data_level="ball_by_ball", access="open",
        licence="Open Data Commons ODbL 1.0 (attribution + share-alike)",
        url="https://cricsheet.org/downloads/",
        coverage="Ball-by-ball for Tests from Dec 2001, ODIs from 2002, T20Is from 2005, plus many domestic and "
                 "franchise competitions. Nothing earlier than 2001.",
        integrated=True,
        notes=["Primary CPI source; never replaced.",
               "Matches involving Afghanistan men or played in the Afghanistan Premier League are withheld by "
               "Cricsheet policy and are reported, not fetched elsewhere."],
    )

    def __init__(self, archive_path: Optional[Path] = None, gamedata_dir: Optional[Path] = None):
        self.archive_path = archive_path or resolve_backend_path(settings.SYNC_ARCHIVE_DIR) / "cricsheet_all.zip"
        self.gamedata_dir = gamedata_dir or resolve_backend_path(settings.GAMEDATA_DIR)

    # ------------------------------------------------------------------ inventory

    def _readme(self) -> Tuple[str, str]:
        if self.archive_path.exists():
            with zipfile.ZipFile(self.archive_path) as zf:
                return zf.read("README.txt").decode("utf-8", "replace"), str(self.archive_path.name)
        fallback = self.gamedata_dir / "README.txt"
        if fallback.exists():
            return fallback.read_text(encoding="utf-8", errors="replace"), "gamedata/README.txt"
        raise FileNotFoundError("No Cricsheet archive or README.txt available locally; run a Cricsheet sync first.")

    def refresh_inventory(self, db: Session) -> Dict[str, int]:
        content, origin = self._readme()
        items, withheld = parse_readme(content)
        now = datetime.utcnow()
        rows = [{**it, "now": now} for it in items]
        for i in range(0, len(rows), 5000):
            db.execute(text("""
                INSERT INTO source_inventory (id, source_key, source_match_id, start_date, match_type, team_type,
                    gender, teams, status, attempts, first_seen_at, last_seen_at)
                VALUES (gen_random_uuid()::text, 'cricsheet', :source_match_id, :start_date, :match_type, :team_type,
                    :gender, :teams, 'available', 0, :now, :now)
                ON CONFLICT (source_key, source_match_id) DO UPDATE SET last_seen_at = EXCLUDED.last_seen_at,
                    start_date = EXCLUDED.start_date, teams = EXCLUDED.teams"""), rows[i:i + 5000])
        counts = self.compare(db)
        counts.update({"listed": len(items), "withheld_by_source": withheld or 0})
        log_event(db, SOURCE_KEY, "refresh_inventory", "ok", f"Inventory read from {origin}", **counts)
        return counts

    def compare(self, db: Session) -> Dict[str, int]:
        """Classify every inventory row as imported / failed / missing against the database."""
        db.execute(text("""
            UPDATE source_inventory s SET status = 'imported', last_error = NULL
            FROM matches m JOIN providers p ON p.id = m.provider_id AND p.name = 'cricsheet'
            WHERE s.source_key = 'cricsheet' AND m.source_match_id = s.source_match_id AND s.status <> 'imported'"""))
        failed = self._failed_from_sync_history(db)
        if failed:
            db.execute(text("""UPDATE source_inventory SET status = 'failed', last_error = :err
                               WHERE source_key = 'cricsheet' AND source_match_id = :sid AND status <> 'imported'"""),
                       [{"sid": k, "err": v} for k, v in failed.items()])
        db.execute(text("""UPDATE source_inventory s SET status = 'missing' WHERE s.source_key = 'cricsheet'
                           AND s.status = 'available'"""))
        out = dict(db.execute(text("""SELECT status, count(*) FROM source_inventory WHERE source_key = 'cricsheet'
                                      GROUP BY 1""")).all())
        out["in_db_not_listed"] = db.scalar(text("""
            SELECT count(*) FROM matches m JOIN providers p ON p.id = m.provider_id AND p.name = 'cricsheet'
            WHERE NOT EXISTS (SELECT 1 FROM source_inventory s WHERE s.source_key = 'cricsheet'
                              AND s.source_match_id = m.source_match_id)""")) or 0
        return {k: int(v) for k, v in out.items()}

    @staticmethod
    def _failed_from_sync_history(db: Session) -> Dict[str, str]:
        out: Dict[str, str] = {}
        for (files,) in db.execute(text("""SELECT failed_files FROM sync_history WHERE failed_files IS NOT NULL
                                           ORDER BY started_at""")):
            for f in files or []:
                sid = Path(str(f.get("file", ""))).stem
                if sid:
                    out[sid] = f"{f.get('stage', '')}: {f.get('error', '')}"[:1000]
        return out

    # ------------------------------------------------------------------ recovery

    def import_missing(self, db: Session, limit: Optional[int] = None, statuses=("missing", "failed")) -> Dict[str, int]:
        """Import inventory rows not in CPI from the locally extracted archive, incrementally."""
        from app.ingestion.importer import MatchImporter
        from app.ingestion.providers.cricsheet import CricsheetParser

        q = select(SourceInventoryItem).where(SourceInventoryItem.source_key == SOURCE_KEY,
                                              SourceInventoryItem.status.in_(statuses)).order_by(SourceInventoryItem.start_date)
        if limit:
            q = q.limit(limit)
        todo = db.execute(q).scalars().all()
        parser, importer = CricsheetParser(), MatchImporter(db)
        counts = {"attempted": len(todo), "imported": 0, "failed": 0, "needs_download": 0}
        for item in todo:
            item.attempts += 1
            item.last_attempt_at = datetime.utcnow()
            path = self.gamedata_dir / f"{item.source_match_id}.json"
            if not path.exists():
                item.last_error = "Not in the local archive; queued a Cricsheet sync to download it."
                counts["needs_download"] += 1
                continue
            try:
                with db.begin_nested():
                    parsed, _ = parser.parse_file(path)
                    importer.import_match(parsed, force=True)
                item.status, item.last_error = "imported", None
                counts["imported"] += 1
            except Exception as exc:  # noqa: BLE001 - recorded per match, never aborts the batch
                item.status, item.last_error = "failed", str(exc)[:1000]
                counts["failed"] += 1
        if counts["needs_download"]:
            s = db.get(SyncSettings, 1)
            if s is not None:
                s.manual_requested_at = datetime.utcnow()
        if counts["imported"]:
            from app.services.data_version import clear_analytics_caches
            clear_analytics_caches()
        log_event(db, SOURCE_KEY, "import_missing", "ok" if not counts["failed"] else "partial", "", **counts)
        return counts

    def check_upstream(self, db: Session, timeout: float = 10.0) -> Dict[str, object]:
        """HEAD the archive and report whether Cricsheet has published a newer one than CPI imported."""
        src = db.scalar(select(SyncSource).where(SyncSource.source_key == "cricsheet_all"))
        if src is None:
            return {"status": "unconfigured"}
        try:
            r = httpx.head(src.archive_url, timeout=timeout, follow_redirects=True)
            remote = r.headers.get("last-modified")
        except httpx.HTTPError as exc:
            return {"status": "unreachable", "error": str(exc)[:300]}
        changed = bool(remote and src.last_modified and remote != src.last_modified)
        return {"status": "newer_available" if changed else "up_to_date", "remote_last_modified": remote,
                "imported_last_modified": src.last_modified,
                "last_imported_at": src.last_imported_at.isoformat() if src.last_imported_at else None}
