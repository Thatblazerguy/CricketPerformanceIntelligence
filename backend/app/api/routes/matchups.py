"""
Comprehensive batter-vs-bowler matchup analytics endpoints.

Endpoints:
  GET /matchups/filter-metadata
  GET /matchups/{batter_id}/{bowler_id}/summary
  GET /matchups/{batter_id}/{bowler_id}/dismissals
  GET /matchups/{batter_id}/{bowler_id}/by-match
  GET /matchups/{batter_id}/{bowler_id}/by-over
  GET /matchups/{batter_id}/{bowler_id}/trends
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.models import Player

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Pydantic response models
# ---------------------------------------------------------------------------


class VenueMeta(BaseModel):
    id: str
    name: str
    city: Optional[str]
    country: Optional[str]


class FilterMetadataResponse(BaseModel):
    years: List[int]
    formats: List[str]
    competitions: List[str]
    teams: List[str]
    venues: List[VenueMeta]


class PhaseData(BaseModel):
    phase: str
    balls: int
    runs: int
    fours: int
    sixes: int
    dot_balls: int
    dismissals: int


class MatchupSummaryResponse(BaseModel):
    batter_id: str
    batter_name: str
    bowler_id: str
    bowler_name: str
    total_deliveries: int
    balls_faced: int
    legal_balls: int
    batter_runs: int
    fours: int
    sixes: int
    boundaries: int
    dot_balls: int
    strike_rate: Optional[float]
    dot_ball_pct: Optional[float]
    boundary_pct: Optional[float]
    matches_count: int
    innings_count: int
    dismissals: int
    batting_average: Optional[float]
    sample_warning: Optional[str]
    filters_applied: Dict[str, Any]
    matches_included: int
    phases: List[PhaseData] = []


class DismissalsResponse(BaseModel):
    total_dismissals: int
    bowler_credited: int
    not_bowler_credited: int
    by_type: Dict[str, int]
    bowler_wickets: int


class MatchRecord(BaseModel):
    match_id: str
    source_match_id: str
    date: str
    season: str
    competition: Optional[str]
    venue: Optional[str]
    team1: Optional[str]
    team2: Optional[str]
    batter_team: Optional[str]
    bowler_team: Optional[str]
    innings_number: int
    balls_faced: int
    runs: int
    fours: int
    sixes: int
    dot_balls: int
    strike_rate: Optional[float]
    dismissed: bool
    dismissal_type: Optional[str]
    over_numbers: str


class ByMatchResponse(BaseModel):
    total: int
    page: int
    page_size: int
    matches: List[MatchRecord]


class OverData(BaseModel):
    over_number: int
    display: str
    balls: int
    runs: int
    fours: int
    sixes: int
    dot_balls: int
    dismissals: int
    strike_rate: Optional[float]


class ByOverResponse(BaseModel):
    overs: List[OverData]


class YearTrend(BaseModel):
    year: int
    balls_faced: int
    runs: int
    strike_rate: Optional[float]
    dismissals: int
    matches: int


class InningsTrend(BaseModel):
    innings_number: int
    balls: int
    runs: int
    strike_rate: Optional[float]
    dismissals: int


class TrendsResponse(BaseModel):
    by_year: List[YearTrend]
    by_innings: List[InningsTrend]


# ---------------------------------------------------------------------------
# Shared filter builder helpers
# ---------------------------------------------------------------------------

def _build_delivery_filters(
    params: dict,
    alias: str = "d",
    mi_alias: str = "mi",
    m_alias: str = "m",
    t_alias: str = "t",
    t1_alias: str = "t1",
    t2_alias: str = "t2",
    bt_alias: str = "bt",
    btt_alias: str = "btt",
) -> tuple[str, dict]:
    """Return (extra_where_clauses_str, bind_params) for common filter params."""
    clauses: list[str] = []
    bind: dict = {}

    # Batter / bowler are always required at the caller level
    if params.get("start_year"):
        clauses.append(f"EXTRACT(year FROM {m_alias}.start_date)::int >= :start_year")
        bind["start_year"] = params["start_year"]
    if params.get("end_year"):
        clauses.append(f"EXTRACT(year FROM {m_alias}.start_date)::int <= :end_year")
        bind["end_year"] = params["end_year"]
    if params.get("format"):
        clauses.append(f"{m_alias}.match_format = :format")
        bind["format"] = params["format"]
    if params.get("competition"):
        clauses.append(f"{t_alias}.name ILIKE :competition")
        bind["competition"] = f"%{params['competition']}%"
    if params.get("season"):
        clauses.append(f"{m_alias}.season = :season")
        bind["season"] = params["season"]
    if params.get("batter_team"):
        clauses.append(f"{btt_alias}.name ILIKE :batter_team")
        bind["batter_team"] = f"%{params['batter_team']}%"
    if params.get("bowler_team"):
        # bowling team = the other team
        clauses.append(
            f"({t1_alias}.name ILIKE :bowler_team OR {t2_alias}.name ILIKE :bowler_team)"
        )
        bind["bowler_team"] = f"%{params['bowler_team']}%"
    if params.get("venue_id"):
        clauses.append(f"{m_alias}.venue_id = :venue_id")
        bind["venue_id"] = params["venue_id"]
    if params.get("innings_number") is not None:
        clauses.append(f"{mi_alias}.innings_number = :innings_number")
        bind["innings_number"] = params["innings_number"]
    if params.get("phase"):
        clauses.append(f"{alias}.phase = :phase")
        bind["phase"] = params["phase"]
    if params.get("over_start") is not None:
        clauses.append(f"{alias}.over_number >= :over_start")
        bind["over_start"] = params["over_start"]
    if params.get("over_end") is not None:
        clauses.append(f"{alias}.over_number <= :over_end")
        bind["over_end"] = params["over_end"]

    where_str = ""
    if clauses:
        where_str = "AND " + " AND ".join(clauses)
    return where_str, bind


def _core_joins(exclude_super_overs: bool = True) -> str:
    """The standard JOIN chain from deliveries to teams/tournaments/venues."""
    super_over_clause = "AND mi.is_super_over = FALSE" if exclude_super_overs else ""
    return f"""
        JOIN match_innings mi ON mi.id = d.innings_id {super_over_clause}
        JOIN matches m ON m.id = mi.match_id
        LEFT JOIN tournaments t ON t.id = m.tournament_id
        LEFT JOIN teams t1 ON t1.id = m.team1_id
        LEFT JOIN teams t2 ON t2.id = m.team2_id
        LEFT JOIN teams bt ON bt.id = mi.batting_team_id
        LEFT JOIN teams btt ON btt.id = mi.batting_team_id
    """


def _resolve_players(db: Session, batter_id: str, bowler_id: str):
    batter = db.get(Player, batter_id)
    if not batter:
        raise HTTPException(status_code=404, detail="Batter not found")
    bowler = db.get(Player, bowler_id)
    if not bowler:
        raise HTTPException(status_code=404, detail="Bowler not found")
    return batter, bowler


# ---------------------------------------------------------------------------
# 1. Filter metadata
# ---------------------------------------------------------------------------


@router.get("/matchups/filter-metadata", response_model=FilterMetadataResponse)
def filter_metadata(db: Session = Depends(get_db)):
    """Returns available filter values derived from actual data."""

    years_rows = db.execute(
        text("SELECT DISTINCT EXTRACT(year FROM start_date)::int AS yr FROM matches ORDER BY yr")
    ).fetchall()

    formats_rows = db.execute(
        text("SELECT DISTINCT match_format FROM matches ORDER BY match_format")
    ).fetchall()

    comps_rows = db.execute(
        text("SELECT DISTINCT name FROM tournaments WHERE name IS NOT NULL ORDER BY name")
    ).fetchall()

    teams_rows = db.execute(
        text("SELECT DISTINCT name FROM teams ORDER BY name")
    ).fetchall()

    venues_rows = db.execute(
        text("SELECT id, name, city, country FROM venues ORDER BY name")
    ).fetchall()

    return FilterMetadataResponse(
        years=[r[0] for r in years_rows if r[0] is not None],
        formats=[r[0] for r in formats_rows if r[0]],
        competitions=[r[0] for r in comps_rows if r[0]],
        teams=[r[0] for r in teams_rows if r[0]],
        venues=[
            VenueMeta(id=r[0], name=r[1], city=r[2], country=r[3])
            for r in venues_rows
        ],
    )


# ---------------------------------------------------------------------------
# Common query param helper
# ---------------------------------------------------------------------------

def _common_params(
    start_year: Optional[int] = Query(None),
    end_year: Optional[int] = Query(None),
    format: Optional[str] = Query(None),
    competition: Optional[str] = Query(None),
    season: Optional[str] = Query(None),
    batter_team: Optional[str] = Query(None),
    bowler_team: Optional[str] = Query(None),
    venue_id: Optional[str] = Query(None),
    innings_number: Optional[int] = Query(None),
    phase: Optional[str] = Query(None),
    over_start: Optional[int] = Query(None),
    over_end: Optional[int] = Query(None),
    exclude_super_overs: bool = Query(True),
):
    return {
        "start_year": start_year,
        "end_year": end_year,
        "format": format,
        "competition": competition,
        "season": season,
        "batter_team": batter_team,
        "bowler_team": bowler_team,
        "venue_id": venue_id,
        "innings_number": innings_number,
        "phase": phase,
        "over_start": over_start,
        "over_end": over_end,
        "exclude_super_overs": exclude_super_overs,
    }


# ---------------------------------------------------------------------------
# 2. Summary endpoint
# ---------------------------------------------------------------------------


@router.get("/matchups/{batter_id}/{bowler_id}/summary", response_model=MatchupSummaryResponse)
def matchup_summary(
    batter_id: str,
    bowler_id: str,
    db: Session = Depends(get_db),
    params: dict = Depends(_common_params),
):
    batter, bowler = _resolve_players(db, batter_id, bowler_id)

    extra_where, bind = _build_delivery_filters(params)
    bind["batter_id"] = batter_id
    bind["bowler_id"] = bowler_id

    core = _core_joins(exclude_super_overs=params.get("exclude_super_overs", True))

    sql = text(f"""
        SELECT
            COUNT(*)                                            AS total_deliveries,
            SUM(CASE WHEN d.is_ball_faced_by_batter THEN 1 ELSE 0 END) AS balls_faced,
            SUM(CASE WHEN d.is_legal_ball THEN 1 ELSE 0 END)   AS legal_balls,
            SUM(d.batter_runs)                                  AS batter_runs,
            SUM(CASE WHEN d.is_boundary_four THEN 1 ELSE 0 END) AS fours,
            SUM(CASE WHEN d.is_boundary_six  THEN 1 ELSE 0 END) AS sixes,
            SUM(CASE WHEN d.is_legal_ball AND d.batter_runs = 0 THEN 1 ELSE 0 END) AS dot_balls,
            COUNT(DISTINCT m.id)                                AS matches_count,
            COUNT(DISTINCT mi.id)                               AS innings_count
        FROM deliveries d
        {core}
        WHERE d.batter_id = :batter_id
          AND d.bowler_id = :bowler_id
          {extra_where}
    """)

    row = db.execute(sql, bind).fetchone()
    if not row:
        total_deliveries = balls_faced = legal_balls = batter_runs = fours = sixes = dot_balls = matches_count = innings_count = 0
    else:
        total_deliveries = int(row[0] or 0)
        balls_faced = int(row[1] or 0)
        legal_balls = int(row[2] or 0)
        batter_runs = int(row[3] or 0)
        fours = int(row[4] or 0)
        sixes = int(row[5] or 0)
        dot_balls = int(row[6] or 0)
        matches_count = int(row[7] or 0)
        innings_count = int(row[8] or 0)

    # Dismissals (bowler credited only)
    dismiss_sql = text(f"""
        SELECT COUNT(*)
        FROM wickets w
        JOIN deliveries d ON d.id = w.delivery_id
        {core}
        WHERE d.batter_id = :batter_id
          AND d.bowler_id = :bowler_id
          AND w.player_out_id = :batter_id
          AND w.is_bowler_wicket = TRUE
          {extra_where}
    """)
    dismiss_row = db.execute(dismiss_sql, bind).fetchone()
    dismissals = int((dismiss_row[0] if dismiss_row else 0) or 0)

    # Phase ranges are comparable only within one limited-overs format.
    phases_out = []
    if params.get("format") in ("T20", "T20I", "ODI", "ODM"):
      phase_sql = text(f"""
        SELECT
            d.phase,
            SUM(CASE WHEN d.is_ball_faced_by_batter THEN 1 ELSE 0 END) AS balls,
            SUM(d.batter_runs) AS runs,
            SUM(CASE WHEN d.is_boundary_four THEN 1 ELSE 0 END) AS fours,
            SUM(CASE WHEN d.is_boundary_six THEN 1 ELSE 0 END) AS sixes,
            SUM(CASE WHEN d.is_legal_ball AND d.batter_runs = 0 THEN 1 ELSE 0 END) AS dot_balls
        FROM deliveries d
        {core}
        WHERE d.batter_id = :batter_id
          AND d.bowler_id = :bowler_id
          {extra_where}
        GROUP BY d.phase
      """)
      phase_rows = {r[0]: r for r in db.execute(phase_sql, bind).fetchall()}

      phase_dismiss_sql = text(f"""
        SELECT
            d.phase,
            COUNT(*)
        FROM wickets w
        JOIN deliveries d ON d.id = w.delivery_id
        {core}
        WHERE d.batter_id = :batter_id
          AND d.bowler_id = :bowler_id
          AND w.player_out_id = :batter_id
          AND w.is_bowler_wicket = TRUE
          {extra_where}
        GROUP BY d.phase
      """)
      phase_dismiss_rows = dict(db.execute(phase_dismiss_sql, bind).fetchall())

      for ph_name in ["powerplay", "middle", "death"]:
          p_row = phase_rows.get(ph_name)
          if p_row:
              phases_out.append(PhaseData(
                  phase=ph_name, balls=int(p_row[1] or 0), runs=int(p_row[2] or 0),
                  fours=int(p_row[3] or 0), sixes=int(p_row[4] or 0),
                  dot_balls=int(p_row[5] or 0), dismissals=int(phase_dismiss_rows.get(ph_name, 0)),
              ))

    boundaries = fours + sixes
    strike_rate = round((batter_runs / balls_faced) * 100, 2) if balls_faced > 0 else None
    dot_ball_pct = round((dot_balls / balls_faced) * 100, 1) if balls_faced > 0 else None
    boundary_pct = round((boundaries / balls_faced) * 100, 1) if balls_faced > 0 else None
    batting_average = round(batter_runs / dismissals, 2) if dismissals > 0 else None
    sample_warning = (
        f"Small sample ({balls_faced} balls faced). Results may not be statistically meaningful."
        if balls_faced < 12 else None
    )

    # Clean up filters_applied (remove None / default values for readability)
    filters_applied = {k: v for k, v in params.items() if v is not None and v is not True}

    return MatchupSummaryResponse(
        batter_id=batter_id,
        batter_name=batter.canonical_name,
        bowler_id=bowler_id,
        bowler_name=bowler.canonical_name,
        total_deliveries=total_deliveries,
        balls_faced=balls_faced,
        legal_balls=legal_balls,
        batter_runs=batter_runs,
        fours=fours,
        sixes=sixes,
        boundaries=boundaries,
        dot_balls=dot_balls,
        strike_rate=strike_rate,
        dot_ball_pct=dot_ball_pct,
        boundary_pct=boundary_pct,
        matches_count=matches_count,
        innings_count=innings_count,
        dismissals=dismissals,
        batting_average=batting_average,
        sample_warning=sample_warning,
        filters_applied=filters_applied,
        matches_included=matches_count,
        phases=phases_out,
    )


# ---------------------------------------------------------------------------
# 3. Dismissals endpoint
# ---------------------------------------------------------------------------


@router.get("/matchups/{batter_id}/{bowler_id}/dismissals", response_model=DismissalsResponse)
def matchup_dismissals(
    batter_id: str,
    bowler_id: str,
    db: Session = Depends(get_db),
    params: dict = Depends(_common_params),
):
    _resolve_players(db, batter_id, bowler_id)

    extra_where, bind = _build_delivery_filters(params)
    bind["batter_id"] = batter_id
    bind["bowler_id"] = bowler_id

    core = _core_joins(exclude_super_overs=params.get("exclude_super_overs", True))

    sql = text(f"""
        SELECT
            w.dismissal_type,
            w.is_bowler_wicket
        FROM wickets w
        JOIN deliveries d ON d.id = w.delivery_id
        {core}
        WHERE d.batter_id = :batter_id
          AND d.bowler_id = :bowler_id
          AND w.player_out_id = :batter_id
          {extra_where}
    """)
    rows = db.execute(sql, bind).fetchall()

    by_type: dict[str, int] = {}
    bowler_credited = 0
    not_bowler_credited = 0
    for dismissal_type, is_bw in rows:
        by_type[dismissal_type] = by_type.get(dismissal_type, 0) + 1
        if is_bw:
            bowler_credited += 1
        else:
            not_bowler_credited += 1

    return DismissalsResponse(
        total_dismissals=len(rows),
        bowler_credited=bowler_credited,
        not_bowler_credited=not_bowler_credited,
        by_type=by_type,
        bowler_wickets=bowler_credited,
    )


# ---------------------------------------------------------------------------
# 4. By-match endpoint
# ---------------------------------------------------------------------------

VALID_SORT_COLS = {"date": "m.start_date", "runs": "runs", "strike_rate": "strike_rate", "balls": "balls_faced"}


@router.get("/matchups/{batter_id}/{bowler_id}/by-match", response_model=ByMatchResponse)
def matchup_by_match(
    batter_id: str,
    bowler_id: str,
    db: Session = Depends(get_db),
    params: dict = Depends(_common_params),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    sort_by: str = Query("date"),
    sort_dir: str = Query("desc"),
):
    _resolve_players(db, batter_id, bowler_id)

    extra_where, bind = _build_delivery_filters(params)
    bind["batter_id"] = batter_id
    bind["bowler_id"] = bowler_id

    core = _core_joins(exclude_super_overs=params.get("exclude_super_overs", True))

    sort_col = VALID_SORT_COLS.get(sort_by, "m.start_date")
    sort_direction = "DESC" if sort_dir.lower() == "desc" else "ASC"

    # We also need bowling team: the team that is NOT the batting team
    sql = text(f"""
        SELECT
            m.id                                                    AS match_id,
            m.source_match_id,
            m.start_date::text                                      AS date,
            m.season,
            t.name                                                  AS competition,
            v.name                                                  AS venue,
            t1.name                                                 AS team1,
            t2.name                                                 AS team2,
            bt.name                                                 AS batter_team,
            CASE WHEN bt.id = m.team1_id THEN t2.name ELSE t1.name END AS bowler_team,
            mi.innings_number,
            SUM(CASE WHEN d.is_ball_faced_by_batter THEN 1 ELSE 0 END)  AS balls_faced,
            SUM(d.batter_runs)                                      AS runs,
            SUM(CASE WHEN d.is_boundary_four THEN 1 ELSE 0 END)    AS fours,
            SUM(CASE WHEN d.is_boundary_six  THEN 1 ELSE 0 END)    AS sixes,
            SUM(CASE WHEN d.is_legal_ball AND d.batter_runs = 0 THEN 1 ELSE 0 END) AS dot_balls,
            CASE WHEN SUM(CASE WHEN d.is_ball_faced_by_batter THEN 1 ELSE 0 END) > 0
                 THEN ROUND(SUM(d.batter_runs)::numeric /
                      SUM(CASE WHEN d.is_ball_faced_by_batter THEN 1 ELSE 0 END) * 100, 2)
                 ELSE NULL END                                      AS strike_rate,
            MAX(CASE WHEN w.is_bowler_wicket THEN w.dismissal_type ELSE NULL END) AS dismissal_type,
            string_agg(DISTINCT d.over_number::text, ',' ORDER BY d.over_number::text) AS over_numbers
        FROM deliveries d
        {core}
        LEFT JOIN venues v ON v.id = m.venue_id
        LEFT JOIN wickets w
            ON w.delivery_id = d.id
            AND w.player_out_id = :batter_id
        WHERE d.batter_id = :batter_id
          AND d.bowler_id = :bowler_id
          {extra_where}
        GROUP BY m.id, m.source_match_id, m.start_date, m.season, t.name, v.name,
                 t1.name, t2.name, bt.name, bt.id, m.team1_id, t2.name, mi.id, mi.innings_number
        ORDER BY {sort_col} {sort_direction}
    """)

    all_rows = db.execute(sql, bind).fetchall()
    total = len(all_rows)
    offset = (page - 1) * page_size
    page_rows = all_rows[offset : offset + page_size]

    matches_out = []
    for r in page_rows:
        balls_faced = int(r[11] or 0)
        dismissed = r[17] is not None
        matches_out.append(
            MatchRecord(
                match_id=r[0],
                source_match_id=r[1],
                date=r[2],
                season=r[3] or "",
                competition=r[4],
                venue=r[5],
                team1=r[6],
                team2=r[7],
                batter_team=r[8],
                bowler_team=r[9],
                innings_number=r[10],
                balls_faced=balls_faced,
                runs=int(r[12] or 0),
                fours=int(r[13] or 0),
                sixes=int(r[14] or 0),
                dot_balls=int(r[15] or 0),
                strike_rate=float(r[16]) if r[16] is not None else None,
                dismissed=dismissed,
                dismissal_type=r[17],
                over_numbers=r[18] or "",
            )
        )

    return ByMatchResponse(total=total, page=page, page_size=page_size, matches=matches_out)


# ---------------------------------------------------------------------------
# 5. By-over endpoint
# ---------------------------------------------------------------------------


@router.get("/matchups/{batter_id}/{bowler_id}/by-over", response_model=ByOverResponse)
def matchup_by_over(
    batter_id: str,
    bowler_id: str,
    db: Session = Depends(get_db),
    params: dict = Depends(_common_params),
):
    _resolve_players(db, batter_id, bowler_id)

    extra_where, bind = _build_delivery_filters(params)
    bind["batter_id"] = batter_id
    bind["bowler_id"] = bowler_id

    core = _core_joins(exclude_super_overs=params.get("exclude_super_overs", True))

    sql = text(f"""
        SELECT
            d.over_number,
            SUM(CASE WHEN d.is_ball_faced_by_batter THEN 1 ELSE 0 END)  AS balls,
            SUM(d.batter_runs)                                      AS runs,
            SUM(CASE WHEN d.is_boundary_four THEN 1 ELSE 0 END)    AS fours,
            SUM(CASE WHEN d.is_boundary_six  THEN 1 ELSE 0 END)    AS sixes,
            SUM(CASE WHEN d.is_legal_ball AND d.batter_runs = 0 THEN 1 ELSE 0 END) AS dot_balls,
            SUM(CASE WHEN w.is_bowler_wicket THEN 1 ELSE 0 END)    AS dismissals
        FROM deliveries d
        {core}
        LEFT JOIN wickets w
            ON w.delivery_id = d.id
            AND w.player_out_id = :batter_id
            AND w.is_bowler_wicket = TRUE
        WHERE d.batter_id = :batter_id
          AND d.bowler_id = :bowler_id
          {extra_where}
        GROUP BY d.over_number
        ORDER BY d.over_number
    """)

    rows = db.execute(sql, bind).fetchall()

    overs_out = []
    for r in rows:
        over_number = int(r[0])
        balls = int(r[1] or 0)
        runs = int(r[2] or 0)
        fours = int(r[3] or 0)
        sixes = int(r[4] or 0)
        dot_balls = int(r[5] or 0)
        dismissals = int(r[6] or 0)
        sr = round((runs / balls) * 100, 2) if balls > 0 else None
        overs_out.append(
            OverData(
                over_number=over_number,
                display=f"Over {over_number + 1}",
                balls=balls,
                runs=runs,
                fours=fours,
                sixes=sixes,
                dot_balls=dot_balls,
                dismissals=dismissals,
                strike_rate=sr,
            )
        )

    return ByOverResponse(overs=overs_out)


# ---------------------------------------------------------------------------
# 6. Trends endpoint
# ---------------------------------------------------------------------------


@router.get("/matchups/{batter_id}/{bowler_id}/trends", response_model=TrendsResponse)
def matchup_trends(
    batter_id: str,
    bowler_id: str,
    db: Session = Depends(get_db),
    params: dict = Depends(_common_params),
):
    _resolve_players(db, batter_id, bowler_id)

    extra_where, bind = _build_delivery_filters(params)
    bind["batter_id"] = batter_id
    bind["bowler_id"] = bowler_id

    core = _core_joins(exclude_super_overs=params.get("exclude_super_overs", True))

    # Year-wise
    year_sql = text(f"""
        SELECT
            EXTRACT(year FROM m.start_date)::int                   AS yr,
            SUM(CASE WHEN d.is_ball_faced_by_batter THEN 1 ELSE 0 END) AS balls_faced,
            SUM(d.batter_runs)                                     AS runs,
            SUM(CASE WHEN w.is_bowler_wicket THEN 1 ELSE 0 END)   AS dismissals,
            COUNT(DISTINCT m.id)                                   AS matches
        FROM deliveries d
        {core}
        LEFT JOIN wickets w
            ON w.delivery_id = d.id
            AND w.player_out_id = :batter_id
            AND w.is_bowler_wicket = TRUE
        WHERE d.batter_id = :batter_id
          AND d.bowler_id = :bowler_id
          {extra_where}
        GROUP BY yr
        ORDER BY yr
    """)

    year_rows = db.execute(year_sql, bind).fetchall()
    by_year = []
    for r in year_rows:
        balls = int(r[1] or 0)
        runs = int(r[2] or 0)
        sr = round((runs / balls) * 100, 2) if balls > 0 else None
        by_year.append(
            YearTrend(
                year=r[0],
                balls_faced=balls,
                runs=runs,
                strike_rate=sr,
                dismissals=int(r[3] or 0),
                matches=int(r[4] or 0),
            )
        )

    # Innings-wise
    innings_sql = text(f"""
        SELECT
            mi.innings_number,
            SUM(CASE WHEN d.is_ball_faced_by_batter THEN 1 ELSE 0 END) AS balls,
            SUM(d.batter_runs)                                     AS runs,
            SUM(CASE WHEN w.is_bowler_wicket THEN 1 ELSE 0 END)   AS dismissals
        FROM deliveries d
        {core}
        LEFT JOIN wickets w
            ON w.delivery_id = d.id
            AND w.player_out_id = :batter_id
            AND w.is_bowler_wicket = TRUE
        WHERE d.batter_id = :batter_id
          AND d.bowler_id = :bowler_id
          {extra_where}
        GROUP BY mi.innings_number
        ORDER BY mi.innings_number
    """)

    innings_rows = db.execute(innings_sql, bind).fetchall()
    by_innings = []
    for r in innings_rows:
        balls = int(r[1] or 0)
        runs = int(r[2] or 0)
        sr = round((runs / balls) * 100, 2) if balls > 0 else None
        by_innings.append(
            InningsTrend(
                innings_number=r[0],
                balls=balls,
                runs=runs,
                strike_rate=sr,
                dismissals=int(r[3] or 0),
            )
        )

    return TrendsResponse(by_year=by_year, by_innings=by_innings)
