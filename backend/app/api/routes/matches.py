"""Match listing and detail endpoints."""
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import select, func, or_
from pydantic import BaseModel
from datetime import date as DateType

from app.db.session import get_db
from app.models.models import Match, Team, Venue, VenueAlias, Tournament, MatchInnings, Delivery, DeliveryExtra, Wicket, Player

router = APIRouter()


class MatchSummary(BaseModel):
    id: str
    source_match_id: str
    competition: Optional[str]
    season: str
    start_date: DateType
    venue: Optional[str]
    team1: Optional[str]
    team2: Optional[str]
    winner: Optional[str]
    result_type: Optional[str]
    result_margin_runs: Optional[int]
    result_margin_wickets: Optional[int]
    match_format: str


class MatchListResponse(BaseModel):
    matches: List[MatchSummary]
    total: int
    page: int
    page_size: int


def _build_match_summary(match: Match, db: Session) -> MatchSummary:
    team1 = db.get(Team, match.team1_id).canonical_name if match.team1_id else None
    team2 = db.get(Team, match.team2_id).canonical_name if match.team2_id else None
    winner = db.get(Team, match.winner_id).canonical_name if match.winner_id else None
    venue = db.get(Venue, match.venue_id).canonical_name if match.venue_id else None
    tournament = db.get(Tournament, match.tournament_id).name if match.tournament_id else None
    return MatchSummary(
        id=match.id,
        source_match_id=match.source_match_id,
        competition=tournament,
        season=match.season,
        start_date=match.start_date,
        venue=venue,
        team1=team1,
        team2=team2,
        winner=winner,
        result_type=match.result_type,
        result_margin_runs=match.result_margin_runs,
        result_margin_wickets=match.result_margin_wickets,
        match_format=match.match_format,
    )


def _build_match_summaries(matches: List[Match], db: Session) -> List[MatchSummary]:
    team_ids = {i for m in matches for i in (m.team1_id, m.team2_id, m.winner_id) if i}
    venue_ids = {m.venue_id for m in matches if m.venue_id}
    tournament_ids = {m.tournament_id for m in matches if m.tournament_id}
    teams = {r.id: r.canonical_name for r in db.execute(select(Team).where(Team.id.in_(team_ids))).scalars()} if team_ids else {}
    venues = {r.id: r.canonical_name for r in db.execute(select(Venue).where(Venue.id.in_(venue_ids))).scalars()} if venue_ids else {}
    tournaments = {r.id: r.name for r in db.execute(select(Tournament).where(Tournament.id.in_(tournament_ids))).scalars()} if tournament_ids else {}
    return [MatchSummary(
        id=m.id, source_match_id=m.source_match_id, competition=tournaments.get(m.tournament_id),
        season=m.season, start_date=m.start_date, venue=venues.get(m.venue_id),
        team1=teams.get(m.team1_id), team2=teams.get(m.team2_id), winner=teams.get(m.winner_id),
        result_type=m.result_type, result_margin_runs=m.result_margin_runs,
        result_margin_wickets=m.result_margin_wickets, match_format=m.match_format,
    ) for m in matches]


@router.get("/matches", response_model=MatchListResponse)
def list_matches(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    format: Optional[str] = Query(None),
    season: Optional[str] = Query(None),
    team: Optional[str] = Query(None),
    search: Optional[str] = Query(None, max_length=100),
    competition: Optional[str] = Query(None, max_length=120),
    tournament: Optional[str] = Query(None, max_length=120),
    year_from: Optional[int] = Query(None, ge=1800, le=2200),
    year_to: Optional[int] = Query(None, ge=1800, le=2200),
    start_date: Optional[DateType] = Query(None),
    end_date: Optional[DateType] = Query(None),
    opponent: Optional[str] = Query(None, max_length=120),
    venue: Optional[str] = Query(None, max_length=160),
    country: Optional[str] = Query(None, max_length=120),
    result: Optional[str] = Query(None, max_length=120),
    db: Session = Depends(get_db),
):
    stmt = select(Match).order_by(Match.start_date.desc())
    if format:
        stmt = stmt.where(Match.match_format == format)
    if season:
        stmt = stmt.where(Match.season == season)
    if team:
        matching_team = select(Team.id).where(Team.name.ilike(f"%{team}%")).subquery()
        stmt = stmt.where(or_(Match.team1_id.in_(select(matching_team.c.id)), Match.team2_id.in_(select(matching_team.c.id))))
    if opponent:
        matching_team = select(Team.id).where(Team.name.ilike(f"%{opponent}%")).subquery()
        stmt = stmt.where(or_(Match.team1_id.in_(select(matching_team.c.id)), Match.team2_id.in_(select(matching_team.c.id))))
    if competition or tournament:
        stmt = stmt.where(Match.tournament_id.in_(select(Tournament.id).where(Tournament.name.ilike(competition or tournament))))
    if year_from: stmt = stmt.where(Match.start_date >= DateType(year_from, 1, 1))
    if year_to: stmt = stmt.where(Match.start_date <= DateType(year_to, 12, 31))
    if start_date: stmt = stmt.where(Match.start_date >= start_date)
    if end_date: stmt = stmt.where(Match.start_date <= end_date)
    if venue:
        venue_ids = select(Venue.id).where(Venue.name.ilike(f"%{venue}%") | Venue.canonical_name.ilike(f"%{venue}%"))
        alias_venue_ids = select(VenueAlias.venue_id).where(VenueAlias.source_name.ilike(f"%{venue}%"))
        stmt = stmt.where(or_(Match.venue_id.in_(venue_ids), Match.venue_id.in_(alias_venue_ids)))
    if country: stmt = stmt.where(Match.venue_id.in_(select(Venue.id).where(Venue.country.ilike(f"%{country}%"))))
    if result:
        result_team_ids = select(Team.id).where(Team.name.ilike(f"%{result}%"))
        stmt = stmt.where(or_(Match.result_type.ilike(f"%{result}%"), Match.winner_id.in_(result_team_ids)))
    if search:
        matching_team_ids = select(Team.id).where(Team.name.ilike(f"%{search}%"))
        stmt = stmt.where(
            (Match.tournament_id.in_(select(Tournament.id).where(Tournament.name.ilike(f"%{search}%")))) |
            (Match.venue_id.in_(select(Venue.id).where(Venue.name.ilike(f"%{search}%") | Venue.canonical_name.ilike(f"%{search}%")))) |
            (Match.venue_id.in_(select(VenueAlias.venue_id).where(VenueAlias.source_name.ilike(f"%{search}%")))) |
            Match.team1_id.in_(matching_team_ids) | Match.team2_id.in_(matching_team_ids) |
            (Match.source_match_id.ilike(f"%{search}%"))
        )

    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar() or 0
    stmt = stmt.offset((page - 1) * page_size).limit(page_size)
    matches = db.execute(stmt).scalars().all()

    return MatchListResponse(
        matches=_build_match_summaries(matches, db),
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/matches/{match_id}", response_model=MatchSummary)
def get_match(match_id: str, db: Session = Depends(get_db)):
    match = db.get(Match, match_id)
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    return _build_match_summary(match, db)


@router.get("/matches/{match_id}/details")
def get_match_details(match_id: str, db: Session = Depends(get_db)):
    """Load a single match's innings and ball-by-ball detail on demand."""
    match = db.get(Match, match_id)
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    innings = db.execute(select(MatchInnings).where(MatchInnings.match_id == match_id).order_by(MatchInnings.innings_number)).scalars().all()
    ids = [inn.id for inn in innings]
    deliveries = db.execute(select(Delivery).where(Delivery.innings_id.in_(ids)).order_by(Delivery.innings_id, Delivery.over_number, Delivery.delivery_sequence)).scalars().all() if ids else []
    player_ids = {p for d in deliveries for p in (d.batter_id, d.bowler_id) if p}
    wicket_rows = db.execute(select(Wicket).where(Wicket.delivery_id.in_([d.id for d in deliveries]))).scalars().all() if deliveries else []
    player_ids.update(w.player_out_id for w in wicket_rows if w.player_out_id)
    player_ids.update(w.fielder_id for w in wicket_rows if w.fielder_id)
    names = {p.id: p.canonical_name for p in db.execute(select(Player).where(Player.id.in_(player_ids))).scalars().all()} if player_ids else {}
    extras = db.execute(select(DeliveryExtra).where(DeliveryExtra.delivery_id.in_([d.id for d in deliveries]))).scalars().all() if deliveries else []
    extras_by_delivery = {}
    for extra in extras: extras_by_delivery.setdefault(extra.delivery_id, []).append({"type": extra.extra_type, "runs": extra.runs})
    wickets_by_delivery = {}
    for wicket in wicket_rows:
        wickets_by_delivery.setdefault(wicket.delivery_id, []).append({
            "player_out": names.get(wicket.player_out_id), "kind": wicket.dismissal_type,
            "fielder": names.get(wicket.fielder_id), "bowler_credited": wicket.is_bowler_wicket,
        })
    batting_team_ids = {inn.batting_team_id for inn in innings if inn.batting_team_id}
    team_names = {t.id: t.canonical_name for t in db.execute(select(Team).where(Team.id.in_(batting_team_ids))).scalars().all()} if batting_team_ids else {}
    by_innings = {i.id: [] for i in innings}
    for d in deliveries:
        by_innings[d.innings_id].append({
            "over": d.over_number + 1, "ball": d.delivery_sequence + 1,
            "batter": names.get(d.batter_id), "bowler": names.get(d.bowler_id),
            "batter_runs": d.batter_runs, "extras": d.extras_runs, "total_runs": d.total_runs,
            "extra_types": extras_by_delivery.get(d.id, []), "wickets": wickets_by_delivery.get(d.id, []),
            "legal": d.is_legal_ball, "phase": d.phase,
        })
    return {"match": _build_match_summary(match, db).model_dump(), "innings": [
        {"innings_number": inn.innings_number, "batting_team_id": inn.batting_team_id,
         "batting_team": team_names.get(inn.batting_team_id),
         "is_super_over": inn.is_super_over, "deliveries": by_innings[inn.id]} for inn in innings
    ]}
