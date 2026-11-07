"""
Ingest ALL gamedata files into the CPI database.

Reads every JSON file in the gamedata/ directory (Test, ODI, T20, MDM, ODM, IT20, etc.),
parses via CricsheetParser, and imports via MatchImporter (idempotent/checksum-based).

Usage:
    PYTHONPATH=backend backend/.venv/bin/python backend/scripts/ingest_gamedata.py
    PYTHONPATH=backend backend/.venv/bin/python backend/scripts/ingest_gamedata.py --limit 500
"""
import sys
import logging
import time
import csv
import argparse
import json
from pathlib import Path

# Ensure project root is on the path
sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("ingest_gamedata")

from app.db.session import SessionLocal
from app.ingestion.providers.cricsheet import CricsheetParser, CricsheetParseError
from app.ingestion.importer import MatchImporter


GAMEDATA_DIR = Path(__file__).parent.parent.parent / "gamedata"
BATCH_SIZE = 500
LOG_EVERY = 100


def _get_source_match_id(path: Path) -> str:
    """Cricsheet's `wi_` prefix is part of the ID namespace and must be preserved."""
    return path.stem


def run_ingestion(limit: int = None, batch_size: int = BATCH_SIZE, files=None, match_types=None, force: bool = False):
    if not GAMEDATA_DIR.exists():
        logger.error("gamedata/ directory not found at: %s", GAMEDATA_DIR)
        sys.exit(1)

    all_files = sorted((GAMEDATA_DIR / name) if not Path(name).is_absolute() else Path(name) for name in files) if files else sorted(GAMEDATA_DIR.glob("*.json"))
    if match_types:
        wanted = set(match_types)
        all_files = [path for path in all_files
                     if json.loads(path.read_bytes()).get("info", {}).get("match_type") in wanted]
        logger.info("Filtered to %d files with source match types: %s", len(all_files), ", ".join(sorted(wanted)))
    total_files = len(all_files)
    logger.info("Found %d JSON files in %s", total_files, GAMEDATA_DIR)

    if limit:
        all_files = all_files[:limit]
        logger.info("Processing first %d files (--limit applied)", limit)

    parser = CricsheetParser()

    stats = {
        "discovered": len(all_files),
        "inserted": 0,
        "updated": 0,
        "skipped": 0,
        "failed": 0,
    }
    errors = []
    # Keep a durable file-level record so interrupted/repeated runs remain auditable.
    report_dir = Path(__file__).parent.parent.parent / "data" / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    run_stamp = time.strftime("%Y%m%dT%H%M%S%z")
    log_path = report_dir / f"ingestion_file_log_{run_stamp}.csv"
    log_file = log_path.open("w", newline="", encoding="utf-8")
    file_log = csv.writer(log_file)
    file_log.writerow(["timestamp", "file", "source_match_id", "checksum", "result", "error"])
    log_file.flush()

    start_time = time.time()

    for batch_start in range(0, len(all_files), batch_size):
        batch = all_files[batch_start : batch_start + batch_size]
        db = SessionLocal()
        try:
            importer = MatchImporter(db)
            for i, path in enumerate(batch, start=1):
                global_i = batch_start + i
                try:
                    match, _warnings = parser.parse_file(path)

                    result = importer.import_match(match, force=force)
                    stats[result] += 1
                    file_log.writerow([time.strftime("%Y-%m-%dT%H:%M:%S%z"), path.name, match.source_match_id, match.checksum, result, ""])

                except CricsheetParseError as exc:
                    stats["failed"] += 1
                    err = f"[ParseError] {path.name}: {exc}"
                    errors.append(err)
                    logger.warning(err)
                    file_log.writerow([time.strftime("%Y-%m-%dT%H:%M:%S%z"), path.name, _get_source_match_id(path), "", "failed", err])
                except Exception as exc:
                    stats["failed"] += 1
                    err = f"[Error] {path.name}: {type(exc).__name__}: {exc}"
                    errors.append(err)
                    logger.warning(err)
                    file_log.writerow([time.strftime("%Y-%m-%dT%H:%M:%S%z"), path.name, _get_source_match_id(path), "", "failed", err])

                if global_i % LOG_EVERY == 0:
                    log_file.flush()

                if global_i % LOG_EVERY == 0:
                    elapsed = time.time() - start_time
                    rate = global_i / elapsed if elapsed > 0 else 0
                    logger.info(
                        "Progress: %d/%d files (%.0f/s) | inserted=%d updated=%d skipped=%d failed=%d",
                        global_i,
                        len(all_files),
                        rate,
                        stats["inserted"],
                        stats["updated"],
                        stats["skipped"],
                        stats["failed"],
                    )

            db.commit()
            logger.info(
                "Committed batch %d–%d",
                batch_start + 1,
                batch_start + len(batch),
            )
        except Exception as exc:
            db.rollback()
            logger.error("Batch %d–%d failed and was rolled back: %s", batch_start + 1, batch_start + len(batch), exc)
            stats["failed"] += len(batch)
        finally:
            db.close()

    elapsed_total = time.time() - start_time
    log_file.flush()
    log_file.close()
    logger.info("Ingestion complete in %.1f seconds.", elapsed_total)
    print("\n=== Ingestion Complete ===")
    print(f"  Discovered : {stats['discovered']}")
    print(f"  Inserted   : {stats['inserted']}")
    print(f"  Updated    : {stats['updated']}")
    print(f"  Skipped    : {stats['skipped']}")
    print(f"  Failed     : {stats['failed']}")
    print(f"  Duration   : {elapsed_total:.1f}s")
    if errors:
        print(f"\nFirst {min(20, len(errors))} errors:")
        for e in errors[:20]:
            print(f"  {e}")
    return stats


def main():
    import argparse

    ap = argparse.ArgumentParser(description="Ingest ALL gamedata into CPI DB")
    ap.add_argument("--limit", type=int, default=None, help="Max files to process")
    ap.add_argument("--batch-size", type=int, default=BATCH_SIZE, help=f"Batch size (default {BATCH_SIZE})")
    ap.add_argument("--files", nargs="+", help="Process only these filenames from gamedata/ (useful for targeted replays)")
    ap.add_argument("--match-types", nargs="+", help="Filter by Cricsheet info.match_type (for parser remapping)")
    ap.add_argument("--force", action="store_true", help="Reprocess unchanged checksums with updated parser rules")
    args = ap.parse_args()

    run_ingestion(limit=args.limit, batch_size=args.batch_size, files=args.files,
                  match_types=args.match_types, force=args.force)


if __name__ == "__main__":
    main()
