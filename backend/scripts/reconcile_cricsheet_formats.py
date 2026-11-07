"""Reconcile source MDM/ODM classifications in existing match rows.

The change affects match metadata only; deliveries are unchanged, so this uses
bulk row updates rather than destructive match reimports.
"""
import csv
import json
import time
from pathlib import Path

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.models import Match, Provider

ROOT = Path(__file__).resolve().parents[2]
GAMEDATA = ROOT / "gamedata"
REPORTS = ROOT / "data" / "reports"


def main():
    desired = {}
    for path in GAMEDATA.glob("*.json"):
        info = json.loads(path.read_bytes()).get("info", {})
        if info.get("match_type") in {"MDM", "ODM"}:
            desired[path.stem] = info["match_type"]

    db = SessionLocal()
    try:
        provider_id = db.execute(select(Provider.id).where(Provider.name == "cricsheet")).scalar_one()
        matches = db.execute(select(Match.id, Match.source_match_id, Match.match_format)
                             .where(Match.provider_id == provider_id,
                                    Match.source_match_id.in_(desired))).all()
        by_source = {source_id: (match_id, fmt) for match_id, source_id, fmt in matches}
        changes = [{"id": by_source[source][0], "match_format": fmt}
                   for source, fmt in desired.items()
                   if source in by_source and by_source[source][1] != fmt]
        db.bulk_update_mappings(Match, changes)
        db.commit()
        missing = sorted(set(desired) - set(by_source))
        stamp = time.strftime("%Y%m%dT%H%M%S%z")
        REPORTS.mkdir(parents=True, exist_ok=True)
        log_path = REPORTS / f"format_reconciliation_{stamp}.csv"
        with log_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["source_match_id", "target_format", "action"])
            for source, fmt in sorted(desired.items()):
                previous = by_source.get(source)
                action = "missing" if previous is None else ("updated" if previous[1] != fmt else "already_correct")
                writer.writerow([source, fmt, action])
        print(f"Source MDM/ODM files={len(desired)}; updated={len(changes)}; missing={len(missing)}; log={log_path}")
        if missing:
            print("Missing IDs:", ", ".join(missing[:20]))
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
