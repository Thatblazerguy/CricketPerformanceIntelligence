"""Health and dataset coverage endpoints."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text, func, select, distinct
from app.db.session import get_db
from app.models.models import Match, Player, Team, Venue, Tournament, IngestionRun
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

router = APIRouter()


class HealthResponse(BaseModel):
    status: str
    database: str


class CoverageResponse(BaseModel):
    total_matches: int
    total_players: int
    total_teams: int
    total_venues: int
    total_tournaments: int
    formats: dict
    seasons: list
    year_counts: list
    last_ingestion: Optional[str]


@router.get("/health", response_model=HealthResponse)
def health_check(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        db_status = "ok"
    except Exception:
        db_status = "error"
    return HealthResponse(status="ok", database=db_status)


@router.get("/dataset/coverage", response_model=CoverageResponse)
def dataset_coverage(db: Session = Depends(get_db)):
    total_matches = db.execute(select(func.count(Match.id))).scalar() or 0
    total_players = db.execute(select(func.count(Player.id))).scalar() or 0
    total_teams = db.execute(select(func.count(Team.id))).scalar() or 0
    total_venues = db.execute(select(func.count(Venue.id))).scalar() or 0
    total_tournaments = db.execute(select(func.count(Tournament.id))).scalar() or 0

    # Format breakdown
    format_rows = db.execute(
        select(Match.match_format, func.count(Match.id).label("count"))
        .group_by(Match.match_format)
    ).fetchall()
    formats = {row[0]: row[1] for row in format_rows}

    # Season list
    season_rows = db.execute(
        select(distinct(Match.season)).order_by(Match.season)
    ).fetchall()
    seasons = [row[0] for row in season_rows]

    year_rows = db.execute(
        select(func.extract("year", Match.start_date).label("year"), func.count(Match.id))
        .where(Match.start_date.is_not(None))
        .group_by(func.extract("year", Match.start_date))
        .order_by(func.extract("year", Match.start_date))
    ).all()
    year_counts = [{"year": int(year), "matches": int(count)} for year, count in year_rows]

    # Last ingestion
    last_run = db.execute(
        select(IngestionRun.finished_at)
        .where(IngestionRun.status.in_(["success", "partial"]))
        .order_by(IngestionRun.finished_at.desc())
        .limit(1)
    ).scalar()
    last_ingestion = last_run.isoformat() if last_run else None

    return CoverageResponse(
        total_matches=total_matches,
        total_players=total_players,
        total_teams=total_teams,
        total_venues=total_venues,
        total_tournaments=total_tournaments,
        formats=formats,
        seasons=seasons,
        year_counts=year_counts,
        last_ingestion=last_ingestion,
    )
