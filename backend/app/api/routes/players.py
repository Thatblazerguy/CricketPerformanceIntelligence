"""
Player listing and profile endpoints.
All cricket statistics are computed server-side from delivery-level data.
"""
from __future__ import annotations

from typing import Optional, List, Dict, Any
from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import select, func, and_, or_, distinct, extract, text
from pydantic import BaseModel
import pandas as pd

from app.db.session import get_db
from app.models.models import (
    Player, PlayerAlias, PlayerNameAlias, PlayerAttribute, PlayerExternalProfile, Provider, Match, MatchInnings, Delivery, Wicket, Tournament, Venue, Team
)
from app.analytics.batting import BattingLine, calculate_batting_stats, calculate_phase_batting_stats
from app.analytics.bowling import BowlingLine, calculate_bowling_stats, calculate_phase_bowling_stats
from app.analytics.player_roles import classify_player_role
from app.domain.enums import Phase
from app.ml.features.player_features import extract_player_feature_matrix
from app.ml.similarity.model import PlayerSimilarityEngine
from app.ml.features.bowling_features import extract_bowling_feature_matrix
from app.ml.similarity.bowling_model import BowlingSimilarityEngine
from app.ml.similarity.allrounder_model import AllRounderSimilarityEngine
from app.ml.similarity.cache import get_or_build

router = APIRouter()


# ---- Response schemas ----

class PlayerSummary(BaseModel):
    id: str
    name: str
    source_player_id: Optional[str]
    full_name: Optional[str] = None
    date_of_birth: Optional[date] = None
    age: Optional[int] = None
    nationality: Optional[str] = None
    primary_role: Optional[str] = None
    batting_style: Optional[str] = None
    bowling_style: Optional[str] = None
    player_image: Optional[str] = None
    data_source: Optional[str] = None
    data_availability: Optional[str] = None
    external_basic_stats: Optional[Dict[str, Any]] = None
    analytics_notice: Optional[str] = None


BIO_ATTRIBUTE_TYPES = {
    "full_name": "full_name", "date_of_birth": "date_of_birth",
    "nationality": "nationality", "primary_role": "primary_role",
    "batting_style": "batting_style", "bowling_style": "bowling_style",
    "player_image": "player_image",
}


def _player_bio_fields(db: Session, player_id: str, canonical_name: str, prefetched=None) -> dict:
    rows = prefetched if prefetched is not None else db.execute(select(PlayerAttribute.attribute_type, PlayerAttribute.attribute_value)
                      .where(PlayerAttribute.player_id == player_id,
                             PlayerAttribute.attribute_type.in_(BIO_ATTRIBUTE_TYPES.values()))
                      .order_by(PlayerAttribute.confidence.desc())).all()
    attrs = {}
    for attr_type, value in rows:
        attrs.setdefault(attr_type, value)
    dob = None
    age = None
    raw_dob = attrs.get("date_of_birth")
    if raw_dob:
        try:
            dob = date.fromisoformat(raw_dob)
            today = date.today()
            age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
        except ValueError:
            dob = None
    return {
        "full_name": attrs.get("full_name", canonical_name), "date_of_birth": dob, "age": age,
        "nationality": attrs.get("nationality"), "primary_role": attrs.get("primary_role"),
        "batting_style": attrs.get("batting_style"), "bowling_style": attrs.get("bowling_style"),
        "player_image": attrs.get("player_image"),
    }

class PlayerListResponse(BaseModel):
    players: List[PlayerSummary]
    total: int
    page: int
    page_size: int


class BattingStatsResponse(BaseModel):
    player_id: str
    matches: int
    innings: int
    not_outs: int
    runs: int
    balls_faced: int
    dismissals: int
    highest_score: int
    fours: int
    sixes: int
    average: Optional[float]
    strike_rate: Optional[float]
    boundary_percentage: Optional[float]
    dot_ball_percentage: Optional[float]
    sample_note: str


class PhaseStatsResponse(BaseModel):
    phase: str
    runs: int
    balls_faced: int
    dismissals: int
    fours: int
    sixes: int
    strike_rate: Optional[float]
    average: Optional[float]
    dot_ball_percentage: Optional[float]
    boundary_percentage: Optional[float]


class BowlingStatsResponse(BaseModel):
    player_id: str
    innings_bowled: int
    legal_balls: int
    overs_display: str
    runs_conceded: int
    wickets: int
    dot_balls: int
    economy_rate: Optional[float]
    bowling_average: Optional[float]
    bowling_strike_rate: Optional[float]
    dot_ball_percentage: Optional[float]
    boundary_percentage: Optional[float]
    sample_note: str


class PlayerProfileResponse(BaseModel):
    id: str
    name: str
    source_player_id: Optional[str]
    batting: Optional[BattingStatsResponse]
    bowling: Optional[BowlingStatsResponse]
    phases_batting: Optional[List[PhaseStatsResponse]]
    phases_bowling: Optional[List[PhaseStatsResponse]]


class VenueOption(BaseModel):
    id: str
    name: str
    city: Optional[str] = None
    country: Optional[str] = None


class TeamOption(BaseModel):
    id: str
    name: str


class PlayerFilterMetadataResponse(BaseModel):
    formats: List[str]
    years: List[int]
    min_year: int
    max_year: int
    venues: List[VenueOption]
    teams: List[TeamOption]
    bowling_styles: List[str]


class PlayerPerformanceItem(BaseModel):
    id: str
    name: str
    matches: int
    innings_batted: int
    runs: int
    balls_faced: int
    dismissals: int
    fours: int
    sixes: int
    dot_balls: int
    batting_average: Optional[float] = None
    batting_strike_rate: Optional[float] = None
    boundary_percentage: Optional[float] = None
    dot_ball_percentage: Optional[float] = None
    # Phases
    pp_runs: int
    pp_balls: int
    pp_sr: Optional[float] = None
    middle_runs: int
    middle_balls: int
    middle_sr: Optional[float] = None
    death_runs: int
    death_balls: int
    death_sr: Optional[float] = None
    # Pace / spin
    pace_runs: int
    pace_balls: int
    pace_sr: Optional[float] = None
    spin_runs: int
    spin_balls: int
    spin_sr: Optional[float] = None
    # Bowling
    innings_bowled: int
    legal_balls_bowled: int
    overs_bowled: str
    runs_conceded: int
    wickets: int
    bowling_average: Optional[float] = None
    economy_rate: Optional[float] = None
    bowling_strike_rate: Optional[float] = None
    bowling_dot_ball_percentage: Optional[float] = None
    death_balls_bowled: int
    death_runs_conceded: int
    death_economy: Optional[float] = None


class PlayerPerformanceResponse(BaseModel):
    players: List[PlayerPerformanceItem]
    total: int
    page: int
    page_size: int
    total_pages: int
    active_filters_count: int


class PaceSpinSplit(BaseModel):
    style: str
    runs: int
    balls: int
    strike_rate: Optional[float] = None
    dismissals: int
    average: Optional[float] = None
    fours: int
    sixes: int
    dot_balls: int
    dot_ball_percentage: Optional[float] = None
    boundary_percentage: Optional[float] = None


class PhaseBreakdownItem(BaseModel):
    phase: str
    role: str
    runs: int
    balls: int
    strike_rate: Optional[float] = None
    dismissals: int
    average: Optional[float] = None
    fours: int
    sixes: int
    dot_ball_percentage: Optional[float] = None
    boundary_percentage: Optional[float] = None


class BowlingPhaseBreakdownItem(BaseModel):
    phase: str
    legal_balls: int
    overs: str
    wickets: int
    runs_conceded: int
    economy: Optional[float] = None
    bowling_average: Optional[float] = None
    bowling_strike_rate: Optional[float] = None
    dot_ball_percentage: Optional[float] = None
    boundary_percentage: Optional[float] = None


class BowlingPaceSpinSplit(BaseModel):
    style: str
    legal_balls: int
    overs: str
    wickets: int
    runs_conceded: int
    economy: Optional[float] = None
    bowling_average: Optional[float] = None
    bowling_strike_rate: Optional[float] = None
    dot_ball_percentage: Optional[float] = None
    boundary_percentage: Optional[float] = None


class FormatBreakdownItem(BaseModel):
    format: str
    matches: int
    innings_batted: int
    runs: int
    balls_faced: int
    batting_average: Optional[float] = None
    batting_strike_rate: Optional[float] = None
    innings_bowled: int
    overs_bowled: str
    wickets: int
    economy_rate: Optional[float] = None
    bowling_average: Optional[float] = None


class OpponentPerformanceItem(BaseModel):
    opponent_id: str
    opponent_name: str
    matches: int
    runs: int
    balls_faced: int
    batting_average: Optional[float] = None
    batting_strike_rate: Optional[float] = None
    wickets: int
    overs_bowled: str
    economy_rate: Optional[float] = None


class VenuePerformanceItem(BaseModel):
    venue_id: str
    venue_name: str
    city: Optional[str] = None
    matches: int
    runs: int
    balls_faced: int
    batting_average: Optional[float] = None
    batting_strike_rate: Optional[float] = None
    wickets: int
    overs_bowled: str
    economy_rate: Optional[float] = None


class YearTrendItem(BaseModel):
    year: int
    matches: int
    runs: int
    balls_faced: int
    batting_average: Optional[float] = None
    batting_strike_rate: Optional[float] = None
    wickets: int
    overs_bowled: str
    economy_rate: Optional[float] = None


class RecentMatchItem(BaseModel):
    match_id: str
    match_date: Optional[str] = None
    format: str
    opponent_name: str
    venue_name: str
    runs: int
    balls_faced: int
    strike_rate: Optional[float] = None
    wickets: int
    overs_bowled: str
    runs_conceded: int


class StrengthsWeaknessesItem(BaseModel):
    strengths: List[str]
    weaknesses: List[str]
    batting_strengths: List[str] = []
    batting_weaknesses: List[str] = []
    bowling_strengths: List[str] = []
    bowling_weaknesses: List[str] = []


class PlayerAnalyticsResponse(BaseModel):
    player_id: str
    player_name: str
    source_player_id: Optional[str] = None
    full_name: Optional[str] = None
    date_of_birth: Optional[date] = None
    age: Optional[int] = None
    nationality: Optional[str] = None
    official_role: Optional[str] = None
    batting_style: Optional[str] = None
    bowling_style: Optional[str] = None
    player_image: Optional[str] = None
    primary_role: str
    role_source: str
    role_confidence: str
    batting: BattingStatsResponse
    bowling: BowlingStatsResponse
    pace_spin: List[PaceSpinSplit]
    phases: List[PhaseBreakdownItem]
    bowling_phases: List[BowlingPhaseBreakdownItem]
    bowling_pace_spin: List[BowlingPaceSpinSplit]
    format_breakdown: List[FormatBreakdownItem]
    by_opponent: List[OpponentPerformanceItem]
    by_venue: List[VenuePerformanceItem]
    year_trends: List[YearTrendItem]
    recent_matches: List[RecentMatchItem]
    strengths_weaknesses: StrengthsWeaknessesItem


# ---- Helper: build filter conditions ----

def _match_filter_conditions(
    db: Session,
    format: Optional[str],
    competition: Optional[str],
    season: Optional[str],
):
    """Build a set of match IDs matching the given filters."""
    stmt = select(Match.id)
    if format:
        stmt = stmt.where(Match.match_format == format)
    if season:
        stmt = stmt.where(Match.season == season)
    if competition:
        stmt = stmt.join(Tournament, Match.tournament_id == Tournament.id).where(
            Tournament.name.ilike(f"%{competition}%")
        )
    return [row[0] for row in db.execute(stmt).fetchall()]


# ---- Routes ----

@router.get("/players", response_model=PlayerListResponse)
def list_players(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    name: Optional[str] = Query(None),
    role: Optional[str] = Query(None),
    format: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    alias_ids = (select(PlayerAlias.player_id.label("player_id"),
                        func.min(PlayerAlias.source_player_id).label("source_player_id"))
                 .group_by(PlayerAlias.player_id).subquery())
    base_stmt = select(Player.id, Player.canonical_name, alias_ids.c.source_player_id).outerjoin(
        alias_ids, Player.id == alias_ids.c.player_id
    )

    if name:
        alias_match = select(PlayerAlias.id).where(
            PlayerAlias.player_id == Player.id,
            PlayerAlias.source_name.ilike(f"%{name}%"),
        ).exists()
        reference_alias_match = select(PlayerNameAlias.id).where(PlayerNameAlias.player_id == Player.id, PlayerNameAlias.alias.ilike(f"%{name}%")).exists()
        base_stmt = base_stmt.where(or_(Player.canonical_name.ilike(f"%{name}%"), alias_match, reference_alias_match))

    if format:
        format_uses_player = select(Delivery.id).join(MatchInnings, Delivery.innings_id == MatchInnings.id).join(
            Match, MatchInnings.match_id == Match.id
        ).where(Match.match_format == format, or_(Delivery.batter_id == Player.id, Delivery.bowler_id == Player.id)).exists()
        base_stmt = base_stmt.where(format_uses_player)

    if role == "batter":
        # Only players who have faced at least one delivery
        batter_subq = select(Delivery.batter_id).distinct().subquery()
        base_stmt = base_stmt.join(batter_subq, Player.id == batter_subq.c.batter_id)
    elif role == "bowler":
        # Only players who have bowled at least one delivery
        bowler_subq = select(Delivery.bowler_id).distinct().subquery()
        base_stmt = base_stmt.join(bowler_subq, Player.id == bowler_subq.c.bowler_id)
    elif role == "all_rounder":
        bat = select(Delivery.batter_id).where(Delivery.batter_id == Player.id).exists()
        bowl = select(Delivery.bowler_id).where(Delivery.bowler_id == Player.id).exists()
        base_stmt = base_stmt.where(bat, bowl)

    total = db.execute(select(func.count()).select_from(base_stmt.subquery())).scalar() or 0
    base_stmt = base_stmt.order_by(Player.canonical_name).offset((page - 1) * page_size).limit(page_size)
    rows = db.execute(base_stmt).fetchall()
    attr_rows = db.execute(select(PlayerAttribute.player_id, PlayerAttribute.attribute_type, PlayerAttribute.attribute_value)
                           .where(PlayerAttribute.player_id.in_([r[0] for r in rows]),
                                  PlayerAttribute.attribute_type.in_(BIO_ATTRIBUTE_TYPES.values()))
                           .order_by(PlayerAttribute.confidence.desc())).all() if rows else []
    attrs_by_player: Dict[str, list] = {}
    for pid, attr_type, value in attr_rows: attrs_by_player.setdefault(pid, []).append((attr_type, value))
    result = [PlayerSummary(id=r[0], name=r[1], source_player_id=r[2],
                            **_player_bio_fields(db, r[0], r[1], attrs_by_player.get(r[0], []))) for r in rows]

    return PlayerListResponse(players=result, total=total, page=page, page_size=page_size)


@router.get("/players/filter-metadata", response_model=PlayerFilterMetadataResponse)
def get_player_filter_metadata(db: Session = Depends(get_db)):
    raw_formats = [
        r[0]
        for r in db.execute(
            select(Match.match_format)
            .where(Match.match_format.isnot(None))
            .distinct()
            .order_by(Match.match_format)
        ).fetchall()
    ]
    priority = ["Test", "ODI", "T20", "T20I"]
    ordered_formats = [f for f in priority if f in raw_formats] + [
        f for f in raw_formats if f not in priority
    ]

    yr_col = extract("year", Match.start_date)
    years = [
        int(r[0])
        for r in db.execute(
            select(yr_col)
            .where(Match.start_date.isnot(None))
            .distinct()
            .order_by(yr_col)
        ).fetchall()
    ]
    min_year = years[0] if years else 2005
    max_year = years[-1] if years else 2026

    venue_rows = db.execute(
        select(Venue.id, Venue.canonical_name, Venue.city, Venue.country).order_by(Venue.canonical_name)
    ).fetchall()
    venues = [
        VenueOption(id=str(r[0]), name=str(r[1]), city=r[2], country=r[3])
        for r in venue_rows
    ]

    team_rows = db.execute(select(Team.id, Team.name).order_by(Team.name)).fetchall()
    teams = [TeamOption(id=str(r[0]), name=str(r[1])) for r in team_rows]

    return PlayerFilterMetadataResponse(
        formats=ordered_formats,
        years=years,
        min_year=min_year,
        max_year=max_year,
        venues=venues,
        teams=teams,
        bowling_styles=["pace", "spin"],
    )


@router.get("/players/performance", response_model=PlayerPerformanceResponse)
def get_player_performance(
    format: Optional[str] = None,
    start_year: Optional[int] = None,
    end_year: Optional[int] = None,
    role: Optional[str] = "all",
    name: Optional[str] = None,
    vs_team_id: Optional[str] = None,
    venue_id: Optional[str] = None,
    # Batting filters
    min_runs: Optional[int] = None,
    max_runs: Optional[int] = None,
    min_batting_avg: Optional[float] = None,
    max_batting_avg: Optional[float] = None,
    min_batting_sr: Optional[float] = None,
    max_batting_sr: Optional[float] = None,
    min_balls_faced: Optional[int] = None,
    min_innings: Optional[int] = None,
    min_matches: Optional[int] = None,
    min_boundary_pct: Optional[float] = None,
    max_boundary_pct: Optional[float] = None,
    min_dot_ball_pct: Optional[float] = None,
    max_dot_ball_pct: Optional[float] = None,
    min_powerplay_sr: Optional[float] = None,
    min_middle_sr: Optional[float] = None,
    min_death_sr: Optional[float] = None,
    min_batting_sr_vs_pace: Optional[float] = None,
    min_batting_sr_vs_spin: Optional[float] = None,
    # Bowling filters
    min_wickets: Optional[int] = None,
    max_wickets: Optional[int] = None,
    min_bowling_avg: Optional[float] = None,
    max_bowling_avg: Optional[float] = None,
    min_economy: Optional[float] = None,
    max_economy: Optional[float] = None,
    min_bowling_sr: Optional[float] = None,
    max_bowling_sr: Optional[float] = None,
    min_balls_bowled: Optional[int] = None,
    max_death_economy: Optional[float] = None,
    # Sorting & Pagination
    sort_by: str = "runs",
    sort_dir: str = "desc",
    page: int = 1,
    page_size: int = 25,
    db: Session = Depends(get_db),
):
    active_filters_count = 0
    if format: active_filters_count += 1
    if start_year: active_filters_count += 1
    if end_year: active_filters_count += 1
    if role and role != "all": active_filters_count += 1
    if name: active_filters_count += 1
    if vs_team_id: active_filters_count += 1
    if venue_id: active_filters_count += 1
    if min_runs is not None or max_runs is not None: active_filters_count += 1
    if min_batting_avg is not None or max_batting_avg is not None: active_filters_count += 1
    if min_batting_sr is not None or max_batting_sr is not None: active_filters_count += 1
    if min_balls_faced is not None: active_filters_count += 1
    if min_innings is not None: active_filters_count += 1
    if min_matches is not None: active_filters_count += 1
    if min_boundary_pct is not None or max_boundary_pct is not None: active_filters_count += 1
    if min_dot_ball_pct is not None or max_dot_ball_pct is not None: active_filters_count += 1
    if min_powerplay_sr is not None: active_filters_count += 1
    if min_middle_sr is not None: active_filters_count += 1
    if min_death_sr is not None: active_filters_count += 1
    if min_batting_sr_vs_pace is not None: active_filters_count += 1
    if min_batting_sr_vs_spin is not None: active_filters_count += 1
    if min_wickets is not None or max_wickets is not None: active_filters_count += 1
    if min_bowling_avg is not None or max_bowling_avg is not None: active_filters_count += 1
    if min_economy is not None or max_economy is not None: active_filters_count += 1
    if min_bowling_sr is not None or max_bowling_sr is not None: active_filters_count += 1
    if min_balls_bowled is not None: active_filters_count += 1
    if max_death_economy is not None: active_filters_count += 1

    params: Dict[str, Any] = {}
    match_conditions = ["1=1"]

    if format:
        match_conditions.append("m.match_format = :format")
        params["format"] = format
    if start_year:
        match_conditions.append("m.start_date >= :start_date")
        params["start_date"] = f"{start_year}-01-01"
    if end_year:
        match_conditions.append("m.start_date <= :end_date")
        params["end_date"] = f"{end_year}-12-31"
    if venue_id:
        match_conditions.append("m.venue_id = :venue_id")
        params["venue_id"] = venue_id
    if vs_team_id:
        match_conditions.append("(m.team1_id = :vs_team_id OR m.team2_id = :vs_team_id)")
        params["vs_team_id"] = vs_team_id

    match_where_clause = " AND ".join(match_conditions)

    bat_vs_team_clause = "AND (CASE WHEN mi.batting_team_id = m.team1_id THEN m.team2_id ELSE m.team1_id END) = :vs_team_id" if vs_team_id else ""
    bowl_vs_team_clause = "AND mi.batting_team_id = :vs_team_id" if vs_team_id else ""

    agg_conditions = ["1=1"]
    if name:
        agg_conditions.append("canonical_name ILIKE :player_name_like")
        params["player_name_like"] = f"%{name}%"

    if role == "batter":
        min_bf_val = min_balls_faced if min_balls_faced is not None else 1
        agg_conditions.append("balls_faced >= :min_bf_val")
        params["min_bf_val"] = min_bf_val
    elif role == "bowler":
        min_bb_val = min_balls_bowled if min_balls_bowled is not None else 1
        agg_conditions.append("legal_balls_bowled >= :min_bb_val")
        params["min_bb_val"] = min_bb_val
    elif role == "all_rounder":
        agg_conditions.append("balls_faced >= 20 AND legal_balls_bowled >= 20")

    if min_runs is not None:
        agg_conditions.append("runs >= :min_runs")
        params["min_runs"] = min_runs
    if max_runs is not None:
        agg_conditions.append("runs <= :max_runs")
        params["max_runs"] = max_runs

    if min_batting_avg is not None:
        agg_conditions.append("batting_average >= :min_batting_avg AND batting_average IS NOT NULL")
        params["min_batting_avg"] = min_batting_avg
    if max_batting_avg is not None:
        agg_conditions.append("batting_average <= :max_batting_avg AND batting_average IS NOT NULL")
        params["max_batting_avg"] = max_batting_avg

    if min_batting_sr is not None:
        agg_conditions.append("batting_strike_rate >= :min_batting_sr AND batting_strike_rate IS NOT NULL")
        params["min_batting_sr"] = min_batting_sr
    if max_batting_sr is not None:
        agg_conditions.append("batting_strike_rate <= :max_batting_sr AND batting_strike_rate IS NOT NULL")
        params["max_batting_sr"] = max_batting_sr

    if min_balls_faced is not None and role != "batter":
        agg_conditions.append("balls_faced >= :min_balls_faced")
        params["min_balls_faced"] = min_balls_faced

    if min_innings is not None:
        agg_conditions.append("innings_batted >= :min_innings")
        params["min_innings"] = min_innings

    if min_matches is not None:
        agg_conditions.append("matches >= :min_matches")
        params["min_matches"] = min_matches

    if min_boundary_pct is not None:
        agg_conditions.append("boundary_percentage >= :min_boundary_pct AND boundary_percentage IS NOT NULL")
        params["min_boundary_pct"] = min_boundary_pct
    if max_boundary_pct is not None:
        agg_conditions.append("boundary_percentage <= :max_boundary_pct AND boundary_percentage IS NOT NULL")
        params["max_boundary_pct"] = max_boundary_pct

    if min_dot_ball_pct is not None:
        agg_conditions.append("dot_ball_percentage >= :min_dot_ball_pct AND dot_ball_percentage IS NOT NULL")
        params["min_dot_ball_pct"] = min_dot_ball_pct
    if max_dot_ball_pct is not None:
        agg_conditions.append("dot_ball_percentage <= :max_dot_ball_pct AND dot_ball_percentage IS NOT NULL")
        params["max_dot_ball_pct"] = max_dot_ball_pct

    if min_powerplay_sr is not None:
        agg_conditions.append("pp_sr >= :min_powerplay_sr AND pp_sr IS NOT NULL")
        params["min_powerplay_sr"] = min_powerplay_sr
    if min_middle_sr is not None:
        agg_conditions.append("middle_sr >= :min_middle_sr AND middle_sr IS NOT NULL")
        params["min_middle_sr"] = min_middle_sr
    if min_death_sr is not None:
        agg_conditions.append("death_sr >= :min_death_sr AND death_sr IS NOT NULL")
        params["min_death_sr"] = min_death_sr

    if min_batting_sr_vs_pace is not None:
        agg_conditions.append("pace_sr >= :min_batting_sr_vs_pace AND pace_sr IS NOT NULL")
        params["min_batting_sr_vs_pace"] = min_batting_sr_vs_pace
    if min_batting_sr_vs_spin is not None:
        agg_conditions.append("spin_sr >= :min_batting_sr_vs_spin AND spin_sr IS NOT NULL")
        params["min_batting_sr_vs_spin"] = min_batting_sr_vs_spin

    if min_wickets is not None:
        agg_conditions.append("wickets >= :min_wickets")
        params["min_wickets"] = min_wickets
    if max_wickets is not None:
        agg_conditions.append("wickets <= :max_wickets")
        params["max_wickets"] = max_wickets

    if min_bowling_avg is not None:
        agg_conditions.append("bowling_average >= :min_bowling_avg AND bowling_average IS NOT NULL")
        params["min_bowling_avg"] = min_bowling_avg
    if max_bowling_avg is not None:
        agg_conditions.append("bowling_average <= :max_bowling_avg AND bowling_average IS NOT NULL")
        params["max_bowling_avg"] = max_bowling_avg

    if min_economy is not None:
        agg_conditions.append("economy_rate >= :min_economy AND economy_rate IS NOT NULL")
        params["min_economy"] = min_economy
    if max_economy is not None:
        agg_conditions.append("economy_rate <= :max_economy AND economy_rate IS NOT NULL")
        params["max_economy"] = max_economy

    if min_bowling_sr is not None:
        agg_conditions.append("bowling_strike_rate >= :min_bowling_sr AND bowling_strike_rate IS NOT NULL")
        params["min_bowling_sr"] = min_bowling_sr
    if max_bowling_sr is not None:
        agg_conditions.append("bowling_strike_rate <= :max_bowling_sr AND bowling_strike_rate IS NOT NULL")
        params["max_bowling_sr"] = max_bowling_sr

    if min_balls_bowled is not None and role != "bowler":
        agg_conditions.append("legal_balls_bowled >= :min_balls_bowled")
        params["min_balls_bowled"] = min_balls_bowled

    if max_death_economy is not None:
        agg_conditions.append("death_economy <= :max_death_economy AND death_economy IS NOT NULL")
        params["max_death_economy"] = max_death_economy

    agg_where_clause = " AND ".join(agg_conditions)

    sort_col_map = {
        "runs": "runs",
        "batting_average": "batting_average",
        "batting_strike_rate": "batting_strike_rate",
        "wickets": "wickets",
        "bowling_average": "bowling_average",
        "economy_rate": "economy_rate",
        "matches": "matches",
        "name": "canonical_name",
    }
    sort_column = sort_col_map.get(sort_by, "runs")
    if sort_by == "name":
        order_by_clause = f"ORDER BY canonical_name {'ASC' if sort_dir == 'asc' else 'DESC'}"
    else:
        order_by_clause = f"ORDER BY {sort_column} {'ASC NULLS LAST' if sort_dir == 'asc' else 'DESC NULLS LAST'}"

    offset = (page - 1) * page_size
    params["page_limit"] = page_size
    params["page_offset"] = offset

    sql = f"""
    WITH filtered_matches AS (
        SELECT m.id, m.team1_id, m.team2_id, m.venue_id
        FROM matches m
        WHERE {match_where_clause}
    ),
    batting AS (
        SELECT 
            d.batter_id AS player_id,
            COUNT(DISTINCT mi.match_id) AS matches_batted,
            COUNT(DISTINCT d.innings_id) AS innings_batted,
            SUM(d.batter_runs) AS runs,
            SUM(CASE WHEN d.is_ball_faced_by_batter THEN 1 ELSE 0 END) AS balls_faced,
            SUM(CASE WHEN d.is_boundary_four THEN 1 ELSE 0 END) AS fours,
            SUM(CASE WHEN d.is_boundary_six THEN 1 ELSE 0 END) AS sixes,
            SUM(CASE WHEN d.is_legal_ball AND d.batter_runs = 0 THEN 1 ELSE 0 END) AS dot_balls,
            SUM(CASE WHEN d.phase = 'powerplay' THEN d.batter_runs ELSE 0 END) AS pp_runs,
            SUM(CASE WHEN d.phase = 'powerplay' AND d.is_ball_faced_by_batter THEN 1 ELSE 0 END) AS pp_balls,
            SUM(CASE WHEN d.phase = 'middle' THEN d.batter_runs ELSE 0 END) AS mid_runs,
            SUM(CASE WHEN d.phase = 'middle' AND d.is_ball_faced_by_batter THEN 1 ELSE 0 END) AS mid_balls,
            SUM(CASE WHEN d.phase = 'death' THEN d.batter_runs ELSE 0 END) AS death_runs,
            SUM(CASE WHEN d.phase = 'death' AND d.is_ball_faced_by_batter THEN 1 ELSE 0 END) AS death_balls,
            SUM(CASE WHEN pa.attribute_value = 'pace' THEN d.batter_runs ELSE 0 END) AS pace_runs,
            SUM(CASE WHEN pa.attribute_value = 'pace' AND d.is_ball_faced_by_batter THEN 1 ELSE 0 END) AS pace_balls,
            SUM(CASE WHEN pa.attribute_value = 'spin' THEN d.batter_runs ELSE 0 END) AS spin_runs,
            SUM(CASE WHEN pa.attribute_value = 'spin' AND d.is_ball_faced_by_batter THEN 1 ELSE 0 END) AS spin_balls
        FROM deliveries d
        JOIN match_innings mi ON d.innings_id = mi.id
        JOIN filtered_matches m ON mi.match_id = m.id
        LEFT JOIN player_attributes pa ON d.bowler_id = pa.player_id AND pa.attribute_type = 'bowling_style'
        WHERE mi.is_super_over = FALSE
          {bat_vs_team_clause}
        GROUP BY d.batter_id
    ),
    batting_wkts AS (
        SELECT 
            w.player_out_id AS player_id,
            COUNT(w.id) AS dismissals
        FROM wickets w
        JOIN deliveries d ON w.delivery_id = d.id
        JOIN match_innings mi ON d.innings_id = mi.id
        JOIN filtered_matches m ON mi.match_id = m.id
        WHERE w.is_batter_dismissed = TRUE
          AND mi.is_super_over = FALSE
          {bat_vs_team_clause}
        GROUP BY w.player_out_id
    ),
    bowling AS (
        SELECT 
            d.bowler_id AS player_id,
            COUNT(DISTINCT mi.match_id) AS matches_bowled,
            COUNT(DISTINCT d.innings_id) AS innings_bowled,
            SUM(CASE WHEN d.is_legal_ball THEN 1 ELSE 0 END) AS legal_balls,
            SUM(d.bowling_runs) AS runs_conceded,
            SUM(CASE WHEN d.is_legal_ball AND d.batter_runs = 0 THEN 1 ELSE 0 END) AS bowl_dots,
            SUM(CASE WHEN d.phase = 'death' AND d.is_legal_ball THEN 1 ELSE 0 END) AS death_legal_balls,
            SUM(CASE WHEN d.phase = 'death' THEN d.bowling_runs ELSE 0 END) AS death_runs_conceded
        FROM deliveries d
        JOIN match_innings mi ON d.innings_id = mi.id
        JOIN filtered_matches m ON mi.match_id = m.id
        WHERE mi.is_super_over = FALSE
          {bowl_vs_team_clause}
        GROUP BY d.bowler_id
    ),
    bowler_wkts AS (
        SELECT 
            d.bowler_id AS player_id,
            COUNT(w.id) AS wickets
        FROM wickets w
        JOIN deliveries d ON w.delivery_id = d.id
        JOIN match_innings mi ON d.innings_id = mi.id
        JOIN filtered_matches m ON mi.match_id = m.id
        WHERE w.is_bowler_wicket = TRUE
          AND mi.is_super_over = FALSE
          {bowl_vs_team_clause}
        GROUP BY d.bowler_id
    ),
    aggregated AS (
        SELECT
            p.id,
            p.canonical_name,
            GREATEST(COALESCE(b.matches_batted, 0), COALESCE(bo.matches_bowled, 0)) AS matches,
            COALESCE(b.innings_batted, 0) AS innings_batted,
            COALESCE(b.runs, 0) AS runs,
            COALESCE(b.balls_faced, 0) AS balls_faced,
            COALESCE(bw.dismissals, 0) AS dismissals,
            COALESCE(b.fours, 0) AS fours,
            COALESCE(b.sixes, 0) AS sixes,
            COALESCE(b.dot_balls, 0) AS dot_balls,
            CASE WHEN COALESCE(bw.dismissals, 0) > 0 THEN ROUND((COALESCE(b.runs, 0)::numeric / bw.dismissals), 2) ELSE NULL END AS batting_average,
            CASE WHEN COALESCE(b.balls_faced, 0) > 0 THEN ROUND((COALESCE(b.runs, 0)::numeric * 100.0 / b.balls_faced), 2) ELSE NULL END AS batting_strike_rate,
            CASE WHEN COALESCE(b.balls_faced, 0) > 0 THEN ROUND(((COALESCE(b.fours, 0) + COALESCE(b.sixes, 0))::numeric * 100.0 / b.balls_faced), 2) ELSE NULL END AS boundary_percentage,
            CASE WHEN COALESCE(b.balls_faced, 0) > 0 THEN ROUND((COALESCE(b.dot_balls, 0)::numeric * 100.0 / b.balls_faced), 2) ELSE NULL END AS dot_ball_percentage,
            -- phases
            COALESCE(b.pp_runs, 0) AS pp_runs,
            COALESCE(b.pp_balls, 0) AS pp_balls,
            CASE WHEN COALESCE(b.pp_balls, 0) > 0 THEN ROUND((COALESCE(b.pp_runs, 0)::numeric * 100.0 / b.pp_balls), 2) ELSE NULL END AS pp_sr,
            COALESCE(b.mid_runs, 0) AS middle_runs,
            COALESCE(b.mid_balls, 0) AS middle_balls,
            CASE WHEN COALESCE(b.mid_balls, 0) > 0 THEN ROUND((COALESCE(b.mid_runs, 0)::numeric * 100.0 / b.mid_balls), 2) ELSE NULL END AS middle_sr,
            COALESCE(b.death_runs, 0) AS death_runs,
            COALESCE(b.death_balls, 0) AS death_balls,
            CASE WHEN COALESCE(b.death_balls, 0) > 0 THEN ROUND((COALESCE(b.death_runs, 0)::numeric * 100.0 / b.death_balls), 2) ELSE NULL END AS death_sr,
            -- pace / spin
            COALESCE(b.pace_runs, 0) AS pace_runs,
            COALESCE(b.pace_balls, 0) AS pace_balls,
            CASE WHEN COALESCE(b.pace_balls, 0) > 0 THEN ROUND((COALESCE(b.pace_runs, 0)::numeric * 100.0 / b.pace_balls), 2) ELSE NULL END AS pace_sr,
            COALESCE(b.spin_runs, 0) AS spin_runs,
            COALESCE(b.spin_balls, 0) AS spin_balls,
            CASE WHEN COALESCE(b.spin_balls, 0) > 0 THEN ROUND((COALESCE(b.spin_runs, 0)::numeric * 100.0 / b.spin_balls), 2) ELSE NULL END AS spin_sr,
            -- bowling
            COALESCE(bo.innings_bowled, 0) AS innings_bowled,
            COALESCE(bo.legal_balls, 0) AS legal_balls_bowled,
            CONCAT(COALESCE(bo.legal_balls, 0) / 6, '.', COALESCE(bo.legal_balls, 0) % 6) AS overs_bowled,
            COALESCE(bo.runs_conceded, 0) AS runs_conceded,
            COALESCE(bow.wickets, 0) AS wickets,
            CASE WHEN COALESCE(bow.wickets, 0) > 0 THEN ROUND((COALESCE(bo.runs_conceded, 0)::numeric / bow.wickets), 2) ELSE NULL END AS bowling_average,
            CASE WHEN COALESCE(bo.legal_balls, 0) > 0 THEN ROUND((COALESCE(bo.runs_conceded, 0)::numeric * 6.0 / bo.legal_balls), 2) ELSE NULL END AS economy_rate,
            CASE WHEN COALESCE(bow.wickets, 0) > 0 THEN ROUND((COALESCE(bo.legal_balls, 0)::numeric / bow.wickets), 2) ELSE NULL END AS bowling_strike_rate,
            CASE WHEN COALESCE(bo.legal_balls, 0) > 0 THEN ROUND((COALESCE(bo.bowl_dots, 0)::numeric * 100.0 / bo.legal_balls), 2) ELSE NULL END AS bowling_dot_ball_percentage,
            COALESCE(bo.death_legal_balls, 0) AS death_balls_bowled,
            COALESCE(bo.death_runs_conceded, 0) AS death_runs_conceded,
            CASE WHEN COALESCE(bo.death_legal_balls, 0) > 0 THEN ROUND((COALESCE(bo.death_runs_conceded, 0)::numeric * 6.0 / bo.death_legal_balls), 2) ELSE NULL END AS death_economy
        FROM players p
        LEFT JOIN batting b ON p.id = b.player_id
        LEFT JOIN batting_wkts bw ON p.id = bw.player_id
        LEFT JOIN bowling bo ON p.id = bo.player_id
        LEFT JOIN bowler_wkts bow ON p.id = bow.player_id
        WHERE (b.balls_faced IS NOT NULL OR bo.legal_balls IS NOT NULL)
    )
    SELECT
        id, canonical_name, matches, innings_batted, runs, balls_faced, dismissals, fours, sixes, dot_balls,
        batting_average, batting_strike_rate, boundary_percentage, dot_ball_percentage,
        pp_runs, pp_balls, pp_sr, middle_runs, middle_balls, middle_sr, death_runs, death_balls, death_sr,
        pace_runs, pace_balls, pace_sr, spin_runs, spin_balls, spin_sr,
        innings_bowled, legal_balls_bowled, overs_bowled, runs_conceded, wickets,
        bowling_average, economy_rate, bowling_strike_rate, bowling_dot_ball_percentage,
        death_balls_bowled, death_runs_conceded, death_economy,
        COUNT(*) OVER() AS total_count
    FROM aggregated
    WHERE {agg_where_clause}
    {order_by_clause}
    LIMIT :page_limit OFFSET :page_offset
    """

    rows = db.execute(text(sql), params).fetchall()
    total = rows[0][41] if rows else 0
    total_pages = (total + page_size - 1) // page_size if total > 0 else 0

    items = []
    for r in rows:
        items.append(PlayerPerformanceItem(
            id=str(r[0]),
            name=str(r[1]),
            matches=int(r[2]),
            innings_batted=int(r[3]),
            runs=int(r[4]),
            balls_faced=int(r[5]),
            dismissals=int(r[6]),
            fours=int(r[7]),
            sixes=int(r[8]),
            dot_balls=int(r[9]),
            batting_average=float(r[10]) if r[10] is not None else None,
            batting_strike_rate=float(r[11]) if r[11] is not None else None,
            boundary_percentage=float(r[12]) if r[12] is not None else None,
            dot_ball_percentage=float(r[13]) if r[13] is not None else None,
            pp_runs=int(r[14]),
            pp_balls=int(r[15]),
            pp_sr=float(r[16]) if r[16] is not None else None,
            middle_runs=int(r[17]),
            middle_balls=int(r[18]),
            middle_sr=float(r[19]) if r[19] is not None else None,
            death_runs=int(r[20]),
            death_balls=int(r[21]),
            death_sr=float(r[22]) if r[22] is not None else None,
            pace_runs=int(r[23]),
            pace_balls=int(r[24]),
            pace_sr=float(r[25]) if r[25] is not None else None,
            spin_runs=int(r[26]),
            spin_balls=int(r[27]),
            spin_sr=float(r[28]) if r[28] is not None else None,
            innings_bowled=int(r[29]),
            legal_balls_bowled=int(r[30]),
            overs_bowled=str(r[31]),
            runs_conceded=int(r[32]),
            wickets=int(r[33]),
            bowling_average=float(r[34]) if r[34] is not None else None,
            economy_rate=float(r[35]) if r[35] is not None else None,
            bowling_strike_rate=float(r[36]) if r[36] is not None else None,
            bowling_dot_ball_percentage=float(r[37]) if r[37] is not None else None,
            death_balls_bowled=int(r[38]),
            death_runs_conceded=int(r[39]),
            death_economy=float(r[40]) if r[40] is not None else None,
        ))

    return PlayerPerformanceResponse(
        players=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
        active_filters_count=active_filters_count,
    )


@router.get("/players/{player_id}", response_model=PlayerSummary)
def get_player(player_id: str, db: Session = Depends(get_db)):
    player = db.get(Player, player_id)
    if not player:
        raise HTTPException(status_code=404, detail="Player not found")
    alias = db.execute(
        select(PlayerAlias).where(PlayerAlias.player_id == player_id).limit(1)
    ).scalar_one_or_none()
    external = db.scalar(select(PlayerExternalProfile).where(PlayerExternalProfile.player_id == player_id).order_by(PlayerExternalProfile.fetched_at.desc()))
    deep = db.scalar(select(Delivery.id).where(or_(Delivery.batter_id == player_id, Delivery.bowler_id == player_id)).limit(1))
    attrs = _player_bio_fields(db, player.id, player.canonical_name)
    return PlayerSummary(
        id=player.id,
        name=player.canonical_name,
        source_player_id=alias.source_player_id if alias else None,
        **attrs,
        data_source="CPI + Cricket Database API" if external else "CPI Cricsheet" if deep else "CPI player record",
        data_availability="deep" if deep else "basic" if external and external.basic_stats else "minimal",
        external_basic_stats=external.basic_stats if external and external.basic_stats else None,
        analytics_notice=("In-depth performance analytics are currently unavailable for this player. Basic player statistics are displayed."
                          if not deep and external and external.basic_stats else None),
    )


@router.get("/players/{player_id}/analytics", response_model=PlayerAnalyticsResponse)
def get_player_analytics(
    player_id: str,
    format: Optional[str] = None,
    gender: Optional[str] = None,
    competition: Optional[str] = None,
    start_year: Optional[int] = None,
    end_year: Optional[int] = None,
    season: Optional[str] = None,
    team_id: Optional[str] = None,
    vs_team_id: Optional[str] = None,
    venue_id: Optional[str] = None,
    bowling_style: Optional[str] = None,
    phase: Optional[str] = None,
    db: Session = Depends(get_db),
):
    if start_year is not None and end_year is not None and start_year > end_year:
        raise HTTPException(status_code=422, detail="From Year must be less than or equal to To Year.")
    player = db.get(Player, player_id)
    if not player:
        raise HTTPException(status_code=404, detail="Player not found")

    alias = db.execute(
        select(PlayerAlias).where(PlayerAlias.player_id == player_id).limit(1)
    ).scalar_one_or_none()
    source_player_id = alias.source_player_id if alias else None

    # Base match filter params
    params: Dict[str, Any] = {"pid": player_id}
    match_conds = ["1=1"]
    if format:
        match_conds.append("m.match_format = :format")
        params["format"] = format
    if gender and gender.lower() != "all":
        if gender.lower() not in {"male", "female"}:
            raise HTTPException(status_code=422, detail="Gender must be male, female, or all.")
        match_conds.append("LOWER(m.gender) = :gender")
        params["gender"] = gender.lower()
    if competition:
        match_conds.append("EXISTS (SELECT 1 FROM tournaments filter_tournament WHERE filter_tournament.id = m.tournament_id AND filter_tournament.name ILIKE :competition)")
        params["competition"] = f"%{competition}%"
    if start_year:
        match_conds.append("m.start_date >= :start_date")
        params["start_date"] = f"{start_year}-01-01"
    if end_year:
        match_conds.append("m.start_date <= :end_date")
        params["end_date"] = f"{end_year}-12-31"
    if season:
        match_conds.append("m.season = :season")
        params["season"] = season
    if venue_id:
        match_conds.append("m.venue_id = :venue_id")
        params["venue_id"] = venue_id
    if vs_team_id:
        match_conds.append("(m.team1_id = :vs_team_id OR m.team2_id = :vs_team_id)")
        params["vs_team_id"] = vs_team_id

    match_filter_sql = " AND ".join(match_conds)

    # Batting filter SQL
    bat_conds = ["mi.is_super_over = FALSE"]
    if team_id:
        bat_conds.append("mi.batting_team_id = :team_id")
        params["team_id"] = team_id
    if vs_team_id:
        bat_conds.append("(CASE WHEN mi.batting_team_id = m.team1_id THEN m.team2_id ELSE m.team1_id END) = :vs_team_id")
    if phase:
        bat_conds.append("d.phase = :phase")
        params["phase"] = phase
    if bowling_style:
        bat_conds.append("pa.attribute_value = :bowling_style")
        params["bowling_style"] = bowling_style

    bat_filter_sql = " AND ".join(bat_conds)

    # Bowling filter SQL
    bowl_conds = ["mi.is_super_over = FALSE"]
    if team_id:
        bowl_conds.append("(CASE WHEN mi.batting_team_id = m.team1_id THEN m.team2_id ELSE m.team1_id END) = :team_id")
    if vs_team_id:
        bowl_conds.append("mi.batting_team_id = :vs_team_id")
    if phase:
        bowl_conds.append("d.phase = :phase")

    bowl_filter_sql = " AND ".join(bowl_conds)

    # 1. Batting overview
    sql_bat = f"""
    SELECT 
        COUNT(DISTINCT mi.match_id) as matches,
        COUNT(DISTINCT d.innings_id) as innings,
        COALESCE(SUM(d.batter_runs), 0) as runs,
        COALESCE(SUM(CASE WHEN d.is_ball_faced_by_batter THEN 1 ELSE 0 END), 0) as balls_faced,
        COALESCE(SUM(CASE WHEN d.is_boundary_four THEN 1 ELSE 0 END), 0) as fours,
        COALESCE(SUM(CASE WHEN d.is_boundary_six THEN 1 ELSE 0 END), 0) as sixes,
        COALESCE(SUM(CASE WHEN d.is_legal_ball AND d.batter_runs = 0 THEN 1 ELSE 0 END), 0) as dot_balls
    FROM deliveries d
    JOIN match_innings mi ON d.innings_id = mi.id
    JOIN matches m ON mi.match_id = m.id
    LEFT JOIN player_attributes pa ON d.bowler_id = pa.player_id AND pa.attribute_type = 'bowling_style'
    WHERE d.batter_id = :pid AND {match_filter_sql} AND {bat_filter_sql}
    """
    bat_res = db.execute(text(sql_bat), params).fetchone()
    b_matches = bat_res[0] if bat_res else 0
    b_innings = bat_res[1] if bat_res else 0
    b_runs = bat_res[2] if bat_res else 0
    b_balls = bat_res[3] if bat_res else 0
    b_fours = bat_res[4] if bat_res else 0
    b_sixes = bat_res[5] if bat_res else 0
    b_dots = bat_res[6] if bat_res else 0

    sql_wkts = f"""
    SELECT COUNT(w.id)
    FROM wickets w
    JOIN deliveries d ON w.delivery_id = d.id
    JOIN match_innings mi ON d.innings_id = mi.id
    JOIN matches m ON mi.match_id = m.id
    LEFT JOIN player_attributes pa ON d.bowler_id = pa.player_id AND pa.attribute_type = 'bowling_style'
    WHERE w.player_out_id = :pid AND w.is_batter_dismissed = TRUE
      AND {match_filter_sql} AND {bat_filter_sql}
    """
    b_dismissals = db.execute(text(sql_wkts), params).scalar() or 0
    b_not_outs = max(0, b_innings - b_dismissals)

    sql_hs = f"""
    SELECT COALESCE(MAX(inn_runs), 0) FROM (
        SELECT SUM(d.batter_runs) as inn_runs
        FROM deliveries d
        JOIN match_innings mi ON d.innings_id = mi.id
        JOIN matches m ON mi.match_id = m.id
        LEFT JOIN player_attributes pa ON d.bowler_id = pa.player_id AND pa.attribute_type = 'bowling_style'
        WHERE d.batter_id = :pid AND {match_filter_sql} AND {bat_filter_sql}
        GROUP BY d.innings_id
    ) sub
    """
    b_hs = db.execute(text(sql_hs), params).scalar() or 0

    b_avg = round(float(b_runs) / b_dismissals, 2) if b_dismissals > 0 else None
    b_sr = round(float(b_runs) * 100.0 / b_balls, 2) if b_balls > 0 else None
    b_bound_pct = round(float(b_fours + b_sixes) * 100.0 / b_balls, 2) if b_balls > 0 else None
    b_dot_pct = round(float(b_dots) * 100.0 / b_balls, 2) if b_balls > 0 else None

    batting_resp = BattingStatsResponse(
        player_id=player_id,
        matches=b_matches,
        innings=b_innings,
        not_outs=b_not_outs,
        runs=b_runs,
        balls_faced=b_balls,
        dismissals=b_dismissals,
        highest_score=b_hs,
        fours=b_fours,
        sixes=b_sixes,
        average=b_avg,
        strike_rate=b_sr,
        boundary_percentage=b_bound_pct,
        dot_ball_percentage=b_dot_pct,
        sample_note=f"Based on {b_innings} innings ({b_balls} balls faced)",
    )

    # 2. Bowling overview
    sql_bowl = f"""
    SELECT 
        COUNT(DISTINCT d.innings_id) as innings_bowled,
        COALESCE(SUM(CASE WHEN d.is_legal_ball THEN 1 ELSE 0 END), 0) as legal_balls,
        COALESCE(SUM(d.bowling_runs), 0) as runs_conceded,
        COALESCE(SUM(CASE WHEN d.is_legal_ball AND d.batter_runs = 0 THEN 1 ELSE 0 END), 0) as dot_balls,
        COALESCE(SUM(CASE WHEN d.is_legal_ball AND (d.is_boundary_four OR d.is_boundary_six) THEN 1 ELSE 0 END), 0) as boundaries
    FROM deliveries d
    JOIN match_innings mi ON d.innings_id = mi.id
    JOIN matches m ON mi.match_id = m.id
    WHERE d.bowler_id = :pid AND {match_filter_sql} AND {bowl_filter_sql}
    """
    bowl_res = db.execute(text(sql_bowl), params).fetchone()
    bo_innings = bowl_res[0] if bowl_res else 0
    bo_legal = bowl_res[1] if bowl_res else 0
    bo_runs = bowl_res[2] if bowl_res else 0
    bo_dots = bowl_res[3] if bowl_res else 0
    bo_boundaries = bowl_res[4] if bowl_res else 0

    sql_bowl_wkts = f"""
    SELECT COUNT(w.id)
    FROM wickets w
    JOIN deliveries d ON w.delivery_id = d.id
    JOIN match_innings mi ON d.innings_id = mi.id
    JOIN matches m ON mi.match_id = m.id
    WHERE d.bowler_id = :pid AND w.is_bowler_wicket = TRUE
      AND {match_filter_sql} AND {bowl_filter_sql}
    """
    bo_wkts = db.execute(text(sql_bowl_wkts), params).scalar() or 0

    bo_overs = f"{bo_legal // 6}.{bo_legal % 6}"
    bo_econ = round(float(bo_runs) * 6.0 / bo_legal, 2) if bo_legal > 0 else None
    bo_avg = round(float(bo_runs) / bo_wkts, 2) if bo_wkts > 0 else None
    bo_sr = round(float(bo_legal) / bo_wkts, 2) if bo_wkts > 0 else None
    bo_dot_pct = round(float(bo_dots) * 100.0 / bo_legal, 2) if bo_legal > 0 else None
    bo_boundary_pct = round(float(bo_boundaries) * 100.0 / bo_legal, 2) if bo_legal > 0 else None

    bowling_resp = BowlingStatsResponse(
        player_id=player_id,
        innings_bowled=bo_innings,
        legal_balls=bo_legal,
        overs_display=bo_overs,
        runs_conceded=bo_runs,
        wickets=bo_wkts,
        dot_balls=bo_dots,
        economy_rate=bo_econ,
        bowling_average=bo_avg,
        bowling_strike_rate=bo_sr,
        dot_ball_percentage=bo_dot_pct,
        boundary_percentage=bo_boundary_pct,
        sample_note=f"Based on {bo_innings} innings ({bo_overs} overs)",
    )

    # 3. Pace vs Spin Batting Splits
    sql_pace_spin = f"""
    SELECT 
        pa.attribute_value as style,
        COALESCE(SUM(d.batter_runs), 0) as runs,
        COALESCE(SUM(CASE WHEN d.is_ball_faced_by_batter THEN 1 ELSE 0 END), 0) as balls,
        COALESCE(SUM(CASE WHEN d.is_boundary_four THEN 1 ELSE 0 END), 0) as fours,
        COALESCE(SUM(CASE WHEN d.is_boundary_six THEN 1 ELSE 0 END), 0) as sixes,
        COALESCE(SUM(CASE WHEN d.is_legal_ball AND d.batter_runs = 0 THEN 1 ELSE 0 END), 0) as dot_balls
    FROM deliveries d
    JOIN match_innings mi ON d.innings_id = mi.id
    JOIN matches m ON mi.match_id = m.id
    JOIN player_attributes pa ON d.bowler_id = pa.player_id AND pa.attribute_type = 'bowling_style'
    WHERE d.batter_id = :pid AND {match_filter_sql} AND mi.is_super_over = FALSE
    GROUP BY pa.attribute_value
    """
    ps_rows = db.execute(text(sql_pace_spin), params).fetchall()

    sql_ps_wkts = f"""
    SELECT 
        pa.attribute_value as style,
        COUNT(w.id) as dismissals
    FROM wickets w
    JOIN deliveries d ON w.delivery_id = d.id
    JOIN match_innings mi ON d.innings_id = mi.id
    JOIN matches m ON mi.match_id = m.id
    JOIN player_attributes pa ON d.bowler_id = pa.player_id AND pa.attribute_type = 'bowling_style'
    WHERE w.player_out_id = :pid AND w.is_batter_dismissed = TRUE
      AND {match_filter_sql} AND mi.is_super_over = FALSE
    GROUP BY pa.attribute_value
    """
    ps_wkt_map = {r[0]: r[1] for r in db.execute(text(sql_ps_wkts), params).fetchall()}

    pace_spin_items = []
    for r in ps_rows:
        style = r[0]
        r_runs = int(r[1])
        r_balls = int(r[2])
        r_fours = int(r[3])
        r_sixes = int(r[4])
        r_dots = int(r[5])
        r_dismissals = ps_wkt_map.get(style, 0)
        pace_spin_items.append(PaceSpinSplit(
            style=style,
            runs=r_runs,
            balls=r_balls,
            strike_rate=round(r_runs * 100.0 / r_balls, 2) if r_balls > 0 else None,
            dismissals=r_dismissals,
            average=round(r_runs / r_dismissals, 2) if r_dismissals > 0 else None,
            fours=r_fours,
            sixes=r_sixes,
            dot_balls=r_dots,
            dot_ball_percentage=round(r_dots * 100.0 / r_balls, 2) if r_balls > 0 else None,
            boundary_percentage=round((r_fours + r_sixes) * 100.0 / r_balls, 2) if r_balls > 0 else None,
        ))

    # 4. Phase Breakdown
    sql_phases_bat = f"""
    SELECT 
        d.phase,
        COALESCE(SUM(d.batter_runs), 0) as runs,
        COALESCE(SUM(CASE WHEN d.is_ball_faced_by_batter THEN 1 ELSE 0 END), 0) as balls,
        COALESCE(SUM(CASE WHEN d.is_boundary_four THEN 1 ELSE 0 END), 0) as fours,
        COALESCE(SUM(CASE WHEN d.is_boundary_six THEN 1 ELSE 0 END), 0) as sixes,
        COALESCE(SUM(CASE WHEN d.is_legal_ball AND d.batter_runs = 0 THEN 1 ELSE 0 END), 0) as dot_balls
    FROM deliveries d
    JOIN match_innings mi ON d.innings_id = mi.id
    JOIN matches m ON mi.match_id = m.id
    WHERE d.batter_id = :pid AND {match_filter_sql} AND mi.is_super_over = FALSE
    GROUP BY d.phase
    """
    pb_rows = db.execute(text(sql_phases_bat), params).fetchall()

    sql_pb_wkts = f"""
    SELECT 
        d.phase,
        COUNT(w.id) as dismissals
    FROM wickets w
    JOIN deliveries d ON w.delivery_id = d.id
    JOIN match_innings mi ON d.innings_id = mi.id
    JOIN matches m ON mi.match_id = m.id
    WHERE w.player_out_id = :pid AND w.is_batter_dismissed = TRUE
      AND {match_filter_sql} AND mi.is_super_over = FALSE
    GROUP BY d.phase
    """
    pb_wkt_map = {r[0]: r[1] for r in db.execute(text(sql_pb_wkts), params).fetchall()}

    phase_items = []
    for r in pb_rows:
        ph = r[0]
        if ph in ('powerplay', 'middle', 'death'):
            p_runs = int(r[1])
            p_balls = int(r[2])
            p_fours = int(r[3])
            p_sixes = int(r[4])
            p_dots = int(r[5])
            p_dismissals = pb_wkt_map.get(ph, 0)
            phase_items.append(PhaseBreakdownItem(
                phase=ph,
                role="batting",
                runs=p_runs,
                balls=p_balls,
                strike_rate=round(p_runs * 100.0 / p_balls, 2) if p_balls > 0 else None,
                dismissals=p_dismissals,
                average=round(p_runs / p_dismissals, 2) if p_dismissals > 0 else None,
                fours=p_fours,
                sixes=p_sixes,
                dot_ball_percentage=round(p_dots * 100.0 / p_balls, 2) if p_balls > 0 else None,
                boundary_percentage=round((p_fours + p_sixes) * 100.0 / p_balls, 2) if p_balls > 0 else None,
            ))

    # Format-aware bowling phases. Limited overs uses the already-ingested phase
    # labels; Test/MDM uses thirds of each actual innings and labels them explicitly.
    phase_expr = "CASE WHEN match_format IN ('Test', 'MDM') THEN CASE WHEN (over_number + 1) * 3 <= innings_overs THEN 'early_innings' WHEN (over_number + 1) * 3 <= innings_overs * 2 THEN 'middle_innings' ELSE 'late_innings' END ELSE phase END"
    bowling_phase_scope = f"""
      WITH selected_innings AS (
        SELECT DISTINCT d.innings_id
        FROM deliveries d
        JOIN match_innings mi ON d.innings_id = mi.id
        JOIN matches m ON mi.match_id = m.id
        WHERE d.bowler_id = :pid AND {match_filter_sql} AND mi.is_super_over = FALSE
      ), innings_lengths AS (
        SELECT d.innings_id, MAX(d.over_number) + 1 AS innings_overs
        FROM deliveries d JOIN selected_innings si ON si.innings_id = d.innings_id
        GROUP BY d.innings_id
      ), scoped AS (
        SELECT d.*, m.match_format, il.innings_overs
        FROM deliveries d
        JOIN selected_innings si ON si.innings_id = d.innings_id
        JOIN innings_lengths il ON il.innings_id = d.innings_id
        JOIN match_innings mi ON d.innings_id = mi.id
        JOIN matches m ON mi.match_id = m.id
        WHERE d.bowler_id = :pid AND mi.is_super_over = FALSE
      )
    """
    phase_rows = db.execute(text(bowling_phase_scope + f"""
      SELECT {phase_expr} AS phase,
             SUM(CASE WHEN is_legal_ball THEN 1 ELSE 0 END) AS legal_balls,
             SUM(bowling_runs) AS runs_conceded,
             SUM(CASE WHEN is_legal_ball AND batter_runs = 0 THEN 1 ELSE 0 END) AS dots,
             SUM(CASE WHEN is_legal_ball AND (is_boundary_four OR is_boundary_six) THEN 1 ELSE 0 END) AS boundaries
      FROM scoped WHERE {phase_expr} IS NOT NULL
      GROUP BY 1 ORDER BY 1
    """), params).mappings().all()
    phase_wickets = db.execute(text(bowling_phase_scope + f"""
      SELECT {phase_expr} AS phase, COUNT(w.id) AS wickets
      FROM scoped
      JOIN wickets w ON w.delivery_id = scoped.id AND w.is_bowler_wicket = TRUE
      WHERE {phase_expr} IS NOT NULL GROUP BY 1
    """), params).mappings().all()
    phase_wicket_map = {row['phase']: int(row['wickets'] or 0) for row in phase_wickets}
    bowling_phase_items = []
    for row in phase_rows:
        label = str(row['phase'])
        balls, runs = int(row['legal_balls'] or 0), int(row['runs_conceded'] or 0)
        wickets = phase_wicket_map.get(label, 0)
        bowling_phase_items.append(BowlingPhaseBreakdownItem(
            phase=label, legal_balls=balls, overs=f"{balls // 6}.{balls % 6}",
            wickets=wickets, runs_conceded=runs,
            economy=round(runs * 6 / balls, 2) if balls else None,
            bowling_average=round(runs / wickets, 2) if wickets else None,
            bowling_strike_rate=round(balls / wickets, 2) if wickets else None,
            dot_ball_percentage=round(int(row['dots'] or 0) * 100 / balls, 2) if balls else None,
            boundary_percentage=round(int(row['boundaries'] or 0) * 100 / balls, 2) if balls else None,
        ))

    # Bowler style splits are only emitted for known styles; unknown style metadata
    # is omitted instead of guessed as pace or spin.
    bowling_style_rows = db.execute(text(f"""
      SELECT CASE
               WHEN LOWER(pa.attribute_value) LIKE '%spin%' OR LOWER(pa.attribute_value) LIKE '%break%' OR LOWER(pa.attribute_value) LIKE '%orthodox%' THEN 'spin'
               WHEN LOWER(pa.attribute_value) LIKE '%fast%' OR LOWER(pa.attribute_value) LIKE '%pace%' OR LOWER(pa.attribute_value) LIKE '%medium%' THEN 'pace'
               ELSE NULL END AS style,
             SUM(CASE WHEN d.is_legal_ball THEN 1 ELSE 0 END) AS legal_balls,
             SUM(d.bowling_runs) AS runs_conceded,
             SUM(CASE WHEN d.is_legal_ball AND d.batter_runs = 0 THEN 1 ELSE 0 END) AS dots,
             SUM(CASE WHEN d.is_legal_ball AND (d.is_boundary_four OR d.is_boundary_six) THEN 1 ELSE 0 END) AS boundaries,
             COUNT(w.id) AS wickets
      FROM deliveries d
      JOIN match_innings mi ON d.innings_id = mi.id
      JOIN matches m ON mi.match_id = m.id
      JOIN player_attributes pa ON pa.player_id = d.bowler_id AND pa.attribute_type = 'bowling_style'
      LEFT JOIN wickets w ON w.delivery_id = d.id AND w.is_bowler_wicket = TRUE
      WHERE d.bowler_id = :pid AND {match_filter_sql} AND mi.is_super_over = FALSE
      GROUP BY 1 HAVING CASE
               WHEN LOWER(pa.attribute_value) LIKE '%spin%' OR LOWER(pa.attribute_value) LIKE '%break%' OR LOWER(pa.attribute_value) LIKE '%orthodox%' THEN 'spin'
               WHEN LOWER(pa.attribute_value) LIKE '%fast%' OR LOWER(pa.attribute_value) LIKE '%pace%' OR LOWER(pa.attribute_value) LIKE '%medium%' THEN 'pace'
               ELSE NULL END IS NOT NULL
    """), params).mappings().all()
    bowling_pace_spin_items = []
    for row in bowling_style_rows:
        balls, runs, wickets = int(row['legal_balls'] or 0), int(row['runs_conceded'] or 0), int(row['wickets'] or 0)
        bowling_pace_spin_items.append(BowlingPaceSpinSplit(
            style=row['style'], legal_balls=balls, overs=f"{balls // 6}.{balls % 6}",
            wickets=wickets, runs_conceded=runs,
            economy=round(runs * 6 / balls, 2) if balls else None,
            bowling_average=round(runs / wickets, 2) if wickets else None,
            bowling_strike_rate=round(balls / wickets, 2) if wickets else None,
            dot_ball_percentage=round(int(row['dots'] or 0) * 100 / balls, 2) if balls else None,
            boundary_percentage=round(int(row['boundaries'] or 0) * 100 / balls, 2) if balls else None,
        ))

    # 5. Format Breakdown
    sql_fmt_bat = """
    SELECT 
        m.match_format,
        COUNT(DISTINCT m.id) as matches,
        COUNT(DISTINCT d.innings_id) as innings,
        COALESCE(SUM(d.batter_runs), 0) as runs,
        COALESCE(SUM(CASE WHEN d.is_ball_faced_by_batter THEN 1 ELSE 0 END), 0) as balls
    FROM deliveries d
    JOIN match_innings mi ON d.innings_id = mi.id
    JOIN matches m ON mi.match_id = m.id
    WHERE d.batter_id = :pid AND mi.is_super_over = FALSE
    GROUP BY m.match_format
    """
    fmt_bat_rows = {r[0]: r for r in db.execute(text(sql_fmt_bat), {"pid": player_id}).fetchall()}

    sql_fmt_wkts = """
    SELECT 
        m.match_format,
        COUNT(w.id) as dismissals
    FROM wickets w
    JOIN deliveries d ON w.delivery_id = d.id
    JOIN match_innings mi ON d.innings_id = mi.id
    JOIN matches m ON mi.match_id = m.id
    WHERE w.player_out_id = :pid AND w.is_batter_dismissed = TRUE AND mi.is_super_over = FALSE
    GROUP BY m.match_format
    """
    fmt_wkt_map = {r[0]: r[1] for r in db.execute(text(sql_fmt_wkts), {"pid": player_id}).fetchall()}

    sql_fmt_bowl = """
    SELECT 
        m.match_format,
        COUNT(DISTINCT d.innings_id) as innings_bowled,
        COALESCE(SUM(CASE WHEN d.is_legal_ball THEN 1 ELSE 0 END), 0) as legal_balls,
        COALESCE(SUM(d.bowling_runs), 0) as runs_conceded
    FROM deliveries d
    JOIN match_innings mi ON d.innings_id = mi.id
    JOIN matches m ON mi.match_id = m.id
    WHERE d.bowler_id = :pid AND mi.is_super_over = FALSE
    GROUP BY m.match_format
    """
    fmt_bowl_rows = {r[0]: r for r in db.execute(text(sql_fmt_bowl), {"pid": player_id}).fetchall()}

    sql_fmt_bowl_wkts = """
    SELECT 
        m.match_format,
        COUNT(w.id) as wickets
    FROM wickets w
    JOIN deliveries d ON w.delivery_id = d.id
    JOIN match_innings mi ON d.innings_id = mi.id
    JOIN matches m ON mi.match_id = m.id
    WHERE d.bowler_id = :pid AND w.is_bowler_wicket = TRUE AND mi.is_super_over = FALSE
    GROUP BY m.match_format
    """
    fmt_bowl_wkt_map = {r[0]: r[1] for r in db.execute(text(sql_fmt_bowl_wkts), {"pid": player_id}).fetchall()}

    all_seen_formats = ["Test", "ODI", "T20I", "T20", "MDM", "ODM", "Other"]
    format_breakdown = []
    for fmt_name in all_seen_formats:
        fb = fmt_bat_rows.get(fmt_name)
        fbo = fmt_bowl_rows.get(fmt_name)
        if not fb and not fbo:
            continue
        f_matches = int(fb[1]) if fb else (int(fbo[0]) if fbo else 0)
        f_inn_batted = int(fb[2]) if fb else 0
        f_runs = int(fb[3]) if fb else 0
        f_balls = int(fb[4]) if fb else 0
        f_dismissals = fmt_wkt_map.get(fmt_name, 0)
        f_bat_avg = round(f_runs / f_dismissals, 2) if f_dismissals > 0 else None
        f_bat_sr = round(f_runs * 100.0 / f_balls, 2) if f_balls > 0 else None

        f_inn_bowled = int(fbo[1]) if fbo else 0
        f_legal = int(fbo[2]) if fbo else 0
        f_runs_c = int(fbo[3]) if fbo else 0
        f_wkts = fmt_bowl_wkt_map.get(fmt_name, 0)
        f_econ = round(f_runs_c * 6.0 / f_legal, 2) if f_legal > 0 else None
        f_bowl_avg = round(f_runs_c / f_wkts, 2) if f_wkts > 0 else None

        format_breakdown.append(FormatBreakdownItem(
            format=fmt_name,
            matches=f_matches,
            innings_batted=f_inn_batted,
            runs=f_runs,
            balls_faced=f_balls,
            batting_average=f_bat_avg,
            batting_strike_rate=f_bat_sr,
            innings_bowled=f_inn_bowled,
            overs_bowled=f"{f_legal // 6}.{f_legal % 6}",
            wickets=f_wkts,
            economy_rate=f_econ,
            bowling_average=f_bowl_avg,
        ))

    # 6. By Opponent Team
    sql_opps = f"""
    SELECT 
        t.id as opp_id,
        t.name as opp_name,
        COUNT(DISTINCT m.id) as matches,
        COALESCE(SUM(d.batter_runs), 0) as runs,
        COALESCE(SUM(CASE WHEN d.is_ball_faced_by_batter THEN 1 ELSE 0 END), 0) as balls
    FROM deliveries d
    JOIN match_innings mi ON d.innings_id = mi.id
    JOIN matches m ON mi.match_id = m.id
    JOIN teams t ON t.id = (CASE WHEN mi.batting_team_id = m.team1_id THEN m.team2_id ELSE m.team1_id END)
    WHERE d.batter_id = :pid AND {match_filter_sql} AND mi.is_super_over = FALSE
    GROUP BY t.id, t.name
    ORDER BY runs DESC
    LIMIT 12
    """
    by_opponent = []
    for r in db.execute(text(sql_opps), params).fetchall():
        o_runs = int(r[3])
        o_balls = int(r[4])
        by_opponent.append(OpponentPerformanceItem(
            opponent_id=str(r[0]),
            opponent_name=str(r[1]),
            matches=int(r[2]),
            runs=o_runs,
            balls_faced=o_balls,
            batting_strike_rate=round(o_runs * 100.0 / o_balls, 2) if o_balls > 0 else None,
            wickets=0,
            overs_bowled="0",
        ))

    # 7. By Venue
    sql_venues = f"""
    SELECT 
        v.id as ven_id,
        v.name as ven_name,
        v.city,
        COUNT(DISTINCT m.id) as matches,
        COALESCE(SUM(d.batter_runs), 0) as runs,
        COALESCE(SUM(CASE WHEN d.is_ball_faced_by_batter THEN 1 ELSE 0 END), 0) as balls
    FROM deliveries d
    JOIN match_innings mi ON d.innings_id = mi.id
    JOIN matches m ON mi.match_id = m.id
    JOIN venues v ON m.venue_id = v.id
    WHERE d.batter_id = :pid AND {match_filter_sql} AND mi.is_super_over = FALSE
    GROUP BY v.id, v.name, v.city
    ORDER BY runs DESC
    LIMIT 10
    """
    by_venue = []
    for r in db.execute(text(sql_venues), params).fetchall():
        v_runs = int(r[4])
        v_balls = int(r[5])
        by_venue.append(VenuePerformanceItem(
            venue_id=str(r[0]),
            venue_name=str(r[1]),
            city=r[2],
            matches=int(r[3]),
            runs=v_runs,
            balls_faced=v_balls,
            batting_strike_rate=round(v_runs * 100.0 / v_balls, 2) if v_balls > 0 else None,
            wickets=0,
            overs_bowled="0",
        ))

    # 8. Year Trends
    sql_years = f"""
    SELECT 
        EXTRACT(YEAR FROM m.start_date)::int as yr,
        COUNT(DISTINCT m.id) as matches,
        COALESCE(SUM(d.batter_runs), 0) as runs,
        COALESCE(SUM(CASE WHEN d.is_ball_faced_by_batter THEN 1 ELSE 0 END), 0) as balls
    FROM deliveries d
    JOIN match_innings mi ON d.innings_id = mi.id
    JOIN matches m ON mi.match_id = m.id
    WHERE d.batter_id = :pid AND {match_filter_sql} AND mi.is_super_over = FALSE AND m.start_date IS NOT NULL
    GROUP BY 1
    ORDER BY 1 ASC
    """
    year_trends = []
    for r in db.execute(text(sql_years), params).fetchall():
        y_runs = int(r[2])
        y_balls = int(r[3])
        year_trends.append(YearTrendItem(
            year=int(r[0]),
            matches=int(r[1]),
            runs=y_runs,
            balls_faced=y_balls,
            batting_strike_rate=round(y_runs * 100.0 / y_balls, 2) if y_balls > 0 else None,
            wickets=0,
            overs_bowled="0",
        ))

    # 9. Recent Matches
    sql_recent = f"""
    SELECT 
        m.id,
        m.start_date,
        m.match_format,
        t.name as opp_name,
        v.name as venue_name,
        COALESCE(SUM(d.batter_runs), 0) as runs,
        COALESCE(SUM(CASE WHEN d.is_ball_faced_by_batter THEN 1 ELSE 0 END), 0) as balls
    FROM deliveries d
    JOIN match_innings mi ON d.innings_id = mi.id
    JOIN matches m ON mi.match_id = m.id
    JOIN teams t ON t.id = (CASE WHEN mi.batting_team_id = m.team1_id THEN m.team2_id ELSE m.team1_id END)
    JOIN venues v ON m.venue_id = v.id
    WHERE d.batter_id = :pid AND {match_filter_sql} AND mi.is_super_over = FALSE AND m.start_date IS NOT NULL
    GROUP BY m.id, m.start_date, m.match_format, t.name, v.name
    ORDER BY m.start_date DESC
    LIMIT 10
    """
    recent_matches = []
    for r in db.execute(text(sql_recent), params).fetchall():
        m_runs = int(r[5])
        m_balls = int(r[6])
        recent_matches.append(RecentMatchItem(
            match_id=str(r[0]),
            match_date=r[1].isoformat() if r[1] else None,
            format=str(r[2]),
            opponent_name=str(r[3]),
            venue_name=str(r[4]),
            runs=m_runs,
            balls_faced=m_balls,
            strike_rate=round(m_runs * 100.0 / m_balls, 2) if m_balls > 0 else None,
            wickets=0,
            overs_bowled="0",
            runs_conceded=0,
        ))

    # 10. Strengths & Weaknesses
    role_metadata = db.execute(
        select(PlayerAttribute.attribute_value)
        .where(PlayerAttribute.player_id == player_id, PlayerAttribute.attribute_type == "primary_role")
        .order_by(PlayerAttribute.confidence.desc())
    ).scalars().first()
    primary_role, role_source, role_confidence = classify_player_role(
        b_balls, b_innings, bo_legal, bo_innings, role_metadata
    )
    batting_strengths, batting_weaknesses = [], []
    bowling_strengths, bowling_weaknesses = [], []

    pace_stat = next((x for x in pace_spin_items if x.style == 'pace'), None)
    spin_stat = next((x for x in pace_spin_items if x.style == 'spin'), None)
    if pace_stat and spin_stat:
        if pace_stat.strike_rate and spin_stat.strike_rate:
            if pace_stat.strike_rate >= spin_stat.strike_rate + 15:
                batting_strengths.append(f"Higher scoring rate against pace ({pace_stat.strike_rate:.1f} SR)")
                batting_weaknesses.append(f"Lower scoring rate against spin ({spin_stat.strike_rate:.1f} SR)")
            elif spin_stat.strike_rate >= pace_stat.strike_rate + 15:
                batting_strengths.append(f"Higher scoring rate against spin ({spin_stat.strike_rate:.1f} SR)")
                batting_weaknesses.append(f"Lower scoring rate against pace ({pace_stat.strike_rate:.1f} SR)")

    death_phase = next((x for x in phase_items if x.phase == 'death'), None)
    pp_phase = next((x for x in phase_items if x.phase == 'powerplay'), None)
    if death_phase and death_phase.strike_rate and death_phase.strike_rate >= 160:
        batting_strengths.append(f"Strong death-phase scoring ({death_phase.strike_rate:.1f} strike rate)")
    if pp_phase and pp_phase.average and pp_phase.average >= 35:
        batting_strengths.append(f"Reliable powerplay starts ({pp_phase.average:.1f} batting average)")
    if pp_phase and pp_phase.dot_ball_percentage and pp_phase.dot_ball_percentage >= 45:
        batting_weaknesses.append(f"Powerplay dot-ball rate is {pp_phase.dot_ball_percentage:.1f}%")

    if bo_legal >= 60 and bo_econ is not None:
        bowling_strengths.append(
            f"Took {bo_wkts} wickets · bowling average {bo_avg:.1f} · strike rate {bo_sr:.1f}"
            if bo_avg is not None and bo_sr is not None
            else f"Took {bo_wkts} wickets in {bo_overs} overs"
        )
        if bo_econ <= 7.2:
            bowling_strengths.append(f"Restrictive economy ({bo_econ:.2f} runs per over across {bo_overs} overs)")
        elif bo_econ >= 9.5:
            bowling_weaknesses.append(f"Economy is high at {bo_econ:.2f} runs per over")
        if bo_dot_pct is not None and bo_dot_pct >= 42:
            bowling_strengths.append(f"Builds pressure with a {bo_dot_pct:.1f}% dot-ball rate")
        elif bo_dot_pct is not None and bo_dot_pct <= 25:
            bowling_weaknesses.append(f"Dot-ball rate is low at {bo_dot_pct:.1f}%")
        if bo_boundary_pct is not None and bo_boundary_pct <= 12:
            bowling_strengths.append(f"Limits boundaries to {bo_boundary_pct:.1f}% of legal balls")
        elif bo_boundary_pct is not None and bo_boundary_pct >= 20:
            bowling_weaknesses.append(f"Concedes a boundary on {bo_boundary_pct:.1f}% of legal balls")
        if bo_avg is not None and bo_avg <= 25:
            bowling_strengths.append(f"Takes wickets at a {bo_avg:.1f} bowling average")
        if bo_sr is not None and bo_sr <= 18:
            bowling_strengths.append(f"Wicket every {bo_sr:.1f} legal deliveries on average")
        if bowling_phase_items:
            best_phase = min((p for p in bowling_phase_items if p.economy is not None), key=lambda p: p.economy, default=None)
            weak_phase = max((p for p in bowling_phase_items if p.economy is not None), key=lambda p: p.economy, default=None)
            if best_phase:
                bowling_strengths.append(f"Most economical in {best_phase.phase.replace('_', ' ')} ({best_phase.economy:.2f})")
            if weak_phase and weak_phase is not best_phase:
                bowling_weaknesses.append(f"Most expensive in {weak_phase.phase.replace('_', ' ')} ({weak_phase.economy:.2f})")
        pace_bowl = next((s for s in bowling_pace_spin_items if s.style == 'pace'), None)
        spin_bowl = next((s for s in bowling_pace_spin_items if s.style == 'spin'), None)
        if pace_bowl and spin_bowl and pace_bowl.legal_balls >= 60 and spin_bowl.legal_balls >= 60:
            more_effective, less_effective = (pace_bowl, spin_bowl) if pace_bowl.economy < spin_bowl.economy else (spin_bowl, pace_bowl)
            bowling_strengths.append(f"More economical against {more_effective.style} ({more_effective.economy:.2f} vs {less_effective.economy:.2f})")

    if b_balls >= 60 and not batting_strengths:
        batting_strengths.append(f"Scored {b_runs:,} runs in {b_innings} batting innings")
    if not batting_weaknesses and b_balls >= 60:
        batting_weaknesses.append(f"Boundary rate: {b_bound_pct:.1f}% · dot-ball rate: {b_dot_pct:.1f}%" if b_bound_pct is not None and b_dot_pct is not None else "No clear batting vulnerability in this sample")
    if bo_legal >= 60 and not bowling_strengths:
        bowling_strengths.append(f"Claimed {bo_wkts} wickets in {bo_overs} overs")
    if not bowling_weaknesses and bo_legal >= 60:
        bowling_weaknesses.append(f"Boundary rate conceded: {bo_boundary_pct:.1f}%" if bo_boundary_pct is not None else "No boundary-rate data in this sample")

    if primary_role in ("Specialist Batter", "Wicketkeeper-Batter"):
        strengths, weaknesses = batting_strengths, batting_weaknesses
    elif primary_role == "Specialist Bowler":
        strengths, weaknesses = bowling_strengths, bowling_weaknesses
    else:
        strengths = batting_strengths + bowling_strengths
        weaknesses = batting_weaknesses + bowling_weaknesses
    if not strengths:
        strengths = ["Insufficient sample for role-specific insights"]
    if not weaknesses:
        weaknesses = ["Insufficient sample for role-specific vulnerabilities"]

    bio = _player_bio_fields(db, player_id, player.canonical_name)
    return PlayerAnalyticsResponse(
        player_id=player_id,
        player_name=player.canonical_name,
        source_player_id=source_player_id,
        full_name=bio["full_name"],
        date_of_birth=bio["date_of_birth"],
        age=bio["age"],
        nationality=bio["nationality"],
        official_role=bio["primary_role"],
        batting_style=bio["batting_style"],
        bowling_style=bio["bowling_style"],
        player_image=bio["player_image"],
        primary_role=primary_role,
        role_source=role_source,
        role_confidence=role_confidence,
        batting=batting_resp,
        bowling=bowling_resp,
        pace_spin=pace_spin_items,
        phases=phase_items,
        bowling_phases=bowling_phase_items,
        bowling_pace_spin=bowling_pace_spin_items,
        format_breakdown=format_breakdown,
        by_opponent=by_opponent,
        by_venue=by_venue,
        year_trends=year_trends,
        recent_matches=recent_matches,
        strengths_weaknesses=StrengthsWeaknessesItem(
            strengths=strengths,
            weaknesses=weaknesses,
            batting_strengths=batting_strengths,
            batting_weaknesses=batting_weaknesses,
            bowling_strengths=bowling_strengths,
            bowling_weaknesses=bowling_weaknesses,
        ),
    )


@router.get("/players/{player_id}/batting", response_model=BattingStatsResponse)
def player_batting(
    player_id: str,
    format: Optional[str] = Query(None),
    competition: Optional[str] = Query(None),
    season: Optional[str] = Query(None),
    exclude_super_overs: bool = Query(True),
    db: Session = Depends(get_db),
):
    player = db.get(Player, player_id)
    if not player:
        raise HTTPException(status_code=404, detail="Player not found")

    match_ids = _match_filter_conditions(db, format, competition, season) if any([format, competition, season]) else None

    # Fetch all deliveries where this player was batter
    stmt = (
        select(
            Delivery.innings_id,
            Delivery.over_number,
            Delivery.delivery_sequence,
            Delivery.batter_runs,
            Delivery.is_legal_ball,
            Delivery.is_ball_faced_by_batter,
            Delivery.is_boundary_four,
            Delivery.is_boundary_six,
            Delivery.phase,
            MatchInnings.is_super_over,
            MatchInnings.match_id,
        )
        .join(MatchInnings, Delivery.innings_id == MatchInnings.id)
        .where(Delivery.batter_id == player_id)
    )
    if match_ids is not None:
        stmt = stmt.where(MatchInnings.match_id.in_(match_ids))
    if exclude_super_overs:
        stmt = stmt.where(MatchInnings.is_super_over == False)

    rows = db.execute(stmt).fetchall()

    # Fetch dismissals for this player with matching filters
    wkt_stmt = (
        select(Wicket.delivery_id, Delivery.innings_id)
        .join(Delivery, Wicket.delivery_id == Delivery.id)
        .join(MatchInnings, Delivery.innings_id == MatchInnings.id)
        .where(
            Wicket.player_out_id == player_id,
            Wicket.is_batter_dismissed == True,
        )
    )
    if match_ids is not None:
        wkt_stmt = wkt_stmt.where(MatchInnings.match_id.in_(match_ids))
    if exclude_super_overs:
        wkt_stmt = wkt_stmt.where(MatchInnings.is_super_over == False)

    wkt_rows = db.execute(wkt_stmt).fetchall()
    dismissed_delivery_ids = set(row[0] for row in wkt_rows)
    dismissed_innings_ids = set(row[1] for row in wkt_rows)

    # Also need to fetch delivery IDs for the batter rows
    # We need to know which deliveries resulted in dismissal
    delivery_stmt = (
        select(Delivery.id, Delivery.innings_id, Delivery.over_number, Delivery.delivery_sequence)
        .join(MatchInnings, Delivery.innings_id == MatchInnings.id)
        .where(Delivery.batter_id == player_id)
    )
    if match_ids is not None:
        delivery_stmt = delivery_stmt.where(MatchInnings.match_id.in_(match_ids))
    if exclude_super_overs:
        delivery_stmt = delivery_stmt.where(MatchInnings.is_super_over == False)
    delivery_id_map = {
        (row[1], row[2], row[3]): row[0]
        for row in db.execute(delivery_stmt).fetchall()
    }

    lines = []
    for row in rows:
        innings_id, over_num, seq, b_runs, legal, ball_faced, is4, is6, phase_str, super_ov, _ = row
        dl_id = delivery_id_map.get((innings_id, over_num, seq))
        was_dismissed = dl_id in dismissed_delivery_ids if dl_id else False
        try:
            phase = Phase(phase_str)
        except (ValueError, TypeError):
            phase = Phase.UNKNOWN
        lines.append(BattingLine(
            innings_id=innings_id,
            over_number=over_num,
            delivery_sequence=seq,
            batter_runs=b_runs,
            is_legal_ball=legal,
            is_ball_faced=ball_faced,
            is_boundary_four=is4,
            is_boundary_six=is6,
            phase=phase,
            was_dismissed=was_dismissed,
            is_super_over=super_ov,
        ))

    stats = calculate_batting_stats(lines, player_id)

    # Ensure any innings where the player was dismissed (e.g. non-striker run out with 0 balls faced)
    # is counted in dismissals and innings
    all_innings_seen = set(row[0] for row in rows)
    extra_dismissals = dismissed_innings_ids - all_innings_seen
    stats.dismissals += len(extra_dismissals)
    stats.innings += len(extra_dismissals)
    sample_note = f"Based on {stats.innings} innings" + (
        f" ({stats.balls_faced} balls faced)" if stats.balls_faced > 0 else ""
    )

    return BattingStatsResponse(
        player_id=player_id,
        matches=len(set(r[10] for r in rows)),
        innings=stats.innings,
        not_outs=stats.not_outs,
        runs=stats.runs,
        balls_faced=stats.balls_faced,
        dismissals=stats.dismissals,
        highest_score=stats.highest_score,
        fours=stats.fours,
        sixes=stats.sixes,
        average=stats.average,
        strike_rate=stats.strike_rate,
        boundary_percentage=stats.boundary_percentage,
        dot_ball_percentage=stats.dot_ball_percentage,
        sample_note=sample_note,
    )


@router.get("/players/{player_id}/bowling", response_model=BowlingStatsResponse)
def player_bowling(
    player_id: str,
    format: Optional[str] = Query(None),
    competition: Optional[str] = Query(None),
    season: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    player = db.get(Player, player_id)
    if not player:
        raise HTTPException(status_code=404, detail="Player not found")

    match_ids = _match_filter_conditions(db, format, competition, season) if any([format, competition, season]) else None

    stmt = (
        select(
            Delivery.innings_id,
            Delivery.over_number,
            Delivery.delivery_sequence,
            Delivery.bowling_runs,
            Delivery.is_legal_ball,
            Delivery.is_boundary_four,
            Delivery.is_boundary_six,
            Delivery.batter_runs,
            Delivery.phase,
            MatchInnings.is_super_over,
        )
        .join(MatchInnings, Delivery.innings_id == MatchInnings.id)
        .where(Delivery.bowler_id == player_id)
    )
    if match_ids is not None:
        stmt = stmt.where(MatchInnings.match_id.in_(match_ids))
    rows = db.execute(stmt).fetchall()

    # Fetch wickets credited to this bowler
    bowler_wicket_delivery_ids = set(
        row[0] for row in db.execute(
            select(Wicket.delivery_id)
            .join(Delivery, Wicket.delivery_id == Delivery.id)
            .where(Delivery.bowler_id == player_id, Wicket.is_bowler_wicket == True)
        ).fetchall()
    )

    # Map delivery keys to IDs
    delivery_stmt = (
        select(Delivery.id, Delivery.innings_id, Delivery.over_number, Delivery.delivery_sequence)
        .join(MatchInnings, Delivery.innings_id == MatchInnings.id)
        .where(Delivery.bowler_id == player_id)
    )
    if match_ids is not None:
        delivery_stmt = delivery_stmt.where(MatchInnings.match_id.in_(match_ids))
    delivery_id_map = {
        (row[1], row[2], row[3]): row[0]
        for row in db.execute(delivery_stmt).fetchall()
    }

    lines = []
    for row in rows:
        inn_id, ov, seq, bowl_runs, legal, is4, is6, bat_runs, phase_str, super_ov = row
        dl_id = delivery_id_map.get((inn_id, ov, seq))
        is_bowler_wkt = dl_id in bowler_wicket_delivery_ids if dl_id else False
        is_dot = legal and bat_runs == 0
        is_boundary = legal and (is4 or is6)
        try:
            phase = Phase(phase_str)
        except (ValueError, TypeError):
            phase = Phase.UNKNOWN
        lines.append(BowlingLine(
            innings_id=inn_id,
            over_number=ov,
            delivery_sequence=seq,
            bowling_runs=bowl_runs,
            is_legal_ball=legal,
            is_boundary_conceded=is_boundary,
            is_dot_ball=is_dot,
            bowler_wicket=is_bowler_wkt,
            phase=phase,
            is_super_over=super_ov,
        ))

    stats = calculate_bowling_stats(lines, player_id)
    sample_note = f"Based on {stats.innings_bowled} innings ({stats.overs_display} overs)"

    return BowlingStatsResponse(
        player_id=player_id,
        innings_bowled=stats.innings_bowled,
        legal_balls=stats.legal_balls,
        overs_display=stats.overs_display,
        runs_conceded=stats.runs_conceded,
        wickets=stats.wickets,
        dot_balls=stats.dot_balls,
        economy_rate=stats.economy_rate,
        bowling_average=stats.bowling_average,
        bowling_strike_rate=stats.bowling_strike_rate,
        dot_ball_percentage=stats.dot_ball_percentage,
        boundary_percentage=stats.boundary_percentage,
        sample_note=sample_note,
    )


@router.get("/players/{player_id}/phases", response_model=List[PhaseStatsResponse])
def player_phases(
    player_id: str,
    role: str = Query("batting", pattern="^(batting|bowling)$"),
    format: Optional[str] = Query(None),
    season: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """Phase-wise batting or bowling breakdown."""
    match_ids = _match_filter_conditions(db, format, None, season) if any([format, season]) else None

    if role == "batting":
        stmt = (
            select(
                Delivery.innings_id, Delivery.over_number, Delivery.delivery_sequence,
                Delivery.batter_runs, Delivery.is_legal_ball, Delivery.is_ball_faced_by_batter,
                Delivery.is_boundary_four, Delivery.is_boundary_six, Delivery.phase,
                MatchInnings.is_super_over,
            )
            .join(MatchInnings, Delivery.innings_id == MatchInnings.id)
            .where(Delivery.batter_id == player_id, MatchInnings.is_super_over == False)
        )
        if match_ids is not None:
            stmt = stmt.where(MatchInnings.match_id.in_(match_ids))
        rows = db.execute(stmt).fetchall()

        wkt_stmt = (
            select(Wicket.delivery_id)
            .join(Delivery, Wicket.delivery_id == Delivery.id)
            .join(MatchInnings, Delivery.innings_id == MatchInnings.id)
            .where(
                Wicket.player_out_id == player_id,
                Wicket.is_batter_dismissed == True,
                MatchInnings.is_super_over == False,
            )
        )
        if match_ids is not None:
            wkt_stmt = wkt_stmt.where(MatchInnings.match_id.in_(match_ids))
        dismissed_set = set(row[0] for row in db.execute(wkt_stmt).fetchall())

        delivery_stmt = (
            select(Delivery.id, Delivery.innings_id, Delivery.over_number, Delivery.delivery_sequence)
            .join(MatchInnings, Delivery.innings_id == MatchInnings.id)
            .where(Delivery.batter_id == player_id, MatchInnings.is_super_over == False)
        )
        if match_ids is not None:
            delivery_stmt = delivery_stmt.where(MatchInnings.match_id.in_(match_ids))
        did_map = {(r[1], r[2], r[3]): r[0] for r in db.execute(delivery_stmt).fetchall()}

        lines = []
        for row in rows:
            inn_id, ov, seq, b_runs, legal, bf, is4, is6, phase_str, super_ov = row
            dl_id = did_map.get((inn_id, ov, seq))
            try:
                phase = Phase(phase_str)
            except:
                phase = Phase.UNKNOWN
            lines.append(BattingLine(
                innings_id=inn_id, over_number=ov, delivery_sequence=seq,
                batter_runs=b_runs, is_legal_ball=legal, is_ball_faced=bf,
                is_boundary_four=is4, is_boundary_six=is6, phase=phase,
                was_dismissed=(dl_id in dismissed_set if dl_id else False),
                is_super_over=super_ov,
            ))

        phase_stats = calculate_phase_batting_stats(lines, player_id)
        return [
            PhaseStatsResponse(
                phase=p.value,
                runs=ps.runs,
                balls_faced=ps.balls_faced,
                dismissals=ps.dismissals,
                fours=ps.fours,
                sixes=ps.sixes,
                strike_rate=ps.strike_rate,
                average=ps.average,
                dot_ball_percentage=ps.dot_ball_percentage,
                boundary_percentage=ps.boundary_percentage,
            )
            for p, ps in phase_stats.items()
        ]

    else:  # bowling
        stmt = (
            select(
                Delivery.innings_id, Delivery.over_number, Delivery.delivery_sequence,
                Delivery.bowling_runs, Delivery.is_legal_ball,
                Delivery.is_boundary_four, Delivery.is_boundary_six,
                Delivery.batter_runs, Delivery.phase, MatchInnings.is_super_over,
            )
            .join(MatchInnings, Delivery.innings_id == MatchInnings.id)
            .where(Delivery.bowler_id == player_id, MatchInnings.is_super_over == False)
        )
        if match_ids is not None:
            stmt = stmt.where(MatchInnings.match_id.in_(match_ids))
        rows = db.execute(stmt).fetchall()

        bowler_wkt_stmt = (
            select(Wicket.delivery_id)
            .join(Delivery, Wicket.delivery_id == Delivery.id)
            .join(MatchInnings, Delivery.innings_id == MatchInnings.id)
            .where(
                Delivery.bowler_id == player_id,
                Wicket.is_bowler_wicket == True,
                MatchInnings.is_super_over == False,
            )
        )
        if match_ids is not None:
            bowler_wkt_stmt = bowler_wkt_stmt.where(MatchInnings.match_id.in_(match_ids))
        bowler_wkt_ids = set(row[0] for row in db.execute(bowler_wkt_stmt).fetchall())

        delivery_stmt2 = (
            select(Delivery.id, Delivery.innings_id, Delivery.over_number, Delivery.delivery_sequence)
            .join(MatchInnings, Delivery.innings_id == MatchInnings.id)
            .where(Delivery.bowler_id == player_id, MatchInnings.is_super_over == False)
        )
        if match_ids is not None:
            delivery_stmt2 = delivery_stmt2.where(MatchInnings.match_id.in_(match_ids))
        did_map2 = {
            (r[1], r[2], r[3]): r[0] for r in db.execute(delivery_stmt2).fetchall()
        }

        lines = []
        for row in rows:
            inn_id, ov, seq, bowl_runs, legal, is4, is6, bat_runs, phase_str, super_ov = row
            dl_id = did_map2.get((inn_id, ov, seq))
            try:
                phase = Phase(phase_str)
            except:
                phase = Phase.UNKNOWN
            lines.append(BowlingLine(
                innings_id=inn_id, over_number=ov, delivery_sequence=seq,
                bowling_runs=bowl_runs, is_legal_ball=legal,
                is_boundary_conceded=(legal and (is4 or is6)),
                is_dot_ball=(legal and bat_runs == 0),
                bowler_wicket=(dl_id in bowler_wkt_ids if dl_id else False),
                phase=phase, is_super_over=super_ov,
            ))

        phase_stats = calculate_phase_bowling_stats(lines, player_id)
        return [
            PhaseStatsResponse(
                phase=p.value,
                runs=ps.runs_conceded,
                balls_faced=ps.legal_balls,
                dismissals=ps.wickets,
                fours=ps.boundary_deliveries,
                sixes=0,
                strike_rate=ps.economy_rate,
                average=ps.bowling_average,
                dot_ball_percentage=ps.dot_ball_percentage,
                boundary_percentage=ps.boundary_percentage,
            )
            for p, ps in phase_stats.items()
        ]


class SimilarPlayerResult(BaseModel):
    player_id: str
    player_name: str
    similarity_score: float
    innings: int
    strike_rate: Optional[float]
    batting_average: Optional[float]
    boundary_pct: Optional[float]
    dot_ball_pct: Optional[float]
    explanations: List[str]


class PlayerSimilarityResponse(BaseModel):
    target_player_id: str
    target_player_name: str
    format: str
    model_version: str
    similar_players: List[SimilarPlayerResult]


@router.get("/players/{player_id}/similar", response_model=PlayerSimilarityResponse)
def get_similar_players(
    player_id: str,
    format: str = Query("T20"),
    min_innings: int = Query(5, ge=1),
    limit: int = Query(5, ge=1, le=20),
    db: Session = Depends(get_db),
):
    player = db.get(Player, player_id)
    if not player:
        raise HTTPException(status_code=404, detail="Player not found")

    df = extract_player_feature_matrix(
        db,
        format_filter=format,
        min_innings=min_innings,
        min_balls=30,
    )

    if df.empty or player_id not in df.index:
        raise HTTPException(
            status_code=400,
            detail=f"Player does not meet minimum sample threshold ({min_innings} innings) for similarity analysis."
        )

    engine = PlayerSimilarityEngine()
    engine.fit(df)
    results = engine.find_similar_players(player_id, n_neighbors=limit)

    return PlayerSimilarityResponse(
        target_player_id=player.id,
        target_player_name=player.canonical_name,
        format=format,
        model_version=engine.version,
        similar_players=[SimilarPlayerResult(**r) for r in results],
    )


class SimilarBowlerResult(BaseModel):
    player_id: str
    player_name: str
    similarity_score: float
    innings: int
    matches: int
    wickets: int
    economy: Optional[float]
    bowling_average: Optional[float]
    bowling_strike_rate: Optional[float]
    dot_ball_pct: Optional[float]
    explanations: List[str]
    differences: List[str]


class BowlerSimilarityResponse(BaseModel):
    target_player_id: str
    target_player_name: str
    format: str
    model_version: str
    similar_players: List[SimilarBowlerResult]


@router.get("/players/{player_id}/similar-bowlers", response_model=BowlerSimilarityResponse)
def get_similar_bowlers(
    player_id: str,
    format: str = Query("T20"),
    min_innings: int = Query(5, ge=1),
    min_legal_balls: int = Query(60, ge=1),
    limit: int = Query(10, ge=1, le=10),
    db: Session = Depends(get_db),
):
    """Compare a bowler only with bowlers, using bowling-only, format-scoped features."""
    player = db.get(Player, player_id)
    if not player:
        raise HTTPException(status_code=404, detail="Player not found")
    def build_model():
        all_bowlers = extract_bowling_feature_matrix(db, format, min_innings, min_legal_balls)
        if all_bowlers.empty:
            return all_bowlers, all_bowlers
        # A player with qualifying batting usage is an all-rounder, not a specialist bowler.
        batting = extract_player_feature_matrix(db, format_filter=format, min_innings=8, min_balls=120)
        specialists = all_bowlers.copy()
        if not batting.empty:
            specialists = specialists.loc[~specialists.index.isin(batting.index)]
        return specialists, all_bowlers
    specialists, all_bowlers = get_or_build(("bowler", format, min_innings, min_legal_balls), build_model)
    # This view is bowling-only: allow an all-rounder profile as the query player,
    # while keeping recommendations restricted to specialist bowlers.
    df = specialists.copy()
    if player_id not in df.index and player_id in all_bowlers.index:
        df = pd.concat([df, all_bowlers.loc[[player_id]]])
    if df.empty or player_id not in df.index:
        raise HTTPException(status_code=400, detail="Player does not meet the bowling sample threshold for this format.")
    engine = BowlingSimilarityEngine()
    if not engine.fit(df):
        return BowlerSimilarityResponse(target_player_id=player.id, target_player_name=player.canonical_name,
                                        format=format, model_version=BowlingSimilarityEngine.version, similar_players=[])
    results = engine.find_similar_players(player_id, limit)
    return BowlerSimilarityResponse(target_player_id=player.id, target_player_name=player.canonical_name,
                                    format=format, model_version=engine.version,
                                    similar_players=[SimilarBowlerResult(**r) for r in results])


class SimilarAllRounderResult(BaseModel):
    player_id: str
    player_name: str
    similarity_score: float
    batting_similarity: float
    bowling_similarity: float
    batting_innings: int
    bowling_innings: int
    batting_explanations: List[str]
    bowling_explanations: List[str]
    weighting: Dict[str, float]


class AllRounderSimilarityResponse(BaseModel):
    target_player_id: str
    target_player_name: str
    format: str
    model_version: str
    similar_players: List[SimilarAllRounderResult]


@router.get("/players/{player_id}/similar-all-rounders", response_model=AllRounderSimilarityResponse)
def get_similar_all_rounders(
    player_id: str,
    format: str = Query("T20"),
    min_innings: int = Query(5, ge=1),
    min_legal_balls: int = Query(60, ge=1),
    limit: int = Query(10, ge=1, le=10),
    db: Session = Depends(get_db),
):
    """Require meaningful use in both disciplines and weight them equally."""
    player = db.get(Player, player_id)
    if not player:
        raise HTTPException(status_code=404, detail="Player not found")
    def build_model():
        batting = extract_player_feature_matrix(db, format_filter=format, min_innings=min_innings, min_balls=30)
        bowling = extract_bowling_feature_matrix(db, format_filter=format, min_innings=min_innings,
                                                 min_legal_balls=min_legal_balls)
        model = AllRounderSimilarityEngine()
        return model if not batting.empty and not bowling.empty and model.fit(batting, bowling) else None
    engine = get_or_build(("allrounder", format, min_innings, min_legal_balls), build_model)
    if engine is None or player_id not in engine.batting.index:
        raise HTTPException(status_code=400, detail="Player does not meet the batting and bowling sample thresholds for this format.")
    results = engine.find_similar_players(player_id, limit)
    return AllRounderSimilarityResponse(target_player_id=player.id, target_player_name=player.canonical_name,
                                        format=format, model_version=engine.version,
                                        similar_players=[SimilarAllRounderResult(**r) for r in results])
