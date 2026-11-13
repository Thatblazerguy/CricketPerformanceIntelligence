"""
Refresh persisted statistics that depend on imported match data.

CPI computes almost every statistic (scorecards, batting/bowling, careers, team
records, partnerships, venues, head-to-head, scouting cohorts) on demand from
``matches`` / ``match_innings`` / ``deliveries``; once a match is (re)imported
those views are correct as soon as the API's short-lived caches are dropped
(see ``app.services.data_version``).

The only persisted derived data keyed on deliveries are the precomputed
win-probability curves (``match_win_probabilities``) and the player WPA
aggregates built from them (``player_win_probability_impact``). Those are
recomputed here for the affected matches/players only, reusing the existing
offline job's helpers and its saved model artefacts. Player nationality
evidence is already refreshed per match by ``MatchImporter``.
"""
from __future__ import annotations

import importlib.util
import logging
from pathlib import Path
from typing import Dict, Iterable, Optional, Set

from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from app.core.config import BACKEND_DIR
from app.ml.win_probability import FORMAT_FAMILY
from app.models.models import Match, MatchWinProbability

logger = logging.getLogger(__name__)

_WP_SCRIPT = BACKEND_DIR / "scripts" / "build_win_probability.py"
_WP_ARTIFACTS = BACKEND_DIR / "artifacts" / "win_probability"
_wp_module = None


def _load_wp_module():
    """Import the offline win-probability job so its helpers are reused, not duplicated."""
    global _wp_module
    if _wp_module is None:
        spec = importlib.util.spec_from_file_location("cpi_build_win_probability", _WP_SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[union-attr]
        _wp_module = module
    return _wp_module


def players_in_matches(db: Session, match_ids: Iterable[str]) -> Set[str]:
    ids = list(match_ids)
    if not ids:
        return set()
    rows = db.execute(text("""
        SELECT DISTINCT p FROM (
            SELECT d.batter_id AS p FROM deliveries d JOIN match_innings i ON i.id = d.innings_id WHERE i.match_id = ANY(:ids)
            UNION SELECT d.bowler_id FROM deliveries d JOIN match_innings i ON i.id = d.innings_id WHERE i.match_id = ANY(:ids)
        ) s WHERE p IS NOT NULL
    """), {"ids": ids}).scalars().all()
    return set(rows)


def refresh_dependent_statistics(
    db: Session,
    inserted_match_ids: Set[str],
    corrected_match_ids: Set[str],
    previous_player_ids: Optional[Set[str]] = None,
) -> Dict[str, object]:
    """Recompute persisted derived data for the affected matches; commits on success."""
    affected = set(inserted_match_ids) | set(corrected_match_ids)
    summary: Dict[str, object] = {
        "affected_matches": len(affected),
        "on_demand_views": [
            "scorecards", "innings/delivery breakdowns", "batting", "bowling", "player careers",
            "team records", "partnerships", "venues", "head-to-head", "scouting/visualisation datasets",
        ],
        "win_probability_matches": 0,
        "player_impact_rows": 0,
        "players_affected": 0,
        "notes": [],
    }
    if not affected:
        return summary

    # Stale curves for corrected matches must never be served, even if recomputation below fails.
    if corrected_match_ids:
        db.execute(delete(MatchWinProbability).where(MatchWinProbability.match_id.in_(list(corrected_match_ids))))
        db.commit()

    formats = dict(db.execute(select(Match.id, Match.match_format).where(Match.id.in_(list(affected)))).all())
    by_family: Dict[str, Set[str]] = {}
    for match_id, fmt in formats.items():
        family = FORMAT_FAMILY.get(fmt)
        if family:
            by_family.setdefault(family, set()).add(match_id)

    players = players_in_matches(db, affected) | set(previous_player_ids or ())
    summary["players_affected"] = len(players)

    if not by_family:
        summary["notes"].append("No affected match belongs to a win-probability format family.")
        return summary

    try:
        import joblib  # already a CPI dependency
        wp = _load_wp_module()
    except Exception as exc:  # pragma: no cover - environment problem
        summary["notes"].append(f"Win-probability helpers unavailable: {exc}")
        return summary

    formats_by_family = {"T20": ["T20", "T20I"], "ODI": ["ODI", "ODM"], "Test": ["Test", "MDM"]}
    precomputed = 0
    for family, ids in by_family.items():
        artifact = _WP_ARTIFACTS / f"{family.lower()}.joblib"
        if not artifact.exists():
            summary["notes"].append(f"No {family} win-probability model artefact; run scripts/build_win_probability.py.")
            continue
        payload = joblib.load(str(artifact))
        precomputed += wp._precompute_matches(
            db, family, formats_by_family[family], payload["model"], payload["version"], {}, match_ids=ids,
        )
        db.commit()
    summary["win_probability_matches"] = precomputed
    if players:
        summary["player_impact_rows"] = wp._rebuild_player_impacts(db, player_ids=players)
    db.commit()
    return summary
