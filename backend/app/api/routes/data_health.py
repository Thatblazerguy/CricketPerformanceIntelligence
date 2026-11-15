"""Data Health and hybrid-coverage API.

Read endpoints describe coverage; POST endpoints run ingestion management
actions (refresh inventories, import missing / retry failed, reconcile,
recompute coverage, import a verified scorecard bundle).
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.hybrid import health, registry
from app.hybrid.career import detect_conflicts, player_career
from app.hybrid.reconstruction import player_coverage, reconstruct_player
from app.hybrid.sources.catalog import catalog
from app.hybrid.sources.cricsheet_inventory import CricsheetInventoryAdapter
from app.hybrid.sources.scorecard_file import ScorecardBundleError, ScorecardFileAdapter
from app.models.models import Player, ReconciliationFlag

router = APIRouter()


def _filters(format_class: Optional[str], gender: Optional[str], season: Optional[str], competition: Optional[str],
             team: Optional[str], player_id: Optional[str]) -> Dict[str, Any]:
    return {"format_class": format_class, "gender": gender, "season": season, "competition": competition,
            "team": team, "player_id": player_id}


@router.get("/data-health/overview")
def get_overview(format_class: Optional[str] = None, gender: Optional[str] = None, season: Optional[str] = None,
                 competition: Optional[str] = None, team: Optional[str] = None, player_id: Optional[str] = None,
                 db: Session = Depends(get_db)):
    return health.overview(db, _filters(format_class, gender, season, competition, team, player_id))


@router.get("/data-health/competitions")
def get_competitions(format_class: Optional[str] = None, gender: Optional[str] = None, season: Optional[str] = None,
                     competition: Optional[str] = None, team: Optional[str] = None, player_id: Optional[str] = None,
                     db: Session = Depends(get_db)):
    return health.competition_coverage(db, _filters(format_class, gender, season, competition, team, player_id))


@router.get("/data-health/players")
def get_player_health(limit: int = Query(50, le=500), gender: Optional[str] = None, db: Session = Depends(get_db)):
    return {
        "career_predates_records": health.players_predating_records(db, limit, gender),
        "incomplete_ball_by_ball": health.players_incomplete_ball_by_ball(db, limit),
        "needs_reconciliation": health.players_needing_reconciliation(db, limit),
        "unresolved_scorecard_identities": health.unresolved_identities(db, limit),
    }


@router.get("/data-health/inventory")
def get_inventory(status: Optional[str] = None, limit: int = Query(200, le=2000), db: Session = Depends(get_db)):
    return {"items": health.inventory_items(db, status, limit)}


@router.get("/data-health/duplicates")
def get_duplicates(db: Session = Depends(get_db)):
    return {"candidates": health.duplicate_candidates(db), "same_day_fixtures_kept_apart": health.double_headers(db)}


@router.get("/data-health/reconciliation")
def get_flags(status: str = "open", db: Session = Depends(get_db)):
    return {"flags": health.flags(db, status)}


@router.get("/data-health/log")
def get_log(limit: int = Query(100, le=500), db: Session = Depends(get_db)):
    return {"events": health.ingestion_log(db, limit)}


@router.get("/data-health/sources")
def get_sources():
    return {"sources": catalog()}


# ----------------------------------------------------------------------------- actions

@router.post("/data-health/actions/refresh-inventory")
def refresh_inventory(check_upstream: bool = False, db: Session = Depends(get_db)):
    adapter = CricsheetInventoryAdapter()
    try:
        out = {"cricsheet": adapter.refresh_inventory(db)}
    except FileNotFoundError as exc:
        raise HTTPException(409, str(exc))
    if check_upstream:
        out["upstream"] = adapter.check_upstream(db)
    db.commit()
    return out


@router.post("/data-health/actions/import-missing")
def import_missing(limit: int = Query(500, le=5000), db: Session = Depends(get_db)):
    out = CricsheetInventoryAdapter().import_missing(db, limit=limit, statuses=("missing",))
    db.commit()
    return out


@router.post("/data-health/actions/retry-failed")
def retry_failed(limit: int = Query(500, le=5000), db: Session = Depends(get_db)):
    out = CricsheetInventoryAdapter().import_missing(db, limit=limit, statuses=("failed",))
    db.commit()
    return out


@router.post("/data-health/actions/reconcile")
def reconcile_all(db: Session = Depends(get_db)):
    """Re-run cross-source reconciliation for every match that has a scorecard and ball-by-ball data."""
    from sqlalchemy import text
    ids = [r for (r,) in db.execute(text("""SELECT DISTINCT si.canonical_match_id FROM scorecard_innings si
                                            JOIN canonical_matches c ON c.id = si.canonical_match_id""")).all()]
    flags = sum(detect_conflicts(db, cid) for cid in ids)
    counts = registry.refresh_coverage(db, ids) if ids else {}
    registry.log_event(db, "hybrid", "reconcile", "ok", "", matches=len(ids), flags=flags)
    db.commit()
    return {"matches_checked": len(ids), "flags_written": flags, "coverage": counts}


@router.post("/data-health/actions/refresh-coverage")
def refresh_coverage(db: Session = Depends(get_db)):
    out = registry.backfill_from_ball_by_ball(db)
    counts = registry.refresh_coverage(db)
    registry.log_event(db, "hybrid", "refresh_coverage", "ok", "", **out, **counts)
    db.commit()
    return {**out, "coverage": counts}


@router.post("/data-health/reconciliation/{flag_id}/resolve")
def resolve_flag(flag_id: str, payload: Dict[str, Any] = Body(...), db: Session = Depends(get_db)):
    flag = db.get(ReconciliationFlag, flag_id)
    if flag is None:
        raise HTTPException(404, "Flag not found")
    note = str(payload.get("resolution") or "").strip()
    if not note:
        raise HTTPException(422, "A resolution note citing the evidence is required")
    flag.status, flag.resolution = "resolved", note[:2000]
    db.commit()
    return {"id": flag.id, "status": flag.status}


@router.post("/data-health/scorecards/import")
def import_scorecards(bundle: Dict[str, Any] = Body(...), db: Session = Depends(get_db)):
    try:
        report = ScorecardFileAdapter().import_bundle(db, bundle)
    except ScorecardBundleError as exc:
        raise HTTPException(422, str(exc))
    db.commit()
    from app.services.data_version import clear_analytics_caches
    clear_analytics_caches()
    return report.as_dict()


# ----------------------------------------------------------------------------- players

def _player(db: Session, player_id: str) -> Player:
    p = db.get(Player, player_id)
    if p is None:
        raise HTTPException(404, "Player not found")
    return p


@router.get("/players/{player_id}/coverage")
def get_player_coverage(player_id: str, db: Session = Depends(get_db)):
    p = _player(db, player_id)
    return {"name": p.canonical_name, **player_coverage(db, player_id)}


@router.get("/players/{player_id}/career")
def get_player_career(player_id: str, gender: Optional[str] = None, db: Session = Depends(get_db)):
    p = _player(db, player_id)
    return {"name": p.canonical_name, **player_career(db, player_id, gender)}


@router.get("/players/{player_id}/reconstruction")
def get_player_reconstruction(player_id: str, db: Session = Depends(get_db)):
    p = _player(db, player_id)
    return {"name": p.canonical_name, **reconstruct_player(db, player_id)}
