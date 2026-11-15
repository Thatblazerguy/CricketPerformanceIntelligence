"""Optional server-side Cricket Database lookup with DB-backed response caching."""
import httpx
from typing import Optional, Dict, Any
from sqlalchemy import select
from app.core.config import settings
from app.models.models import Provider, Player, PlayerAlias, PlayerNameAlias, PlayerAttribute, PlayerExternalProfile

PROVIDER = "cricketdatabase"

async def enrich_player(db, name: str, supplied: Optional[Dict[str, Any]] = None):
    """Resolve from provider only when enabled; create an explicitly minimal record otherwise."""
    supplied = supplied or {}
    provider = db.scalar(select(Provider).where(Provider.name == PROVIDER))
    if not provider:
        provider = Provider(name=PROVIDER, base_url=settings.CRICKET_DATABASE_BASE_URL)
        db.add(provider); db.flush()
    cached_alias = db.scalar(select(PlayerAlias).where(PlayerAlias.provider_id == provider.id,
                                                       PlayerAlias.source_name.ilike(name.strip())).limit(1))
    if cached_alias:
        is_minimal = cached_alias.source_player_id.startswith("auction-upload:")
        return db.get(Player, cached_alias.player_id), "auction_upload" if is_minimal else PROVIDER, "minimal" if is_minimal else "basic"
    local = db.scalar(select(Player).where(Player.canonical_name.ilike(name.strip())).limit(1))
    if local: return local, "CPI", "local"
    result = None
    key = settings.CRICKET_DATABASE_API_KEY
    if key and name.strip():
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                response = await client.get(f"{settings.CRICKET_DATABASE_BASE_URL.rstrip('/')}/players",
                    params={"q": name.strip()}, headers={"Authorization": f"Bearer {key}"})
                response.raise_for_status()
                data = response.json().get("data", [])
            normalized = lambda s: " ".join(''.join(c.lower() if c.isalnum() else ' ' for c in s).split())
            exact = [item for item in data if normalized(item.get("name", "")) == normalized(name)]
            if len(exact) == 1:
                result = exact[0]
                provider_id = str(result.get("player") or result.get("id") or "")
                cached = db.scalar(select(PlayerExternalProfile).where(PlayerExternalProfile.provider_id == provider.id,
                                                                           PlayerExternalProfile.provider_player_id == provider_id))
                if cached:
                    return db.get(Player, cached.player_id), "cricketdatabase", "basic"
                detail = await client.get(f"{settings.CRICKET_DATABASE_BASE_URL.rstrip('/')}/players/{provider_id}",
                    headers={"Authorization": f"Bearer {key}"})
                if detail.is_success: result = detail.json().get("data", result)
                stat_response = await client.get(f"{settings.CRICKET_DATABASE_BASE_URL.rstrip('/')}/players/{provider_id}/stats",
                    headers={"Authorization": f"Bearer {key}"})
                stats = stat_response.json().get("data", {}) if stat_response.is_success else {}
                result = {**result, "basic_stats": stats, "provider_player_id": provider_id}
        except (httpx.HTTPError, ValueError, KeyError):
            result = None
    player = Player(canonical_name=(result or {}).get("name") or name.strip())
    db.add(player); db.flush()
    alias = PlayerAlias(player_id=player.id, provider_id=provider.id,
                        source_player_id=str((result or {}).get("provider_player_id") or f"auction-upload:{player.id}"),
                        source_name=name.strip())
    db.add(alias)
    attrs = {**supplied, **(result or {})}
    nationality_added = False
    for key_name, attr_type in (("full_name", "full_name"), ("country", "nationality"), ("nationality", "nationality"),
                                ("born", "date_of_birth"), ("batting_style", "batting_style"),
                                ("bowling_style", "bowling_style"), ("primary_role", "primary_role")):
        value = attrs.get(key_name)
        if value:
            if attr_type == "nationality" and str(value).strip().casefold() in {"indian", "overseas"}:
                continue
            existing = db.scalar(select(PlayerAttribute).where(PlayerAttribute.player_id == player.id,
                                                               PlayerAttribute.attribute_type == attr_type).limit(1))
            if not existing:
                db.add(PlayerAttribute(player_id=player.id, attribute_type=attr_type, attribute_value=str(value),
                                       source=PROVIDER if result else "auction_upload", confidence="medium" if result else "low"))
            if attr_type == "nationality":
                nationality_added = True
    if not nationality_added and not db.scalar(select(PlayerAttribute.id).where(
            PlayerAttribute.player_id == player.id, PlayerAttribute.attribute_type == "nationality").limit(1)):
        db.add(PlayerAttribute(player_id=player.id, attribute_type="nationality", attribute_value="Unknown",
            source="nationality_review_required", confidence="low"))
    if result:
        db.add(PlayerExternalProfile(player_id=player.id, provider_id=provider.id,
            provider_player_id=result["provider_player_id"], basic_stats=result.get("basic_stats") or {}))
    return player, PROVIDER if result else "auction_upload", "basic" if result else "minimal"
