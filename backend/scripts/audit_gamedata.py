"""Reconcile the Cricsheet archive against the CPI database and pre-migration dump."""
from __future__ import annotations

import csv
import hashlib
import json
import subprocess
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

from sqlalchemy import text

from app.db.session import engine
from app.ingestion.providers.cricsheet import CricsheetParser

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "gamedata"
BACKUP = ROOT / "data/backups/cpi_db_pre_cricsheet_migration_20261107.dump"


def canonical_id(path: Path) -> str:
    # Prefixes such as `wi_` define distinct Cricsheet ID namespaces.
    return path.stem


def format_name(info: dict) -> str:
    kind = info.get("match_type", "Unknown")
    if kind == "IT20" or (kind == "T20" and info.get("team_type") == "international"):
        return "T20I"
    if kind == "T20":
        return "T20"
    return kind


def old_ids() -> set[str]:
    if not BACKUP.exists():
        return set()
    with tempfile.NamedTemporaryFile(mode="w+", suffix=".sql") as dump:
        subprocess.run(["pg_restore", "--data-only", "--table=providers", "--table=matches", "--file", dump.name, str(BACKUP)], check=True)
        dump.seek(0)
        table_rows = {}
        for line in dump:
            if not line.startswith("COPY public."):
                continue
            table = line.split(" ", 2)[1].removeprefix("public.")
            columns = line[line.index("(") + 1:line.index(")")].split(", ")
            rows = []
            for row in dump:
                if row.strip() == "\\.":
                    break
                rows.append(row.rstrip("\n").split("\t"))
            table_rows[table] = (columns, rows)
        provider_cols, provider_rows = table_rows.get("providers", ([], []))
        if not provider_cols:
            return set()
        provider_id = next((row[provider_cols.index("id")] for row in provider_rows
                            if row[provider_cols.index("name")] == "cricsheet"), None)
        match_cols, match_rows = table_rows.get("matches", ([], []))
        if not provider_id or not match_cols:
            return set()
        return {row[match_cols.index("source_match_id")] for row in match_rows
                if row[match_cols.index("provider_id")] == provider_id}


def main() -> None:
    files = sorted(DATA.glob("*.json"))
    valid = []
    failures = []
    duplicates: dict[str, list[str]] = defaultdict(list)
    by_format = Counter()
    by_year = Counter()
    by_competition = Counter()
    innings_count = delivery_count = 0
    checksums: dict[str, list[str]] = defaultdict(list)
    parser = CricsheetParser()
    for path in files:
        try:
            raw = path.read_bytes()
            data = json.loads(raw)
            parser.parse_bytes(raw, path.name)
            info = data["info"]
            if len(info.get("teams", [])) != 2 or not data.get("innings"):
                raise ValueError("missing two teams or innings")
            match_id = canonical_id(path)
            duplicates[match_id].append(path.name)
            checksums[hashlib.sha256(raw).hexdigest()].append(path.name)
            valid.append((path, data, match_id, hashlib.sha256(raw).hexdigest()))
            by_format[format_name(info)] += 1
            year = str(info.get("season") or (info.get("dates") or ["Unknown"])[0][:4])
            by_year[year] += 1
            by_competition[str((info.get("event") or {}).get("name") or "Unspecified")] += 1
            innings_count += len(data["innings"])
            delivery_count += sum(len(over.get("deliveries", [])) for inn in data["innings"] for over in inn.get("overs", []))
        except Exception as exc:
            failures.append((path.name, str(exc)))

    with engine.connect() as conn:
        current_ids = set(conn.execute(text("SELECT source_match_id FROM matches m JOIN providers p ON p.id=m.provider_id WHERE p.name='cricsheet'")).scalars())
        db_counts = dict(conn.execute(text("SELECT m.match_format, count(*) FROM matches m JOIN providers p ON p.id=m.provider_id WHERE p.name='cricsheet' GROUP BY m.match_format")).all())
        innings_db = conn.execute(text("SELECT count(*) FROM match_innings i JOIN matches m ON m.id=i.match_id JOIN providers p ON p.id=m.provider_id WHERE p.name='cricsheet'")).scalar_one()
        deliveries_db = conn.execute(text("SELECT count(*) FROM deliveries d JOIN match_innings i ON i.id=d.innings_id JOIN matches m ON m.id=i.match_id JOIN providers p ON p.id=m.provider_id WHERE p.name='cricsheet'")).scalar_one()
        db_years = conn.execute(text("SELECT extract(year from m.start_date)::int, count(*) FROM matches m JOIN providers p ON p.id=m.provider_id WHERE p.name='cricsheet' GROUP BY 1 ORDER BY 1")).all()
        db_competitions = conn.execute(text("SELECT coalesce(t.name,'Unspecified'), count(*) FROM matches m JOIN providers p ON p.id=m.provider_id LEFT JOIN tournaments t ON t.id=m.tournament_id WHERE p.name='cricsheet' GROUP BY 1 ORDER BY 2 DESC, 1")).all()
    previous_ids = old_ids()
    archive_ids = {item[2] for item in valid}
    ids_by_filename = {item[2]: item[0].name for item in valid}
    imported_ids = archive_ids & current_ids
    new_ids = imported_ids - previous_ids
    duplicate_files = [names for names in duplicates.values() if len(names) > 1]
    duplicate_checksums = [names for names in checksums.values() if len(names) > 1]

    migration_log = ROOT / "data/reports/cricsheet_migration_file_status.csv"
    migration_log.parent.mkdir(parents=True, exist_ok=True)
    with migration_log.open("w", newline="", encoding="utf-8") as log_file:
        writer = csv.writer(log_file)
        writer.writerow(["file", "source_match_id", "sha256", "format", "year", "migration_status"])
        for path, data, match_id, checksum in valid:
            info = data["info"]
            year = str(info.get("season") or (info.get("dates") or ["Unknown"])[0][:4])
            status = "previously_imported" if match_id in previous_ids else "newly_imported"
            writer.writerow([path.name, match_id, checksum, format_name(info), year, status])

    lines = [
        "# Cricsheet Data Audit", "",
        "Generated by `backend/scripts/audit_gamedata.py` after reconciliation against the pre-migration database dump.", "",
        "## Import Summary", "",
        f"- Files discovered: **{len(files):,}**", f"- Structurally valid files: **{len(valid):,}**",
        f"- Unique source match IDs: **{len(archive_ids):,}**", f"- Previously imported archive matches: **{len(archive_ids & previous_ids):,}**",
        f"- Newly imported archive matches: **{len(new_ids):,}**", f"- Imported from archive after migration: **{len(imported_ids):,}**",
        f"- Duplicate match ID groups: **{len(duplicate_files):,}**", f"- Duplicate checksum groups: **{len(duplicate_checksums):,}**",
        f"- Failed/invalid files: **{len(failures):,}**", f"- Database matches by format: {', '.join(f'{k} {v:,}' for k,v in sorted(db_counts.items()))}",
        f"- Archive innings: **{innings_count:,}**", f"- Archive deliveries: **{delivery_count:,}**",
        f"- Database innings (Cricsheet): **{innings_db:,}**", f"- Database deliveries (Cricsheet): **{deliveries_db:,}**", "",
        "## Archive Matches by Format", "", "| Format | Matches |", "|---|---:|",
    ]
    lines += [f"| {k} | {v:,} |" for k, v in sorted(by_format.items())]
    lines += ["", "## Archive Matches by Year", "", "| Year | Matches |", "|---|---:|"]
    lines += [f"| {k} | {v:,} |" for k, v in sorted(by_year.items())]
    lines += ["", "## Archive Matches by Competition", "", "| Competition | Matches |", "|---|---:|"]
    for k, v in by_competition.most_common():
        lines.append("| " + k.replace("|", "\\|") + f" | {v:,} |")
    lines += ["", "## Imported Database Matches by Year", "", "| Year | Matches |", "|---|---:|"]
    lines += [f"| {year} | {count:,} |" for year, count in db_years]
    lines += ["", "## Imported Database Matches by Competition", "", "| Competition | Matches |", "|---|---:|"]
    lines += ["| " + name.replace("|", "\\|") + f" | {count:,} |" for name, count in db_competitions]
    lines += ["", "## Exceptions", "", "### Duplicate source IDs", ""]
    lines += [f"- `{', '.join(names)}`" for names in duplicate_files] or ["- None"]
    lines += ["", "### Duplicate file checksums", ""]
    lines += [f"- `{', '.join(names)}`" for names in duplicate_checksums] or ["- None"]
    lines += ["", "### Failed files", ""]
    lines += [f"- `{name}`: {reason}" for name, reason in failures] or ["- None"]
    lines += ["", "### Archive source IDs not found in database", ""]
    missing = sorted(archive_ids - current_ids)
    lines += [f"- `{ids_by_filename.get(mid, mid)}` (`{mid}`)" for mid in missing[:500]] or ["- None"]
    if len(missing) > 500: lines.append(f"- … plus {len(missing)-500:,} more")
    lines.append("")
    (ROOT / "DATA_AUDIT.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote DATA_AUDIT.md and {migration_log}: files={len(files)}, valid={len(valid)}, imported={len(imported_ids)}, missing={len(missing)}, failures={len(failures)}")


if __name__ == "__main__":
    main()
