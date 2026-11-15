"""Indexed, match-level team records. No delivery scans are needed for results."""
from datetime import date
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, func, or_, and_
from sqlalchemy.orm import Session, aliased

from app.db.session import get_db
from app.models.models import Team, Match, MatchInnings, Venue
from app.analytics.grounds import FORMAT_BUCKETS

router = APIRouter()


class TeamSummary(BaseModel):
    id: str
    name: str
    canonical_name: str
    matches_played: int


def result_bucket(result_type, winner_id, team_id):
    """Use explicit result type first; an undecided non-NR record is not a loss."""
    value = (result_type or "").strip().casefold()
    if value in {"tie", "tied"}:
        return "ties"
    if value in {"no result", "abandoned", "cancelled", "canceled"}:
        return "no_results"
    if winner_id is None:
        return "unresolved"
    return "wins" if winner_id == team_id else "losses"


def resolve_formats(format_name):
    if not format_name:
        return None
    if format_name in FORMAT_BUCKETS:
        return FORMAT_BUCKETS[format_name]
    return (format_name,)


def validate_date_range(start_date, end_date):
    if start_date and end_date and start_date > end_date:
        raise ValueError("start_date must be on or before end_date")


def validate_gender(gender):
    if gender not in {"all", "male", "female"}:
        raise ValueError("gender must be all, male, or female")


def classify_ground_sides(venue_country, team1_country, team2_country):
    """Use stored country evidence; never infer an away side from an unknown team."""
    def same_country(left, right):
        return bool(left and right and left.strip().casefold() == right.strip().casefold())
    if not venue_country:
        return "unknown", "unknown"
    home1, home2 = same_country(venue_country, team1_country), same_country(venue_country, team2_country)
    if home1 and home2:
        return "home", "home"
    if home1:
        return "home", "away"
    if home2:
        return "away", "home"
    if team1_country and team2_country:
        return "neutral", "neutral"
    return ("neutral" if team1_country else "unknown", "neutral" if team2_country else "unknown")


class TeamStatsResponse(BaseModel):
    team_id: str
    team_name: str
    total_matches: int
    wins: int
    losses: int
    ties: int
    no_results: int
    unresolved: int = 0
    win_percentage: Optional[float]
    loss_percentage: Optional[float] = None
    batting_first_wins: int
    batting_first_matches: int
    batting_first_win_pct: Optional[float]
    chasing_wins: int
    chasing_matches: int
    chasing_win_pct: Optional[float]
    by_country: list = []
    by_ground: list = []
    by_opponent: list = []
    toss_decisions: list = []
    home_away: dict = {}
    home_away_coverage: dict = {}
    filters: dict = {}
    insights: list = []
    team_country: Optional[str] = None
    team_country_source: Optional[str] = None
    team_country_confidence: Optional[str] = None
    recent_matches: list = []


@router.get("/teams", response_model=List[TeamSummary])
def list_teams(db: Session = Depends(get_db)):
    counts = dict(db.execute(
        select(Team.id, func.count(Match.id))
        .join(Match, or_(Match.team1_id == Team.id, Match.team2_id == Team.id))
        .group_by(Team.id)
    ).all())
    teams = db.execute(select(Team).order_by(Team.canonical_name)).scalars().all()
    return [TeamSummary(id=t.id, name=t.name, canonical_name=t.canonical_name,
                        matches_played=int(counts.get(t.id, 0)))
            for t in teams if counts.get(t.id, 0)]


@router.get("/teams/{team_id}", response_model=TeamStatsResponse)
def get_team_stats(
    team_id: str,
    format: Optional[str] = Query(None),
    period: Optional[str] = Query(None),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    country: Optional[str] = Query(None),
    opposition: Optional[str] = Query(None),
    gender: str = Query("all"),
    db: Session = Depends(get_db),
):
    team = db.get(Team, team_id)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    try:
        validate_date_range(start_date, end_date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if period and period not in {"1", "3", "5", "10", "all"}:
        raise HTTPException(status_code=400, detail="period must be 1, 3, 5, 10, or all")
    try:
        validate_gender(gender)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    formats = resolve_formats(format)
    if format and not formats:
        raise HTTPException(status_code=400, detail="format must be ODI, T20, or Test")

    first_innings = (select(MatchInnings.match_id.label("match_id"),
                            MatchInnings.batting_team_id.label("batting_team_id"))
                     .where(MatchInnings.innings_number == 1,
                            MatchInnings.is_super_over.is_(False)).subquery())
    team1 = aliased(Team)
    team2 = aliased(Team)
    stmt = (select(Match.id, Match.start_date, Match.match_format, Match.gender, Match.team1_id, Match.team2_id,
                   Match.winner_id, Match.result_type, Match.toss_winner_id, Match.toss_decision,
                   first_innings.c.batting_team_id, Venue.canonical_name.label("ground"),
                   Venue.country.label("country"), team1.country.label("team1_country"),
                   team2.country.label("team2_country"))
            .outerjoin(first_innings, first_innings.c.match_id == Match.id)
            .outerjoin(Venue, Venue.id == Match.venue_id)
            .outerjoin(team1, team1.id == Match.team1_id)
            .outerjoin(team2, team2.id == Match.team2_id)
            .where(or_(Match.team1_id == team_id, Match.team2_id == team_id)))
    if formats:
        stmt = stmt.where(Match.match_format.in_(formats))
    if gender != "all":
        stmt = stmt.where(func.lower(Match.gender) == gender)
    if period and period != "all" and not (start_date or end_date):
        today = date.today()
        try:
            cutoff = today.replace(year=today.year - int(period))
        except ValueError:  # leap day
            cutoff = today.replace(year=today.year - int(period), day=28)
        stmt = stmt.where(Match.start_date >= cutoff)
    if start_date:
        stmt = stmt.where(Match.start_date >= start_date)
    if end_date:
        stmt = stmt.where(Match.start_date <= end_date)
    if country:
        stmt = stmt.where(Venue.country.ilike(f"%{country}%"))
    if opposition:
        opponent = db.get(Team, opposition)
        if opponent:
            stmt = stmt.where(or_(and_(Match.team1_id == team_id, Match.team2_id == opponent.id),
                                  and_(Match.team2_id == team_id, Match.team1_id == opponent.id)))
        else:
            stmt = stmt.where(False)
    rows = db.execute(stmt.order_by(Match.start_date.desc())).mappings().all()
    involved_team_ids = {r["team1_id"] for r in rows} | {r["team2_id"] for r in rows}
    team_names = {t.id: t.canonical_name for t in db.execute(
        select(Team).where(Team.id.in_(involved_team_ids))).scalars().all()} if involved_team_ids else {}
    counts = {key: 0 for key in ("wins", "losses", "ties", "no_results", "unresolved")}
    first = {"matches": 0, "wins": 0}; chase = {"matches": 0, "wins": 0}
    country_stats, ground_stats, opponent_stats, toss_stats = {}, {}, {}, {}
    home_away = {kind: {"matches": 0, "wins": 0} for kind in ("home", "away", "neutral", "unknown")}
    home_away_coverage = {"ground_country_missing": 0, "team_country_missing": 0}
    for row in rows:
        won = row["winner_id"] == team_id
        bucket = result_bucket(row["result_type"], row["winner_id"], team_id)
        counts[bucket] += 1
        if row["batting_team_id"] == team_id:
            first["matches"] += 1; first["wins"] += int(won)
        elif row["batting_team_id"]:
            chase["matches"] += 1; chase["wins"] += int(won)
        other_id = row["team2_id"] if row["team1_id"] == team_id else row["team1_id"]
        opponent_name = team_names.get(other_id, "Unknown")
        _bump(opponent_stats, opponent_name, bucket, won)
        _bump(country_stats, row["country"] or "Unknown", bucket, won)
        _bump(ground_stats, row["ground"] or "Unknown", bucket, won)
        decision = (row["toss_decision"] or "unknown").casefold()
        key = f"{decision}:{'won toss' if row['toss_winner_id'] == team_id else 'lost toss'}"
        _bump(toss_stats, key, bucket, won)
        side1, side2 = classify_ground_sides(row["country"], row["team1_country"], row["team2_country"])
        home_key = side1 if row["team1_id"] == team_id else side2
        home_away[home_key]["matches"] += 1
        home_away[home_key]["wins"] += int(won)
        home_away_coverage["ground_country_missing"] += int(not row["country"])
        home_away_coverage["team_country_missing"] += int(not row["team1_country"] or not row["team2_country"])

    played = len(rows)
    def pct(n, d): return round(100*n/d, 1) if d else None
    insights = []
    best_ground = _best_win_rate(ground_stats)
    best_country = _best_win_rate(country_stats)
    if best_ground and best_ground[1]["matches"] >= 5:
        insights.append(f"Best ground record: {best_ground[0]} ({best_ground[1]['wins']}/{best_ground[1]['matches']} wins).")
    if best_country and best_country[1]["matches"] >= 5:
        insights.append(f"Strongest venue-country record: {best_country[0]} ({best_country[1]['wins']}/{best_country[1]['matches']} wins).")
    if first["matches"] >= 5 and chase["matches"] >= 5:
        insights.append(f"Batting-first win rate {pct(first['wins'],first['matches'])}% (n={first['matches']}); chasing {pct(chase['wins'],chase['matches'])}% (n={chase['matches']}).")
    decided_rows = [r for r in rows if result_bucket(r["result_type"], r["winner_id"], team_id) in {"wins", "losses"}]
    if len(decided_rows) >= 10:
        recent, previous = decided_rows[:5], decided_rows[5:10]
        recent_rate = sum(result_bucket(r["result_type"], r["winner_id"], team_id) == "wins" for r in recent) / len(recent)
        previous_rate = sum(result_bucket(r["result_type"], r["winner_id"], team_id) == "wins" for r in previous) / len(previous)
        change = (recent_rate - previous_rate) * 100
        if abs(change) >= 20:
            insights.append(f"Recent form is {'improving' if change > 0 else 'declining'} by {abs(change):.0f} percentage points across the latest 5 vs previous 5 decided matches.")
    return TeamStatsResponse(
        team_id=team.id, team_name=team.canonical_name, total_matches=played,
        wins=counts["wins"], losses=counts["losses"], ties=counts["ties"], no_results=counts["no_results"], unresolved=counts["unresolved"],
        win_percentage=pct(counts["wins"], played), loss_percentage=pct(counts["losses"], played),
        batting_first_wins=first["wins"], batting_first_matches=first["matches"], batting_first_win_pct=pct(first["wins"],first["matches"]),
        chasing_wins=chase["wins"], chasing_matches=chase["matches"], chasing_win_pct=pct(chase["wins"],chase["matches"]),
        by_country=_serialize(country_stats), by_ground=_serialize(ground_stats), by_opponent=_serialize(opponent_stats),
        toss_decisions=_serialize(toss_stats), home_away=home_away,
        home_away_coverage=home_away_coverage,
        filters={"format": format or "all", "period": period or "all", "start_date": start_date, "end_date": end_date,
                 "country": country, "opposition": opposition, "gender": gender, "sample_matches": played},
        insights=insights, team_country=team.country, team_country_source=team.country_source,
        team_country_confidence=team.country_confidence,
        recent_matches=[{
            "match_id": r["id"], "date": r["start_date"].isoformat() if r["start_date"] else None,
            "format": r["match_format"], "team1": team_names.get(r["team1_id"]),
            "team2": team_names.get(r["team2_id"]), "winner": team_names.get(r["winner_id"]),
            "result_type": r["result_type"], "venue": r["ground"],
        } for r in rows[:20]])


def _bump(target, name, result, won):
    item = target.setdefault(name, {"matches": 0, "wins": 0, "losses": 0, "ties": 0, "no_results": 0, "unresolved": 0})
    item["matches"] += 1; item[result] += 1


def _serialize(values):
    return [{"name": name, **stats, "win_percentage": round(stats["wins"] * 100 / (stats["wins"] + stats["losses"]), 1)
             if stats["wins"] + stats["losses"] else None} for name, stats in
            sorted(values.items(), key=lambda pair: (-pair[1]["matches"], pair[0]))]


def _best_win_rate(values):
    eligible = [(name, row) for name, row in values.items() if name.casefold() not in {"unknown", "neutral", "neutral/unknown"} and row["wins"] + row["losses"]]
    return max(eligible, key=lambda pair: (pair[1]["wins"] / (pair[1]["wins"] + pair[1]["losses"]), pair[1]["matches"])) if eligible else None
