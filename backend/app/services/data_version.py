"""
Detect imported-data changes made by another process (the sync worker) and drop
the API's in-process analytics caches so on-demand statistics are recomputed.

The marker is the id of the newest ``sync_history`` row that imported or
corrected at least one match. It is polled at most every ``CHECK_SECONDS``.
"""
from __future__ import annotations

import logging
import time
from threading import Lock
from typing import Optional

from sqlalchemy import text

logger = logging.getLogger(__name__)

CHECK_SECONDS = 30.0
_lock = Lock()
_last_poll = 0.0
_last_marker: Optional[int] = None
_initialised = False


def current_data_marker(conn_or_session) -> Optional[int]:
    return conn_or_session.execute(text(
        "SELECT max(id) FROM sync_history WHERE (new_matches + updated_matches) > 0 AND completed_at IS NOT NULL"
    )).scalar()


def clear_analytics_caches() -> None:
    """Clear every process-local cache that holds values derived from match data."""
    try:
        from app.analytics import grounds
        with grounds._CACHE_LOCK:
            grounds._CACHE.clear()
    except Exception:  # pragma: no cover - defensive
        logger.debug("grounds cache not cleared", exc_info=True)
    try:
        from app.ml.similarity.cache import clear_similarity_cache
        clear_similarity_cache()  # also backs the scouting cohort cache
    except Exception:  # pragma: no cover
        logger.debug("similarity cache not cleared", exc_info=True)
    try:
        from app.analytics import auction_form
        auction_form._CURRENT_FORM_CACHE.clear()
    except Exception:  # pragma: no cover
        logger.debug("auction form cache not cleared", exc_info=True)
    try:
        from app.api.routes import xi
        xi._PRESETS_CACHE = None
    except Exception:  # pragma: no cover
        logger.debug("xi presets cache not cleared", exc_info=True)
    try:
        from app.ml import sim_calibration
        sim_calibration.clear_profile_cache()  # simulator player/venue profiles
    except Exception:  # pragma: no cover
        logger.debug("simulator profile cache not cleared", exc_info=True)
    logger.info("Analytics caches cleared after a data change")


def maybe_invalidate_caches(engine) -> bool:
    """Poll the marker (rate-limited); clear caches when it moved. Returns True if cleared."""
    global _last_poll, _last_marker, _initialised
    now = time.monotonic()
    with _lock:
        if now - _last_poll < CHECK_SECONDS:
            return False
        _last_poll = now
    try:
        with engine.connect() as conn:
            marker = current_data_marker(conn)
    except Exception:
        # sync tables may not exist yet (pre-migration) or DB briefly unavailable
        return False
    with _lock:
        changed = _initialised and marker != _last_marker
        _last_marker, _initialised = marker, True
    if changed:
        clear_analytics_caches()
    return changed
