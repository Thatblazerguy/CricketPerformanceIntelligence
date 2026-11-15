"""Idempotently backfill player nationality evidence and write an audit report."""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta
from pathlib import Path

import httpx
from sqlalchemy import select

from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.models import (Player, PlayerAttribute, PlayerNationalityEvidence, Match, MatchInnings,
                               Delivery, PlayerAlias, PlayerExternalProfile, Provider)
from app.services.nationality import backfill_nationalities, _record


async def run() -> None:
    engine = create_engine(settings.DATABASE_URL)
    with Session(engine) as db:
        before = {
            "players": db.scalar(select(func.count()).select_from(Player)) or 0,
            "matches": db.scalar(select(func.count()).select_from(Match)) or 0,
            "innings": db.scalar(select(func.count()).select_from(MatchInnings)) or 0,
            "deliveries": db.scalar(select(func.count()).select_from(Delivery)) or 0,
        }
        result = backfill_nationalities(db)
        if "--cache-api-attempts" in sys.argv:
            # The completed first backfill queried these unresolved names; persist the
            # negative-result cache so reruns do not repeat the same provider requests.
            for item in result["unresolved"]:
                cached = db.scalar(select(PlayerNationalityEvidence.id).where(
                    PlayerNationalityEvidence.player_id == item["id"],
                    PlayerNationalityEvidence.source == "cricketdatabase_exact_name",
                    PlayerNationalityEvidence.verification_status == "unresolved").limit(1))
                if not cached:
                    _record(db, item["id"], "Unknown", "cricketdatabase_exact_name", "unresolved", "low",
                            details={"exact_name_lookup_attempted": True,
                                     "result": "no unique exact player or nationality returned"})
        # External provider is strictly a fallback and only receives players still unresolved.
        api_resolved = 0
        api_attempted = 0
        if "--skip-api" not in sys.argv and settings.CRICKET_DATABASE_API_KEY and result["unresolved"]:
            retry_after = datetime.utcnow() - timedelta(days=30)
            attempted_recently = set(db.scalars(select(PlayerNationalityEvidence.player_id).where(
                PlayerNationalityEvidence.source == "cricketdatabase_exact_name",
                PlayerNationalityEvidence.verification_status == "unresolved",
                PlayerNationalityEvidence.created_at >= retry_after)).all())
            pending_api = [row for row in result["unresolved"] if row["id"] not in attempted_recently]
            semaphore = asyncio.Semaphore(10)
            headers = {"Authorization": f"Bearer {settings.CRICKET_DATABASE_API_KEY}"}
            base = settings.CRICKET_DATABASE_BASE_URL.rstrip("/")
            normalize = lambda value: " ".join("".join(c.lower() if c.isalnum() else " " for c in value).split())

            async def fetch_name(client, row):
                async with semaphore:
                    try:
                        response = await client.get(f"{base}/players", params={"q": row["name"]}, headers=headers)
                        response.raise_for_status()
                        matches = [p for p in response.json().get("data", [])
                                   if normalize(str(p.get("name", ""))) == normalize(row["name"])]
                        if len(matches) != 1:
                            return row["id"], None, None
                        item = matches[0]
                        provider_id = str(item.get("player") or item.get("id") or "")
                        if not provider_id:
                            return row["id"], None, None
                        detail = await client.get(f"{base}/players/{provider_id}", headers=headers)
                        if detail.is_success:
                            item = detail.json().get("data", item)
                        nationality = item.get("nationality") or item.get("country")
                        if isinstance(nationality, dict):
                            nationality = nationality.get("name") or nationality.get("country")
                        return row["id"], provider_id, str(nationality).strip() if nationality else None
                    except (httpx.HTTPError, ValueError, TypeError):
                        return row["id"], None, None

            provider = db.scalar(select(Provider).where(Provider.name == "cricketdatabase"))
            if provider is None:
                provider = Provider(name="cricketdatabase", base_url=base)
                db.add(provider)
                db.flush()
            async with httpx.AsyncClient(timeout=8.0) as client:
                batch_size = 100
                for start in range(0, len(pending_api), batch_size):
                    batch = pending_api[start:start + batch_size]
                    found = await asyncio.gather(*(fetch_name(client, item) for item in batch))
                    api_attempted += len(batch)
                    for player_id, provider_player_id, nationality in found:
                        if not provider_player_id or not nationality:
                            _record(db, player_id, "Unknown", "cricketdatabase_exact_name", "unresolved", "low",
                                    details={"exact_name_lookup_attempted": True,
                                             "result": "no unique exact player or nationality returned"})
                            continue
                        player = db.get(Player, player_id)
                        alias = db.scalar(select(PlayerAlias).where(PlayerAlias.provider_id == provider.id,
                            PlayerAlias.source_player_id == provider_player_id).limit(1))
                        if alias is not None and alias.player_id != player_id:
                            _record(db, player_id, nationality, "cricketdatabase_exact_name", "conflict", "medium",
                                    details={"provider_player_id": provider_player_id,
                                             "already_mapped_to_player_id": alias.player_id})
                            continue
                        if alias is None:
                            db.add(PlayerAlias(player_id=player_id, provider_id=provider.id,
                                source_player_id=provider_player_id, source_name=player.canonical_name))
                        profile = db.scalar(select(PlayerExternalProfile).where(
                            PlayerExternalProfile.provider_id == provider.id,
                            PlayerExternalProfile.provider_player_id == provider_player_id).limit(1))
                        if profile is None:
                            db.add(PlayerExternalProfile(player_id=player_id, provider_id=provider.id,
                                provider_player_id=provider_player_id, basic_stats={"nationality": nationality,
                                                                                 "country": nationality}))
                        _record(db, player_id, nationality, "cricketdatabase_exact_name", "provider_reported", "medium",
                                details={"provider_player_id": provider_player_id})
                        attr = db.scalar(select(PlayerAttribute).where(PlayerAttribute.player_id == player_id,
                            PlayerAttribute.attribute_type == "nationality").limit(1))
                        if attr is None:
                            db.add(PlayerAttribute(player_id=player_id, attribute_type="nationality",
                                attribute_value=nationality, source="cricketdatabase_exact_name", confidence="medium"))
                        elif attr.attribute_value.strip().lower() in {"", "unknown", "indian", "overseas"}:
                            attr.attribute_value, attr.source, attr.confidence = nationality, "cricketdatabase_exact_name", "medium"
                        elif attr.attribute_value.casefold() != nationality.casefold():
                            _record(db, player_id, nationality, "cricketdatabase_exact_name", "conflict", "medium",
                                    details={"conflicts_with_existing_value": attr.attribute_value})
                        api_resolved += 1
                    db.flush()
                    print(f"Cricket Database fallback: {min(start + len(batch), len(pending_api))}/{len(pending_api)} queried", flush=True)
        db.flush()
        db.commit()

        rows = db.execute(select(Player.id, Player.canonical_name, PlayerAttribute.attribute_value,
                PlayerAttribute.source, PlayerAttribute.confidence)
            .join(PlayerAttribute, PlayerAttribute.player_id == Player.id)
            .where(PlayerAttribute.attribute_type == "nationality")
            .order_by(Player.canonical_name)).all()
        by_player = {}
        for player_id, name, value, source, confidence in rows:
            by_player.setdefault(player_id, []).append((value, source, confidence))
        resolved_ids = {player_id for player_id, vals in by_player.items()
                        if any(v and v.lower() != "unknown" for v, _, _ in vals)}
        resolved_names_count = len(resolved_ids)
        unresolved_rows = [(player.canonical_name, player.id) for player in db.scalars(select(Player)).all()
                           if player.id not in resolved_ids]
        conflicts = db.execute(select(Player.canonical_name, PlayerNationalityEvidence.nationality,
                PlayerNationalityEvidence.source, PlayerNationalityEvidence.details)
            .join(PlayerNationalityEvidence, PlayerNationalityEvidence.player_id == Player.id)
            .where(PlayerNationalityEvidence.verification_status == "conflict")
            .order_by(Player.canonical_name)).all()
        evidence_count = db.scalar(select(func.count()).select_from(PlayerNationalityEvidence)) or 0
        cached_api_count = db.scalar(select(func.count()).select_from(PlayerNationalityEvidence).where(
            PlayerNationalityEvidence.source == "cricketdatabase_exact_name",
            PlayerNationalityEvidence.verification_status == "unresolved")) or 0
        final_counts = {
            "players": db.scalar(select(func.count()).select_from(Player)) or 0,
            "matches": db.scalar(select(func.count()).select_from(Match)) or 0,
            "innings": db.scalar(select(func.count()).select_from(MatchInnings)) or 0,
            "deliveries": db.scalar(select(func.count()).select_from(Delivery)) or 0,
        }
        coverage_pct = 100 * resolved_names_count / max(final_counts["players"], 1)
        lines = [
            "# Player Nationality Coverage Audit", "",
            "Generated by `backend/scripts/backfill_player_nationality.py`.", "",
            "## Coverage", "",
            f"- Total players: {final_counts['players']}",
            f"- Players with known nationality: {resolved_names_count} ({coverage_pct:.2f}%)",
            f"- Unresolved (`Unknown` / no reliable evidence): {len(unresolved_rows)}",
            f"- Conflicting evidence cases: {len({row[0] for row in conflicts})}",
            f"- Stored evidence records: {evidence_count}",
            f"- Newly resolved by Cricket Database API during this run: {api_resolved}", "",
            f"- Cricket Database exact-name queries attempted: {api_attempted}", "",
            f"- Cached unresolved Cricket Database lookups: {cached_api_count}", "",
            "## Data integrity", "",
            f"- Players before/after: {before['players']} / {final_counts['players']}",
            f"- Matches before/after: {before['matches']} / {final_counts['matches']}",
            f"- Innings before/after: {before['innings']} / {final_counts['innings']}",
            f"- Deliveries before/after: {before['deliveries']} / {final_counts['deliveries']}",
            "- The backfill updates nationality attributes/evidence only; it does not modify match or delivery rows.", "",
            "## Conflicting evidence", "",
        ]
        if conflicts:
            lines += ["| Player | Conflicting affiliation | Source | Details |", "|---|---|---|---|"]
            for name, nationality, source, details in conflicts:
                lines.append(f"| {name.replace('|', '/')} | {nationality.replace('|', '/')} | {source} | `{details}` |")
        else:
            lines.append("No conflicting evidence was recorded.")
        lines += ["", "## Unresolved records", ""]
        if unresolved_rows:
            lines += ["| Player | CPI player ID |", "|---|---|"]
            lines += [f"| {name.replace('|', '/')} | `{player_id}` |" for name, player_id in unresolved_rows]
        else:
            lines.append("No unresolved player records.")
        lines += ["", "## Method", "",
            "Existing high-confidence/verified nationality attributes are retained. Test, ODI and T20I appearances infer represented national affiliation from the actual match sides. Domestic/franchise team membership, birthplace and IPL overseas status are not treated as nationality evidence. Multiple affiliations are retained with date ranges; unresolved simultaneous evidence is flagged instead of guessed. Cricket Database lookups use exact normalized player-name matches and are cached against the existing CPI player identity.", ""]
        report = Path(__file__).resolve().parents[2] / "NATIONALITY_AUDIT.md"
        report.write_text("\n".join(lines), encoding="utf-8")
        print(f"Nationality backfill complete: {resolved_names_count}/{final_counts['players']} known; {len(unresolved_rows)} unresolved; {len({row[0] for row in conflicts})} conflicting.")
        print(f"Audit: {report}")


if __name__ == "__main__":
    asyncio.run(run())
