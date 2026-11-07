"""Nationality evidence resolution. Domestic/franchise team participation is never used."""
from __future__ import annotations

from datetime import date
from typing import Iterable

from sqlalchemy import text, select
from sqlalchemy.orm import Session

from app.models.models import Player, PlayerAttribute, PlayerNationalityEvidence, PlayerAlias, PlayerExternalProfile, Provider
from app.core.config import settings

UNKNOWN = "Unknown"
NON_NATIONAL_TEAMS = {
    "africa xi", "asia xi", "icc world xi", "world xi", "rest of the world xi",
    "icc xi", "world eleven", "africa eleven", "asia eleven",
}


def is_national_side(name: str) -> bool:
    """Exclude invitational/composite XIs that cannot establish a player's nationality."""
    return " ".join(name.casefold().replace(".", " ").split()) not in NON_NATIONAL_TEAMS


def resolve_affiliations(evidence: Iterable[dict]) -> tuple[str, list[dict]]:
    """Return a single current value or Unknown and flag ambiguous concurrent teams."""
    rows = [dict(row) for row in evidence if row.get("nationality") and row["nationality"] != UNKNOWN
            and is_national_side(row["nationality"])]
    if not rows:
        return UNKNOWN, []
    # A single represented national side is strong evidence. Preserve distinct eras as history.
    names = {r["nationality"] for r in rows}
    if len(names) == 1:
        return next(iter(names)), rows
    # Non-overlapping affiliations indicate an eligibility change. Use the latest dated appearance.
    ordered = sorted(rows, key=lambda r: (r.get("last_seen") or date.min, r["nationality"]))
    latest = ordered[-1]
    latest_date = latest.get("last_seen")
    earlier = [r for r in rows if r["nationality"] != latest["nationality"]]
    if latest_date and all(r.get("last_seen") and r["last_seen"] < (latest.get("first_seen") or latest_date) for r in earlier):
        return latest["nationality"], rows
    return UNKNOWN, rows


INTERNATIONAL_APPEARANCES_SQL = text("""
WITH appearances AS (
  SELECT d.batter_id AS player_id, i.batting_team_id AS team_id, m.id AS match_id, m.start_date
  FROM deliveries d JOIN match_innings i ON i.id=d.innings_id JOIN matches m ON m.id=i.match_id
  WHERE upper(m.match_format) IN ('TEST','ODI','T20I') AND d.batter_id IS NOT NULL AND i.batting_team_id IS NOT NULL
  UNION ALL
  SELECT d.non_striker_id, i.batting_team_id, m.id, m.start_date
  FROM deliveries d JOIN match_innings i ON i.id=d.innings_id JOIN matches m ON m.id=i.match_id
  WHERE upper(m.match_format) IN ('TEST','ODI','T20I') AND d.non_striker_id IS NOT NULL AND i.batting_team_id IS NOT NULL
  UNION ALL
  SELECT d.bowler_id,
    CASE WHEN i.batting_team_id=m.team1_id THEN m.team2_id
         WHEN i.batting_team_id=m.team2_id THEN m.team1_id END,
    m.id, m.start_date
  FROM deliveries d JOIN match_innings i ON i.id=d.innings_id JOIN matches m ON m.id=i.match_id
  WHERE upper(m.match_format) IN ('TEST','ODI','T20I') AND d.bowler_id IS NOT NULL
    AND i.batting_team_id IN (m.team1_id,m.team2_id)
)
SELECT a.player_id, t.canonical_name AS nationality, min(a.start_date) AS first_seen,
       max(a.start_date) AS last_seen, count(DISTINCT a.match_id) AS match_count
FROM appearances a JOIN teams t ON t.id=a.team_id
GROUP BY a.player_id,t.canonical_name
""")


def record_match_nationalities(db: Session, match_id: str) -> None:
    """Low-cost import hook; records evidence from this match only when format is international."""
    rows = db.execute(text("""
      SELECT m.match_format, m.start_date, p.id AS player_id, t.canonical_name AS nationality,
             count(DISTINCT d.id) AS delivery_count
      FROM matches m JOIN match_innings i ON i.match_id=m.id
      JOIN deliveries d ON d.innings_id=i.id
      JOIN players p ON p.id IN (d.batter_id,d.non_striker_id,d.bowler_id)
      JOIN teams t ON t.id=CASE WHEN p.id IN (d.batter_id,d.non_striker_id) THEN i.batting_team_id
        WHEN i.batting_team_id=m.team1_id THEN m.team2_id
        WHEN i.batting_team_id=m.team2_id THEN m.team1_id END
      WHERE m.id=:match_id AND upper(m.match_format) IN ('TEST','ODI','T20I')
      GROUP BY m.match_format,m.start_date,p.id,t.canonical_name
    """), {"match_id": match_id}).mappings()
    for row in rows:
        if not is_national_side(row["nationality"]):
            _record(db, row["player_id"], row["nationality"], "international_appearances", "excluded", "low",
                    1, row["start_date"], row["start_date"], {"match_id": match_id,
                    "exclusion_reason": "composite/invitational team is not nationality evidence"})
            continue
        _record(db, row["player_id"], row["nationality"], "international_appearances", "verified", "high",
                1, row["start_date"], row["start_date"],
                {"match_id": match_id, "format": row["match_format"], "delivery_count": int(row["delivery_count"])})
        attr = db.scalar(select(PlayerAttribute).where(PlayerAttribute.player_id == row["player_id"],
            PlayerAttribute.attribute_type == "nationality").order_by(PlayerAttribute.confidence.desc()).limit(1))
        if attr is None:
            db.add(PlayerAttribute(player_id=row["player_id"], attribute_type="nationality",
                attribute_value=row["nationality"], source="international_appearances", confidence="high",
                valid_from=row["start_date"], valid_to=row["start_date"]))
        elif (attr.attribute_value.strip().lower() in {"", "unknown", "indian", "overseas"}
              or (attr.source == "international_appearances" and not is_national_side(attr.attribute_value))):
            attr.attribute_value = row["nationality"]
            attr.source = "international_appearances"
            attr.confidence = "high"
            attr.valid_from = row["start_date"]
            attr.valid_to = row["start_date"]
        elif attr.attribute_value.casefold() != row["nationality"].casefold():
            _record(db, row["player_id"], row["nationality"], "international_appearances", "conflict", "high",
                    1, row["start_date"], row["start_date"],
                    {"match_id": match_id, "conflicts_with_existing_value": attr.attribute_value})


def _record(db: Session, player_id: str, nationality: str, source: str, status: str,
            confidence: str, evidence_count: int = 1, first_seen=None, last_seen=None, details=None):
    existing = db.scalar(select(PlayerNationalityEvidence).where(
        PlayerNationalityEvidence.player_id == player_id,
        PlayerNationalityEvidence.nationality == nationality,
        PlayerNationalityEvidence.source == source,
        PlayerNationalityEvidence.valid_from == first_seen,
        PlayerNationalityEvidence.valid_to == last_seen,
    ).limit(1))
    if existing:
        existing.verification_status = status
        existing.confidence = confidence
        existing.evidence_count = evidence_count
        existing.details = details or {}
        return existing
    row = PlayerNationalityEvidence(player_id=player_id, nationality=nationality, source=source,
        verification_status=status, confidence=confidence, evidence_count=evidence_count,
        valid_from=first_seen, valid_to=last_seen, details=details or {})
    db.add(row)
    return row


def backfill_nationalities(db: Session) -> dict:
    """Idempotently resolve current nationality and preserve all observed affiliations."""
    intl_by_player: dict[str, list[dict]] = {}
    for row in db.execute(INTERNATIONAL_APPEARANCES_SQL).mappings():
        item = dict(row)
        intl_by_player.setdefault(item["player_id"], []).append(item)

    players = db.scalars(select(Player)).all()
    unresolved, conflicts, resolved = [], [], 0
    for player in players:
        attrs = db.scalars(select(PlayerAttribute).where(
            PlayerAttribute.player_id == player.id,
            PlayerAttribute.attribute_type == "nationality",
        )).all()
        for attr in attrs:
            if attr.attribute_value.strip().casefold() in {"indian", "overseas"}:
                attr.attribute_value = UNKNOWN
                attr.source = "nationality_review_required"
                attr.confidence = "low"
        established = [a for a in attrs if a.attribute_value.strip().lower() not in {"", "unknown", "indian", "overseas"}
                       and (a.confidence == "high" or "verified" in (a.source or "").lower()
                            or (a.source or "").lower() in {"cricketdatabase", "cricketdatabase_exact_name"})]
        all_observations = intl_by_player.get(player.id, [])
        observations = [obs for obs in all_observations if is_national_side(obs["nationality"])]
        for obs in all_observations:
            excluded = not is_national_side(obs["nationality"])
            _record(db, player.id, obs["nationality"], "international_appearances",
                    "excluded" if excluded else "verified", "low" if excluded else "high",
                    int(obs["match_count"]), obs["first_seen"], obs["last_seen"],
                    {"formats": ["Test", "ODI", "T20I"], "basis": "represented match side",
                     "exclusion_reason": "composite/invitational team is not nationality evidence" if excluded else None})
        current = established[0].attribute_value.strip() if established else None
        if current and established[0].source == "international_appearances" and not is_national_side(current):
            established[0].attribute_value = UNKNOWN
            established[0].source = "nationality_review_required"
            established[0].confidence = "low"
            current = None
        if current:
            for obs in observations:
                if obs["nationality"].casefold() != current.casefold():
                    _record(db, player.id, obs["nationality"], "international_appearances", "conflict", "high",
                            int(obs["match_count"]), obs["first_seen"], obs["last_seen"],
                            {"conflicts_with_existing_verified_value": current})
                    conflicts.append(player.id)
            resolved += 1
            if player.id not in conflicts:
                stale = db.scalars(select(PlayerNationalityEvidence).where(
                    PlayerNationalityEvidence.player_id == player.id,
                    PlayerNationalityEvidence.source == "international_appearances",
                    PlayerNationalityEvidence.verification_status == "conflict",
                )).all()
                for evidence in stale:
                    evidence.verification_status = "resolved"
            continue

        inferred, history = resolve_affiliations(observations)
        if len({h["nationality"] for h in history}) > 1 and inferred == UNKNOWN:
            conflicts.append(player.id)
            _record(db, player.id, UNKNOWN, "international_appearances", "conflict", "low", 0,
                    details={"affiliations": sorted({h["nationality"] for h in history})})
        if inferred != UNKNOWN:
            selected = next((h for h in history if h["nationality"] == inferred), None)
            attr = next((a for a in attrs if a.attribute_value.strip().lower() in {"", "unknown", "indian", "overseas"}), None)
            if attr:
                attr.attribute_value = inferred
                attr.source = "international_appearances"
                attr.confidence = "high"
                attr.valid_from = selected["first_seen"] if selected else None
                attr.valid_to = selected["last_seen"] if selected else None
            else:
                db.add(PlayerAttribute(player_id=player.id, attribute_type="nationality", attribute_value=inferred,
                    source="international_appearances", confidence="high",
                    valid_from=selected["first_seen"] if selected else None,
                    valid_to=selected["last_seen"] if selected else None))
            resolved += 1
        else:
            if not attrs:
                db.add(PlayerAttribute(player_id=player.id, attribute_type="nationality", attribute_value=UNKNOWN,
                    source="nationality_review_required", confidence="low"))
            unresolved.append({"id": player.id, "name": player.canonical_name})
        if player.id not in conflicts:
            stale = db.scalars(select(PlayerNationalityEvidence).where(
                PlayerNationalityEvidence.player_id == player.id,
                PlayerNationalityEvidence.source == "international_appearances",
                PlayerNationalityEvidence.verification_status == "conflict",
            )).all()
            for evidence in stale:
                evidence.verification_status = "resolved"
    db.flush()
    return {"total_players": len(players), "resolved": resolved, "unresolved": unresolved,
            "conflicting_player_ids": sorted(set(conflicts))}


async def lookup_cricketdatabase_nationality(db: Session, player: Player) -> str | None:
    """Exact-name provider fallback for unresolved players; never creates/merges player identities."""
    import httpx
    key = settings.CRICKET_DATABASE_API_KEY
    if not key:
        return None
    provider = db.scalar(select(Provider).where(Provider.name == "cricketdatabase"))
    if provider:
        cached = db.scalar(select(PlayerExternalProfile).where(
            PlayerExternalProfile.player_id == player.id,
            PlayerExternalProfile.provider_id == provider.id).limit(1))
        if cached:
            value = cached.basic_stats.get("nationality") or cached.basic_stats.get("country")
            if value:
                return str(value).strip()
    normalize = lambda value: " ".join("".join(c.lower() if c.isalnum() else " " for c in value).split())
    base = settings.CRICKET_DATABASE_BASE_URL.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            response = await client.get(f"{base}/players", params={"q": player.canonical_name},
                headers={"Authorization": f"Bearer {key}"})
            response.raise_for_status()
            data = response.json().get("data", [])
            matches = [item for item in data if normalize(str(item.get("name", ""))) == normalize(player.canonical_name)]
            if len(matches) != 1:
                return None
            item = matches[0]
            provider_player_id = str(item.get("player") or item.get("id") or "")
            if not provider_player_id:
                return None
            detail = await client.get(f"{base}/players/{provider_player_id}",
                headers={"Authorization": f"Bearer {key}"})
            if detail.is_success:
                item = detail.json().get("data", item)
    except (httpx.HTTPError, ValueError, TypeError):
        return None
    nationality = item.get("nationality") or item.get("country")
    if isinstance(nationality, dict):
        nationality = nationality.get("name") or nationality.get("country")
    if not nationality or not str(nationality).strip():
        return None
    nationality = str(nationality).strip()
    if provider is None:
        provider = Provider(name="cricketdatabase", base_url=base)
        db.add(provider)
        db.flush()
    # Cache stable provider identity against the existing CPI player; never create a second player.
    alias = db.scalar(select(PlayerAlias).where(PlayerAlias.provider_id == provider.id,
        PlayerAlias.source_player_id == provider_player_id).limit(1))
    if alias is None:
        db.add(PlayerAlias(player_id=player.id, provider_id=provider.id,
            source_player_id=provider_player_id, source_name=str(item.get("name") or player.canonical_name)))
    profile = db.scalar(select(PlayerExternalProfile).where(PlayerExternalProfile.provider_id == provider.id,
        PlayerExternalProfile.provider_player_id == provider_player_id).limit(1))
    basic = {"nationality": nationality, "country": nationality}
    if profile is None:
        db.add(PlayerExternalProfile(player_id=player.id, provider_id=provider.id,
            provider_player_id=provider_player_id, basic_stats=basic))
    _record(db, player.id, nationality, "cricketdatabase_exact_name", "provider_reported", "medium",
            details={"provider_player_id": provider_player_id})
    existing = db.scalar(select(PlayerAttribute).where(PlayerAttribute.player_id == player.id,
        PlayerAttribute.attribute_type == "nationality").limit(1))
    if existing is None:
        db.add(PlayerAttribute(player_id=player.id, attribute_type="nationality", attribute_value=nationality,
            source="cricketdatabase_exact_name", confidence="medium"))
    elif existing.attribute_value.strip().lower() in {"", "unknown", "indian", "overseas"}:
        existing.attribute_value = nationality
        existing.source = "cricketdatabase_exact_name"
        existing.confidence = "medium"
    elif existing.attribute_value.casefold() != nationality.casefold():
        _record(db, player.id, nationality, "cricketdatabase_exact_name", "conflict", "medium",
            details={"conflicts_with_existing_value": existing.attribute_value})
    return nationality
