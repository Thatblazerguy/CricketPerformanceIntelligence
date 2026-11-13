"""Backfill Test/MDM draws from retained Cricsheet JSON source files."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.db.session import SessionLocal
from app.models.models import Match, Provider


def main():
    db = SessionLocal()
    try:
        cricsheet = db.scalar(select(Provider).where(Provider.name.ilike("%cricsheet%")))
        query = select(Match).where(Match.match_format.in_(("Test", "MDM")), Match.winner_id.is_(None),
                                    Match.result_type.is_(None))
        if cricsheet:
            query = query.where(Match.provider_id == cricsheet.id)
        matches = db.scalars(query).all()
        updated = {"draw": 0, "no result": 0}
        unavailable = []
        for match in matches:
            source_id = str(match.source_match_id)
            candidates = [ROOT.parent / "gamedata" / f"{source_id}.json"]
            candidates.extend((ROOT.parent / "data" / "raw").glob(f"**/matches/{source_id}.json"))
            source_file = next((path for path in candidates if path.is_file()), None)
            if source_file is None:
                unavailable.append(source_id)
                continue
            try:
                source = json.loads(source_file.read_text())
            except (OSError, json.JSONDecodeError):
                unavailable.append(source_id)
                continue
            result = ((source.get("info") or {}).get("outcome") or {}).get("result")
            value = str(result or "").strip().casefold()
            if value in {"draw", "drawn"}:
                match.result_type = "draw"
                updated["draw"] += 1
            elif value in {"no result", "abandoned"}:
                match.result_type = "no result"
                updated["no result"] += 1
        db.commit()
        print({"scanned": len(matches), "updated": updated, "source_unavailable": len(unavailable),
               "unresolved_examples": unavailable[:20]})
    finally:
        db.close()


if __name__ == "__main__":
    main()
