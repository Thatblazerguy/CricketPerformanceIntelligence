"""Move legacy `wi_` imports to their namespaced IDs without losing distinct matches.

Only removes an unprefixed row when the prefixed match has the same checksum.
Any checksum mismatch is preserved and reported as requiring manual review.
"""
import csv
import hashlib
import json
import time
from pathlib import Path

from sqlalchemy import select, delete

from app.db.session import SessionLocal
from app.models.models import (Delivery, DeliveryExtra, Match, MatchInnings,
                              Provider, RawMatch, Wicket)

ROOT = Path(__file__).resolve().parents[2]
GAMEDATA = ROOT / "gamedata"
REPORTS = ROOT / "data" / "reports"


def remove_match_children(db, match_id: str) -> None:
    innings_ids = list(db.execute(select(MatchInnings.id).where(MatchInnings.match_id == match_id)).scalars())
    if not innings_ids:
        return
    delivery_ids = list(db.execute(select(Delivery.id).where(Delivery.innings_id.in_(innings_ids))).scalars())
    if delivery_ids:
        db.execute(delete(DeliveryExtra).where(DeliveryExtra.delivery_id.in_(delivery_ids)))
        db.execute(delete(Wicket).where(Wicket.delivery_id.in_(delivery_ids)))
        db.execute(delete(Delivery).where(Delivery.id.in_(delivery_ids)))
    db.execute(delete(MatchInnings).where(MatchInnings.id.in_(innings_ids)))


def main() -> None:
    REPORTS.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%S%z")
    log_path = REPORTS / f"namespace_reconciliation_{stamp}.csv"
    db = SessionLocal()
    actions = []
    try:
        provider = db.execute(select(Provider).where(Provider.name == "cricsheet")).scalar_one()
        for path in sorted(GAMEDATA.glob("wi_*.json")):
            legacy_id = path.stem[3:]
            namespaced_id = path.stem
            checksum = hashlib.sha256(path.read_bytes()).hexdigest()
            prefixed = db.execute(select(Match).where(Match.provider_id == provider.id,
                                                      Match.source_match_id == namespaced_id)).scalar_one_or_none()
            legacy = db.execute(select(Match).where(Match.provider_id == provider.id,
                                                     Match.source_match_id == legacy_id)).scalar_one_or_none()
            if prefixed is None:
                actions.append([path.name, legacy_id, namespaced_id, checksum, "missing_prefixed_row"])
                continue
            if prefixed.raw_source_checksum != checksum:
                raise RuntimeError(f"Namespaced row checksum differs from source: {path.name}")
            if legacy is None:
                actions.append([path.name, legacy_id, namespaced_id, checksum, "already_namespaced"])
                continue
            if legacy.raw_source_checksum != checksum:
                actions.append([path.name, legacy_id, namespaced_id, checksum, "preserved_distinct_match"])
                continue
            # Exact source checksum proves the old and namespaced rows are duplicate copies.
            remove_match_children(db, legacy.id)
            db.execute(delete(Match).where(Match.id == legacy.id))
            db.execute(delete(RawMatch).where(RawMatch.provider_id == provider.id,
                                              RawMatch.source_match_id == legacy_id,
                                              RawMatch.checksum == checksum))
            actions.append([path.name, legacy_id, namespaced_id, checksum, "removed_exact_legacy_duplicate"])
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    with log_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["source_file", "legacy_id", "namespaced_id", "source_sha256", "action"])
        writer.writerows(actions)
    print(f"Reconciled {len(actions)} prefixed source files; "
          f"removed {sum(row[-1] == 'removed_exact_legacy_duplicate' for row in actions)} checksum-identical legacy rows; "
          f"log={log_path}")


if __name__ == "__main__":
    main()
