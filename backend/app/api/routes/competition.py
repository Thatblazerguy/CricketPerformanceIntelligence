"""Team Analytics and Venue Analytics endpoints (Competitions section).

Shared filters on every endpoint: format (exact stored format), gender,
competition (tournament name contains), season, start_year, end_year.
"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.analytics.competition_common import Scope, require_summary_table
from app.analytics.team_analytics import head_to_head, team_directory, team_profile
from app.analytics.venue_analytics import venue_directory, venue_profile
from app.db.session import get_db

router = APIRouter(prefix="/competition")


def scope_params(
    format: str = Query("T20"),
    gender: str = Query("male", description="male or female. Teams often hold both men's and women's matches, so genders are never mixed."),
    competition: Optional[str] = Query(None),
    season: Optional[str] = Query(None),
    start_year: Optional[int] = Query(None),
    end_year: Optional[int] = Query(None),
) -> Scope:
    if gender not in ("male", "female"):
        raise HTTPException(status_code=422, detail="gender must be male or female")
    scope = Scope(format=format, gender=gender, competition=(competition or None) and competition.strip(),
                  season=season or None, start_year=start_year, end_year=end_year)
    try:
        scope.where({})
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return scope


def _ready(db: Session) -> None:
    try:
        require_summary_table(db)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/seasons")
def seasons(scope: Scope = Depends(scope_params), db: Session = Depends(get_db)):
    """Seasons available for the format (for the season filter)."""
    params: dict = {}
    where = Scope(format=scope.format, gender=scope.gender, competition=scope.competition).where(params)
    rows = db.execute(text(f"SELECT DISTINCT m.season FROM matches m WHERE {where} ORDER BY 1 DESC"), params).scalars().all()
    return {"seasons": rows}


@router.get("/teams")
def teams(scope: Scope = Depends(scope_params), db: Session = Depends(get_db)):
    _ready(db)
    return {"scope": scope.__dict__, "teams": team_directory(db, scope)}


@router.get("/teams/compare")
def compare_teams(a: str, b: str, scope: Scope = Depends(scope_params), db: Session = Depends(get_db)):
    _ready(db)
    if a == b:
        raise HTTPException(status_code=422, detail="Choose two different teams.")
    pa, pb = team_profile(db, a, scope), team_profile(db, b, scope)
    if not pa or not pb:
        raise HTTPException(status_code=404, detail="Team not found")
    return {"a": pa, "b": pb, "head_to_head": head_to_head(db, a, b, scope)}


@router.get("/teams/{team_id}")
def team(team_id: str, opponent_id: Optional[str] = None, scope: Scope = Depends(scope_params), db: Session = Depends(get_db)):
    _ready(db)
    profile = team_profile(db, team_id, scope, opponent_id or None)
    if profile is None:
        raise HTTPException(status_code=404, detail="Team not found")
    return profile


@router.get("/venues")
def venues(team_id: Optional[str] = None, scope: Scope = Depends(scope_params), db: Session = Depends(get_db)):
    _ready(db)
    return {"scope": scope.__dict__, "venues": venue_directory(db, scope, team_id or None)}


@router.get("/venues/compare")
def compare_venues(ids: str = Query(..., description="Comma-separated venue ids (2-4)"),
                   team_id: Optional[str] = None, scope: Scope = Depends(scope_params), db: Session = Depends(get_db)):
    _ready(db)
    venue_ids: List[str] = [v for v in dict.fromkeys(x.strip() for x in ids.split(",")) if v]
    if not 2 <= len(venue_ids) <= 4:
        raise HTTPException(status_code=422, detail="Compare between 2 and 4 venues.")
    profiles = [venue_profile(db, v, scope, team_id or None) for v in venue_ids]
    if any(p is None for p in profiles):
        raise HTTPException(status_code=404, detail="Venue not found")
    return {"venues": profiles}


@router.get("/venues/{venue_id}")
def venue(venue_id: str, team_id: Optional[str] = None, scope: Scope = Depends(scope_params), db: Session = Depends(get_db)):
    _ready(db)
    profile = venue_profile(db, venue_id, scope, team_id or None)
    if profile is None:
        raise HTTPException(status_code=404, detail="Venue not found")
    return profile
