"""Consolidate venue rows only when their Cricsheet source IDs match exactly."""
import csv
from pathlib import Path
from sqlalchemy import select, update, delete
from app.db.session import SessionLocal
from app.models.models import Venue, VenueAlias, Match

ROOT = Path(__file__).resolve().parents[2]


def main():
    with (ROOT / "data/reference/cricsheet/venues.csv").open(newline="", encoding="utf-8-sig") as f:
        registry = {r["identifier"]: r for r in csv.DictReader(f)}
    with (ROOT / "data/reference/cricsheet/venue_names.csv").open(newline="", encoding="utf-8-sig") as f:
        names = list(csv.DictReader(f))
    db = SessionLocal()
    merged = alias_added = matches_relinked = 0
    try:
        groups = {}
        for venue in db.execute(select(Venue).where(Venue.source_venue_id.isnot(None))).scalars():
            groups.setdefault(venue.source_venue_id, []).append(venue)
        for source_id, venues in groups.items():
            ref = registry.get(source_id, {})
            preferred_name = (ref.get("unique_name") or ref.get("name") or "").strip()
            canonical = next((v for v in venues if preferred_name and v.canonical_name == preferred_name), venues[0])
            canonical.canonical_name = preferred_name or canonical.canonical_name
            if not canonical.city:
                canonical.city = next((v.city for v in venues if v.city), None)
            if not canonical.country:
                canonical.country = next((v.country for v in venues if v.country), None)
            alias_names = {v.name for v in venues}
            alias_names.update(r["name"].strip() for r in names if r["identifier"] == source_id and r.get("name"))
            existing = {a.source_name.casefold() for a in db.execute(select(VenueAlias).where(VenueAlias.source_venue_id == source_id)).scalars()}
            for alias in alias_names:
                if alias and alias.casefold() != canonical.canonical_name.casefold() and alias.casefold() not in existing:
                    db.add(VenueAlias(venue_id=canonical.id, source_venue_id=source_id, source_name=alias))
                    existing.add(alias.casefold()); alias_added += 1
            duplicates = [v for v in venues if v.id != canonical.id]
            for duplicate in duplicates:
                # Existing aliases on the duplicate are moved if not already present.
                for alias in db.execute(select(VenueAlias).where(VenueAlias.venue_id == duplicate.id)).scalars().all():
                    if alias.source_name.casefold() in existing:
                        db.delete(alias)
                    else:
                        alias.venue_id = canonical.id; existing.add(alias.source_name.casefold())
                # Flush alias moves/deletes before removing their referenced venue.
                db.flush()
                changed = db.execute(update(Match).where(Match.venue_id == duplicate.id).values(venue_id=canonical.id)).rowcount or 0
                matches_relinked += changed
                db.delete(duplicate); merged += 1
                db.flush()
        db.commit()
        print({"duplicate_venue_rows_merged": merged, "aliases_added": alias_added, "matches_relinked": matches_relinked})
    except Exception:
        db.rollback(); raise
    finally:
        db.close()


if __name__ == "__main__": main()
