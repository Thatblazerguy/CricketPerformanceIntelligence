"""Apply Cricsheet people/names and venue reference CSVs by stable IDs only."""
import csv
from pathlib import Path
from sqlalchemy import select
from app.db.session import SessionLocal
from app.models.models import Player, PlayerAlias, PlayerNameAlias, PlayerAttribute, Provider, Venue, VenueAlias

ROOT = Path(__file__).resolve().parents[2]
REF = ROOT / "data/reference/cricsheet"


def read_csv(name):
    with (REF / name).open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def main():
    names, people = read_csv("names.csv"), read_csv("people.csv")
    venue_names, venues = read_csv("venue_names.csv"), read_csv("venues.csv")
    db = SessionLocal()
    counts = {"player_aliases": 0, "player_attributes": 0, "venue_aliases": 0, "venues_updated": 0, "unmatched_ids": 0}
    try:
        # Resolve people strictly through the existing Cricsheet registry identifier.
        provider = db.execute(select(Provider).where(Provider.name == "cricsheet")).scalar_one_or_none()
        player_by_source = {source_id: player_id for source_id, player_id in db.execute(
            select(PlayerAlias.source_player_id, PlayerAlias.player_id).where(PlayerAlias.provider_id == provider.id)
        ).all()} if provider else {}
        by_id = {}
        for row in people:
            by_id[row["identifier"]] = row
        existing_attrs = {(pid, kind) for pid, kind in db.execute(select(PlayerAttribute.player_id, PlayerAttribute.attribute_type)).all()}
        existing_names = {(pid, name.casefold()) for pid, name in db.execute(select(PlayerNameAlias.player_id, PlayerNameAlias.alias)).all()}
        for row in people:
            pid = player_by_source.get(row["identifier"])
            if not pid:
                counts["unmatched_ids"] += 1
                continue
            unique_name = (row.get("unique_name") or "").strip()
            if unique_name and (pid, "full_name") not in existing_attrs:
                db.add(PlayerAttribute(player_id=pid, attribute_type="full_name", attribute_value=unique_name, source="Cricsheet people.csv", confidence="medium"))
                existing_attrs.add((pid, "full_name")); counts["player_attributes"] += 1
        for row in names:
            pid = player_by_source.get(row["identifier"])
            alias = (row.get("name") or "").strip()
            if pid and alias and (pid, alias.casefold()) not in existing_names:
                db.add(PlayerNameAlias(player_id=pid, alias=alias, source="Cricsheet names.csv")); existing_names.add((pid, alias.casefold())); counts["player_aliases"] += 1

        venue_by_id = {v.source_venue_id: v for v in db.execute(select(Venue).where(Venue.source_venue_id.isnot(None))).scalars()}
        venue_rows = {v["identifier"]: v for v in venues}
        for identifier, row in venue_rows.items():
            venue = venue_by_id.get(identifier)
            if venue:
                canonical = (row.get("unique_name") or row.get("name") or "").strip()
                if canonical and venue.canonical_name != canonical:
                    venue.canonical_name = canonical; counts["venues_updated"] += 1
        existing_va = {(v_id, name.casefold()) for v_id, name in db.execute(select(VenueAlias.venue_id, VenueAlias.source_name)).all()}
        for row in venue_names:
            venue = venue_by_id.get(row["identifier"])
            alias = (row.get("name") or "").strip()
            if venue and alias and (venue.id, alias.casefold()) not in existing_va:
                db.add(VenueAlias(venue_id=venue.id, source_venue_id=row["identifier"], source_name=alias)); existing_va.add((venue.id, alias.casefold())); counts["venue_aliases"] += 1
        db.commit()
        print(counts)
    except Exception:
        db.rollback(); raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
