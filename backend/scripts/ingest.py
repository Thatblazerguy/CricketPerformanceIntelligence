"""CLI ingestion script — run directly without FastAPI server."""
import sys
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

from app.db.session import SessionLocal
from app.ingestion.sync import IngestionOrchestrator
from app.core.config import settings


def main():
    import argparse
    parser = argparse.ArgumentParser(description="CPI Data Ingestion CLI")
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Maximum number of files to process (default: all)"
    )
    parser.add_argument(
        "--ipl-only", action="store_true",
        help="Ingest IPL files only"
    )
    parser.add_argument(
        "--t20i-only", action="store_true",
        help="Ingest T20I files only"
    )
    args = parser.parse_args()

    ipl_dir = Path(settings.IPL_DATA_DIR)
    t20i_dir = Path(settings.T20I_DATA_DIR)

    if args.ipl_only:
        t20i_dir = Path("/nonexistent")
    if args.t20i_only:
        ipl_dir = Path("/nonexistent")

    print(f"Starting CPI ingestion...")
    print(f"  IPL dir  : {ipl_dir} (exists: {ipl_dir.exists()})")
    print(f"  T20I dir : {t20i_dir} (exists: {t20i_dir.exists()})")
    if args.limit:
        print(f"  Limit    : {args.limit} files")

    db = SessionLocal()
    try:
        orch = IngestionOrchestrator(db, ipl_dir, t20i_dir)
        result = orch.run(limit=args.limit)
        print("\n=== Ingestion Complete ===")
        print(f"  Discovered : {result['discovered']}")
        print(f"  Inserted   : {result['inserted']}")
        print(f"  Updated    : {result['updated']}")
        print(f"  Skipped    : {result['skipped']}")
        print(f"  Failed     : {result['failed']}")
        if result.get('errors'):
            print("\nFirst errors:")
            for e in result['errors']:
                print(f"  {e}")
    finally:
        db.close()


if __name__ == "__main__":
    main()

