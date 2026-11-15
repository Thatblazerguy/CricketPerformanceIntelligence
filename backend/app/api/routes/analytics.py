"""Matchup and venue analytics endpoints."""
from typing import Optional, List
from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import select, func
from pydantic import BaseModel

from app.db.session import get_db
from app.models.models import Player, Delivery, MatchInnings, Match, Wicket, Venue
from app.analytics.grounds import FORMAT_BUCKETS, get_ground_analytics

router = APIRouter()


class MatchupPhaseData(BaseModel):
    phase: str
    balls: int
    runs: int
    strike_rate: Optional[float]
    dismissals: int


class MatchupResponse(BaseModel):
    batter_id: str
    batter_name: str
    bowler_id: str
    bowler_name: str
    balls_faced: int
    legal_balls: int
    batter_runs: int
    fours: int
    sixes: int
    dismissals: int
    dismissal_types: dict
    strike_rate: Optional[float]
    dot_ball_count: int
    boundary_count: int
    dot_ball_pct: Optional[float]
    boundary_pct: Optional[float]
    sample_warning: Optional[str]
    phases: List[MatchupPhaseData] = []


class VenueStatsResponse(BaseModel):
    venue_id: str
    venue_name: str
    total_matches: int
    avg_first_innings_score: Optional[float]
    avg_second_innings_score: Optional[float]
    city: Optional[str] = None
    country: Optional[str] = None


@router.get("/matchups/{batter_id}/{bowler_id}", response_model=MatchupResponse)
def batter_bowler_matchup(
    batter_id: str,
    bowler_id: str,
    format: Optional[str] = Query(None),
    season: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    batter = db.get(Player, batter_id)
    bowler = db.get(Player, bowler_id)
    if not batter:
        raise HTTPException(status_code=404, detail="Batter not found")
    if not bowler:
        raise HTTPException(status_code=404, detail="Bowler not found")

    stmt = (
        select(
            Delivery.batter_runs,
            Delivery.is_legal_ball,
            Delivery.is_ball_faced_by_batter,
            Delivery.is_boundary_four,
            Delivery.is_boundary_six,
            Delivery.phase,
            Delivery.id,
        )
        .join(MatchInnings, Delivery.innings_id == MatchInnings.id)
        .join(Match, MatchInnings.match_id == Match.id)
        .where(
            Delivery.batter_id == batter_id,
            Delivery.bowler_id == bowler_id,
            MatchInnings.is_super_over == False,
        )
    )
    if format:
        stmt = stmt.where(Match.match_format == format)
    if season:
        stmt = stmt.where(Match.season == season)

    rows = db.execute(stmt).fetchall()

    balls_faced = sum(1 for r in rows if r[2])
    legal_balls = sum(1 for r in rows if r[1])
    batter_runs = sum(r[0] for r in rows)
    fours = sum(1 for r in rows if r[3])
    sixes = sum(1 for r in rows if r[4])
    boundaries = fours + sixes
    dot_balls = sum(1 for r in rows if r[1] and r[0] == 0)

    # Dismissals: only count dismissals where the batter was facing the bowler AND credited to the bowler
    wkt_stmt = (
        select(Wicket.dismissal_type, Delivery.phase)
        .join(Delivery, Wicket.delivery_id == Delivery.id)
        .join(MatchInnings, Delivery.innings_id == MatchInnings.id)
        .join(Match, MatchInnings.match_id == Match.id)
        .where(
            Wicket.player_out_id == batter_id,
            Delivery.batter_id == batter_id,
            Delivery.bowler_id == bowler_id,
            Wicket.is_bowler_wicket == True,
            MatchInnings.is_super_over == False,
        )
    )
    if format:
        wkt_stmt = wkt_stmt.where(Match.match_format == format)
    if season:
        wkt_stmt = wkt_stmt.where(Match.season == season)

    wkt_rows = db.execute(wkt_stmt).fetchall()

    dismissal_types: dict = {}
    phase_dismissals: dict = {}
    for row in wkt_rows:
        kind = row[0]
        ph = row[1] or "middle"
        dismissal_types[kind] = dismissal_types.get(kind, 0) + 1
        phase_dismissals[ph] = phase_dismissals.get(ph, 0) + 1
    dismissals = sum(dismissal_types.values())

    strike_rate = round((batter_runs / balls_faced) * 100, 2) if balls_faced > 0 else None
    dot_ball_pct = round((dot_balls / balls_faced) * 100, 1) if balls_faced > 0 else None
    boundary_pct = round((boundaries / balls_faced) * 100, 1) if balls_faced > 0 else None

    # Calculate phase splits
    phases_data = []
    for ph_name in ["powerplay", "middle", "death"]:
        ph_rows = [r for r in rows if r[5] == ph_name]
        ph_bf = sum(1 for r in ph_rows if r[2])
        ph_runs = sum(r[0] for r in ph_rows)
        ph_sr = round((ph_runs / ph_bf) * 100, 1) if ph_bf > 0 else None
        ph_wk = phase_dismissals.get(ph_name, 0)
        phases_data.append(MatchupPhaseData(
            phase=ph_name,
            balls=ph_bf,
            runs=ph_runs,
            strike_rate=ph_sr,
            dismissals=ph_wk,
        ))

    sample_warning = None
    if balls_faced < 12:
        sample_warning = f"Small sample ({balls_faced} balls faced). Results may not be statistically meaningful."

    return MatchupResponse(
        batter_id=batter_id,
        batter_name=batter.canonical_name,
        bowler_id=bowler_id,
        bowler_name=bowler.canonical_name,
        balls_faced=balls_faced,
        legal_balls=legal_balls,
        batter_runs=batter_runs,
        fours=fours,
        sixes=sixes,
        dismissals=dismissals,
        dismissal_types=dismissal_types,
        strike_rate=strike_rate,
        dot_ball_count=dot_balls,
        boundary_count=boundaries,
        dot_ball_pct=dot_ball_pct,
        boundary_pct=boundary_pct,
        sample_warning=sample_warning,
        phases=phases_data,
    )


@router.get("/venues", response_model=List[VenueStatsResponse])
def list_venues(format: Optional[str] = Query("T20"), db: Session = Depends(get_db)):
    """Lightweight directory; detailed ball-level analysis is loaded per selected venue."""
    if format and format not in FORMAT_BUCKETS:
        raise HTTPException(status_code=400, detail="format must be one of ODI, T20, or Test")
    stmt = (select(Venue, func.count(Match.id))
        .join(Match, Match.venue_id == Venue.id)
        .group_by(Venue.id)
        .order_by(func.count(Match.id).desc(), Venue.canonical_name))
    if format:
        formats = FORMAT_BUCKETS[format]
        stmt = stmt.where(Match.match_format.in_(formats))
    rows = db.execute(stmt).all()
    return [VenueStatsResponse(venue_id=venue.id, venue_name=venue.canonical_name,
        total_matches=int(count), avg_first_innings_score=None, avg_second_innings_score=None,
        city=venue.city, country=venue.country) for venue, count in rows]


@router.get("/venues/{venue_id}/ground-analytics")
def selected_ground_analytics(venue_id: str, format: str = Query("T20"), start_date: Optional[date] = None,
                              end_date: Optional[date] = None, recent_matches: int = Query(10, ge=10, le=20),
                              period: str = Query("all"),
                              db: Session = Depends(get_db)):
    """Format-aware details are computed only when a ground is selected and cached briefly."""
    if format not in FORMAT_BUCKETS:
        raise HTTPException(status_code=400, detail="format must be one of ODI, T20, or Test")
    if recent_matches not in (10, 20):
        raise HTTPException(status_code=400, detail="recent_matches must be 10 or 20")
    try:
        result = get_ground_analytics(db, venue_id, format, start_date, end_date, recent_matches, period)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Ground not found")
    return result
