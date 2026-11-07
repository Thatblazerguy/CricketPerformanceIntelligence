"""Format-scoped, role-specific scouting over delivery-level CPI data."""
from datetime import date
from math import ceil
from statistics import mean, pstdev
from typing import Dict, List, Optional, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.analytics.scouting import SCOUTING_PRESETS, score_cohort
from app.db.session import get_db
from app.ml.similarity.cache import get_or_build
from app.models.models import PlayerAttribute

router = APIRouter()
FORMATS = {"Test", "ODI", "T20I", "T20", "MDM", "ODM"}
ROLE_LABELS = {"BATTERS": "Specialist Batter", "BOWLERS": "Specialist Bowler", "ALL_ROUNDERS": "All-Rounder"}


class ScoutingRequest(BaseModel):
    format: str = "T20"
    gender: Literal["male", "female", "all"] = "male"
    category: Literal["BATTERS", "BOWLERS", "ALL_ROUNDERS"] = "BATTERS"
    preset: Optional[str] = None
    competition: Optional[str] = None
    nationality: Optional[str] = None
    seasons: Optional[List[str]] = None
    start_year: Optional[int] = None
    end_year: Optional[int] = None
    team_id: Optional[str] = None
    role: Optional[str] = None
    min_age: Optional[int] = None
    max_age: Optional[int] = None
    batting_style: Optional[str] = None
    bowling_style: Optional[str] = None
    pace_spin: Optional[Literal["pace", "spin"]] = None
    minimum_matches: int = 5
    minimum_innings: int = 5
    minimum_balls_faced: int = 60
    minimum_legal_balls: int = 60
    metric_min: Dict[str, float] = Field(default_factory=dict)
    metric_max: Dict[str, float] = Field(default_factory=dict)
    weights: Optional[Dict[str, float]] = None
    # Kept for clients of the previous batter-only API.
    priorities: Optional[Dict[str, float]] = None
    page: int = 1
    page_size: int = 20
    sort_by: str = "score"
    sort_desc: bool = True

    @model_validator(mode="after")
    def validate_filters(self):
        if self.format not in FORMATS:
            raise ValueError("Unsupported format")
        if self.start_year and self.end_year and self.start_year > self.end_year:
            raise ValueError("From year must be less than or equal to To year")
        if self.min_age is not None and self.max_age is not None and self.min_age > self.max_age:
            raise ValueError("Minimum age must be less than or equal to maximum age")
        if min(self.minimum_matches, self.minimum_innings, self.minimum_balls_faced, self.minimum_legal_balls, self.page, self.page_size) < 1:
            raise ValueError("Sample thresholds, page, and page size must be at least 1")
        if self.page_size > 100:
            raise ValueError("page_size may not exceed 100")
        return self


class ScoutingCandidate(BaseModel):
    rank: int
    player_id: str
    player_name: str
    role: str
    nationality: Optional[str] = None
    batting_style: Optional[str] = None
    bowling_style: Optional[str] = None
    recent_match_runs: List[dict] = Field(default_factory=list)
    matches: int
    innings: int
    bowling_innings: int = 0
    runs: Optional[int] = None
    wickets: Optional[int] = None
    balls_faced: int = 0
    legal_balls: int = 0
    overall_score: float
    suitability_score: float
    batting_score: Optional[float] = None
    bowling_score: Optional[float] = None
    metric_scores: Dict[str, Optional[float]] = Field(default_factory=dict)
    stats: Dict[str, Optional[float]] = Field(default_factory=dict)
    confidence: str
    strengths: List[str]
    limitations: List[str]
    explanation: str
    # Backward-compatible batter fields.
    batting_average: Optional[float] = None
    strike_rate: Optional[float] = None
    middle_over_strike_rate: Optional[float] = None
    death_over_strike_rate: Optional[float] = None


class ScoutingResponse(BaseModel):
    candidates: List[ScoutingCandidate]
    total_eligible: int
    page: int
    page_size: int
    total_pages: int
    filters_applied: dict
    score_explanation: str
    visualization: dict = Field(default_factory=dict)


@router.get("/scouting/options")
def scouting_options(db: Session = Depends(get_db)):
    from app.analytics.scouting import SCOUTING_PRESETS
    rows = db.execute(text("""
      SELECT attribute_type, attribute_value FROM player_attributes
      WHERE attribute_type IN ('batting_style','bowling_style','nationality')
      GROUP BY attribute_type, attribute_value ORDER BY attribute_type, attribute_value
    """)).mappings().all()
    batting, bowling, nationality = [], [], []
    for row in rows:
        target = batting if row["attribute_type"] == "batting_style" else bowling if row["attribute_type"] == "bowling_style" else nationality
        if row["attribute_value"] and row["attribute_value"].casefold() != "unknown":
            target.append(row["attribute_value"])
    seasons = [row[0] for row in db.execute(text("SELECT DISTINCT season FROM matches WHERE season IS NOT NULL ORDER BY season DESC")).all()]
    competitions = [row[0] for row in db.execute(text("SELECT DISTINCT name FROM tournaments WHERE name IS NOT NULL ORDER BY name")).all()]
    teams = [dict(id=row[0], name=row[1]) for row in db.execute(text("SELECT id,name FROM teams ORDER BY name")).all()]
    return {"formats": ["Test", "ODI", "T20I", "T20", "MDM", "ODM"], "presets": SCOUTING_PRESETS,
            "batting_styles": batting, "bowling_styles": bowling, "seasons": seasons,
            "competitions": competitions, "nationalities": nationality, "teams": teams}


def _filters(request: ScoutingRequest, side: str) -> tuple[str, dict]:
    clauses = ["m.match_format = :format", "mi.is_super_over = FALSE"]
    params = {"format": request.format}
    if request.gender != "all":
        clauses.append("LOWER(m.gender) = :gender")
        params["gender"] = request.gender
    if request.start_year:
        clauses.append("m.start_date >= :start_date")
        params["start_date"] = date(request.start_year, 1, 1)
    if request.end_year:
        clauses.append("m.start_date <= :end_date")
        params["end_date"] = date(request.end_year, 12, 31)
    if request.competition:
        clauses.append("EXISTS (SELECT 1 FROM tournaments tr WHERE tr.id = m.tournament_id AND tr.name ILIKE :competition)")
        params["competition"] = "%" + request.competition + "%"
    if request.seasons:
        clauses.append("m.season = ANY(:seasons)")
        params["seasons"] = request.seasons
    if request.team_id:
        clauses.extend(["(m.team1_id = :team_id OR m.team2_id = :team_id)"])
        clauses.append("mi.batting_team_id = :team_id" if side == "batting" else "mi.batting_team_id <> :team_id")
        params["team_id"] = request.team_id
    return " AND ".join(clauses), params


def _candidate_rows(db: Session, request: ScoutingRequest) -> List[dict]:
    """Build filtered player aggregates in SQL; cache by data-affecting filters."""
    key = ("scouting-cohort-v3", request.format, request.gender, request.category, request.competition, request.nationality,
           tuple(request.seasons or ()), request.start_year, request.end_year, request.team_id,
           request.minimum_matches, request.minimum_innings, request.minimum_balls_faced,
           request.minimum_legal_balls, request.min_age, request.max_age,
           request.batting_style, request.bowling_style, request.pace_spin)

    def build():
        sides = ["batting", "bowling"] if request.category == "ALL_ROUNDERS" else ["batting" if request.category == "BATTERS" else "bowling"]
        side_rows = {}
        for side in sides:
            filter_sql, params = _filters(request, side)
            player_col = "d.batter_id" if side == "batting" else "d.bowler_id"
            aggregate_sql = f"""
              SELECT {player_col} AS player_id,
                     COUNT(DISTINCT m.id) AS matches,
                     COUNT(DISTINCT mi.id) AS innings,
                     SUM(CASE WHEN d.is_legal_ball THEN 1 ELSE 0 END) AS legal_balls,
                     SUM(CASE WHEN d.is_ball_faced_by_batter THEN 1 ELSE 0 END) AS balls_faced,
                     SUM(d.batter_runs) AS runs,
                     SUM(d.bowling_runs) AS runs_conceded,
                     SUM(CASE WHEN d.is_legal_ball AND d.batter_runs = 0 THEN 1 ELSE 0 END) AS dots,
                     SUM(CASE WHEN d.is_legal_ball AND (d.is_boundary_four OR d.is_boundary_six) THEN 1 ELSE 0 END) AS boundaries,
                     SUM(CASE WHEN d.phase = 'powerplay' THEN d.batter_runs ELSE 0 END) AS pp_runs,
                     SUM(CASE WHEN d.phase = 'powerplay' AND d.is_ball_faced_by_batter THEN 1 ELSE 0 END) AS pp_balls,
                     SUM(CASE WHEN d.phase = 'middle' THEN d.batter_runs ELSE 0 END) AS mid_runs,
                     SUM(CASE WHEN d.phase = 'middle' AND d.is_ball_faced_by_batter THEN 1 ELSE 0 END) AS mid_balls,
                     SUM(CASE WHEN d.phase = 'death' THEN d.batter_runs ELSE 0 END) AS death_runs,
                     SUM(CASE WHEN d.phase = 'death' AND d.is_ball_faced_by_batter THEN 1 ELSE 0 END) AS death_balls,
                     SUM(CASE WHEN d.phase = 'powerplay' AND d.is_legal_ball THEN 1 ELSE 0 END) AS pp_legal,
                     SUM(CASE WHEN d.phase = 'middle' AND d.is_legal_ball THEN 1 ELSE 0 END) AS mid_legal,
                     SUM(CASE WHEN d.phase = 'death' AND d.is_legal_ball THEN 1 ELSE 0 END) AS death_legal,
                     SUM(CASE WHEN d.phase = 'powerplay' THEN d.bowling_runs ELSE 0 END) AS pp_conceded,
                     SUM(CASE WHEN d.phase = 'middle' THEN d.bowling_runs ELSE 0 END) AS mid_conceded,
                     SUM(CASE WHEN d.phase = 'death' THEN d.bowling_runs ELSE 0 END) AS death_conceded,
                     SUM(CASE WHEN d.phase = 'powerplay' AND d.is_legal_ball AND d.batter_runs = 0 THEN 1 ELSE 0 END) AS pp_dots,
                     SUM(CASE WHEN d.phase = 'middle' AND d.is_legal_ball AND d.batter_runs = 0 THEN 1 ELSE 0 END) AS mid_dots,
                     SUM(CASE WHEN d.phase = 'death' AND d.is_legal_ball AND d.batter_runs = 0 THEN 1 ELSE 0 END) AS death_dots,
                     SUM(CASE WHEN d.phase = 'death' AND d.is_legal_ball AND (d.is_boundary_four OR d.is_boundary_six) THEN 1 ELSE 0 END) AS death_boundaries
              FROM deliveries d
              JOIN match_innings mi ON mi.id = d.innings_id
              JOIN matches m ON m.id = mi.match_id
              WHERE {player_col} IS NOT NULL AND {filter_sql}
              GROUP BY 1
            """
            base = {r["player_id"]: dict(r) for r in db.execute(text(aggregate_sql), params).mappings()}
            if not base:
                side_rows[side] = {}
                continue
            ids = list(base)
            if side == "batting":
                dismissals = db.execute(text(f"""
                  SELECT d.batter_id player_id, COUNT(w.id) dismissals
                  FROM wickets w JOIN deliveries d ON d.id = w.delivery_id
                  JOIN match_innings mi ON mi.id = d.innings_id JOIN matches m ON m.id = mi.match_id
                  WHERE d.batter_id = ANY(:ids) AND w.is_batter_dismissed = TRUE AND {_filters(request, 'batting')[0]}
                  GROUP BY d.batter_id
                """), {**params, "ids": ids}).mappings().all()
                dismissal_map = {r["player_id"]: int(r["dismissals"]) for r in dismissals}
                styles = db.execute(text(f"""
                  SELECT d.batter_id player_id,
                         CASE WHEN LOWER(pa.attribute_value) LIKE '%spin%' OR LOWER(pa.attribute_value) LIKE '%break%' OR LOWER(pa.attribute_value) LIKE '%orthodox%' THEN 'spin'
                              WHEN LOWER(pa.attribute_value) LIKE '%fast%' OR LOWER(pa.attribute_value) LIKE '%pace%' OR LOWER(pa.attribute_value) LIKE '%medium%' THEN 'pace' END style,
                         SUM(d.batter_runs) runs, COUNT(*) FILTER (WHERE d.is_ball_faced_by_batter) balls
                  FROM deliveries d JOIN match_innings mi ON mi.id=d.innings_id JOIN matches m ON m.id=mi.match_id
                  JOIN (SELECT DISTINCT ON (player_id) player_id, attribute_value FROM player_attributes
                        WHERE attribute_type='bowling_style' ORDER BY player_id,
                        CASE confidence WHEN 'high' THEN 3 WHEN 'medium' THEN 2 WHEN 'low' THEN 1 ELSE 0 END DESC, updated_at DESC) pa
                    ON pa.player_id=d.bowler_id
                  WHERE d.batter_id=ANY(:ids) AND {_filters(request, 'batting')[0]} GROUP BY 1,2
                """), {**params, "ids": ids}).mappings().all()
                for row in styles:
                    if row["style"]:
                        base[row["player_id"]][row["style"] + "_runs"] = int(row["runs"] or 0)
                        base[row["player_id"]][row["style"] + "_balls"] = int(row["balls"] or 0)
                for pid, record in base.items():
                    record["dismissals"] = dismissal_map.get(pid, 0)
            else:
                wicket_rows = db.execute(text(f"""
                  SELECT d.bowler_id player_id, COUNT(w.id) wickets,
                         COUNT(w.id) FILTER (WHERE d.phase='powerplay') pp_wickets,
                         COUNT(w.id) FILTER (WHERE d.phase='middle') mid_wickets,
                         COUNT(w.id) FILTER (WHERE d.phase='death') death_wickets
                  FROM wickets w JOIN deliveries d ON d.id=w.delivery_id
                  JOIN match_innings mi ON mi.id=d.innings_id JOIN matches m ON m.id=mi.match_id
                  WHERE d.bowler_id=ANY(:ids) AND w.is_bowler_wicket=TRUE AND {_filters(request, 'bowling')[0]}
                  GROUP BY d.bowler_id
                """), {**params, "ids": ids}).mappings().all()
                wicket_map = {r["player_id"]: dict(r) for r in wicket_rows}
                for pid, record in base.items():
                    record.update(wicket_map.get(pid, {"wickets": 0, "pp_wickets": 0, "mid_wickets": 0, "death_wickets": 0}))
            side_rows[side] = base

        all_player_ids = list(set().union(*(set(rows) for rows in side_rows.values())))
        attributes = db.execute(text("""
          SELECT player_id, attribute_type, attribute_value
          FROM player_attributes WHERE player_id=ANY(:ids)
            AND attribute_type IN ('date_of_birth','batting_style','bowling_style','primary_role','nationality')
          ORDER BY player_id, attribute_type,
                   CASE confidence WHEN 'high' THEN 3 WHEN 'medium' THEN 2 WHEN 'low' THEN 1 ELSE 0 END DESC,
                   updated_at DESC
        """), {"ids": all_player_ids}).mappings().all() if all_player_ids else []
        attr_map = {}
        for row in attributes:
            attr_map.setdefault(row["player_id"], {}).setdefault(row["attribute_type"], row["attribute_value"])

        # Match-level records provide consistency and last-five-match form without
        # transferring delivery rows into Python.
        match_stats = {}
        for side in sides:
            ids = list(side_rows[side])
            if not ids:
                continue
            column = "d.batter_id" if side == "batting" else "d.bowler_id"
            metric = "SUM(d.batter_runs)" if side == "batting" else "SUM(CASE WHEN w.id IS NOT NULL THEN 1 ELSE 0 END)"
            join_wickets = "LEFT JOIN wickets w ON w.delivery_id=d.id AND w.is_bowler_wicket=TRUE" if side == "bowling" else ""
            rows = db.execute(text(f"""
              SELECT {column} player_id, m.id match_id, m.start_date, {metric} metric
              FROM deliveries d JOIN match_innings mi ON mi.id=d.innings_id JOIN matches m ON m.id=mi.match_id
              {join_wickets}
              WHERE {column}=ANY(:ids) AND {_filters(request, side)[0]}
              GROUP BY {column},m.id,m.start_date ORDER BY m.start_date
            """), {**_filters(request, side)[1], "ids": ids}).mappings().all()
            per_player = {}
            for row in rows:
                per_player.setdefault(row["player_id"], []).append((row["start_date"], float(row["metric"] or 0)))
            match_stats[side] = per_player

        opposite_usage = {}
        if request.category != "ALL_ROUNDERS" and side_rows.get(sides[0]):
            opposite_side = "bowling" if request.category == "BATTERS" else "batting"
            filter_sql, filter_params = _filters(request, opposite_side)
            player_col = "d.bowler_id" if opposite_side == "bowling" else "d.batter_id"
            usage_rows = db.execute(text(f"""
              SELECT {player_col} player_id, COUNT(DISTINCT mi.id) innings,
                     SUM(CASE WHEN d.is_legal_ball THEN 1 ELSE 0 END) legal_balls,
                     SUM(CASE WHEN d.is_ball_faced_by_batter THEN 1 ELSE 0 END) balls_faced
              FROM deliveries d JOIN match_innings mi ON mi.id=d.innings_id JOIN matches m ON m.id=mi.match_id
              WHERE {player_col}=ANY(:ids) AND {filter_sql}
              GROUP BY {player_col}
            """), {**filter_params, "ids": list(side_rows[sides[0]])}).mappings().all()
            opposite_usage = {row["player_id"]: dict(row) for row in usage_rows}

        batting_milestones = {}
        batting_ids = list(side_rows.get("batting", {}))
        if batting_ids:
            milestone_sql, milestone_params = _filters(request, "batting")
            milestone_rows = db.execute(text(f"""
              SELECT innings.batter_id AS player_id,
                     COUNT(*) FILTER (WHERE innings_runs BETWEEN 50 AND 99) AS fifties,
                     COUNT(*) FILTER (WHERE innings_runs >= 100) AS hundreds
              FROM (
                SELECT d.batter_id, mi.id AS innings_id, SUM(d.batter_runs) AS innings_runs
                FROM deliveries d JOIN match_innings mi ON mi.id=d.innings_id JOIN matches m ON m.id=mi.match_id
                WHERE d.batter_id=ANY(:ids) AND {milestone_sql}
                GROUP BY d.batter_id,mi.id
              ) innings
              GROUP BY innings.batter_id
            """), {**milestone_params, "ids": batting_ids}).mappings().all()
            batting_milestones = {row["player_id"]: {"fifties": int(row["fifties"] or 0), "hundreds": int(row["hundreds"] or 0)} for row in milestone_rows}

        records = []
        if request.category == "ALL_ROUNDERS":
            pids = set(side_rows["batting"]) & set(side_rows["bowling"])
        else:
            pids = set(side_rows[sides[0]])
        today = date.today()
        for pid in pids:
            bat = side_rows.get("batting", {}).get(pid, {})
            bowl = side_rows.get("bowling", {}).get(pid, {})
            attrs = attr_map.get(pid, {})
            try:
                dob = date.fromisoformat(attrs.get("date_of_birth", "")[:10])
                age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
            except (ValueError, TypeError):
                age = None
            raw_role = (attrs.get("primary_role") or "").lower().replace("_", " ")
            opposite = opposite_usage.get(pid, {})
            has_bat_usage = (int(bat.get("innings") or 0) >= 8 and int(bat.get("balls_faced") or 0) >= 120) if bat else (int(opposite.get("innings") or 0) >= 8 and int(opposite.get("balls_faced") or 0) >= 120 if request.category == "BOWLERS" else False)
            has_bowl_usage = (int(bowl.get("innings") or 0) >= 8 and int(bowl.get("legal_balls") or 0) >= 120) if bowl else (int(opposite.get("innings") or 0) >= 8 and int(opposite.get("legal_balls") or 0) >= 120 if request.category == "BATTERS" else False)
            actual_allrounder = "round" in raw_role or (has_bat_usage and has_bowl_usage)
            if actual_allrounder:
                role = "Batting All-Rounder" if int(bat.get("balls_faced") or 0) >= int(bowl.get("legal_balls") or 0) else "Bowling All-Rounder"
            elif "wicket" in raw_role or "keeper" in raw_role:
                role = "Wicketkeeper-Batter"
            elif "bowl" in raw_role:
                role = "Specialist Bowler"
            elif "batt" in raw_role:
                role = "Specialist Batter"
            else:
                role = ROLE_LABELS[request.category]
            if request.category in ("BATTERS", "BOWLERS") and actual_allrounder:
                continue
            if request.role and request.role.lower() not in role.lower():
                continue
            if request.min_age is not None and (age is None or age < request.min_age):
                continue
            if request.max_age is not None and (age is None or age > request.max_age):
                continue
            bat_balls = int(bat.get("balls_faced") or 0)
            bat_innings = int(bat.get("innings") or 0)
            bowl_balls = int(bowl.get("legal_balls") or 0)
            bowl_innings = int(bowl.get("innings") or 0)
            matches = max(int(bat.get("matches") or 0), int(bowl.get("matches") or 0))
            if matches < request.minimum_matches:
                continue
            if request.category in ("BATTERS", "ALL_ROUNDERS") and (bat_innings < max(request.minimum_innings, 8 if request.category == "ALL_ROUNDERS" else 1) or bat_balls < max(request.minimum_balls_faced, 120 if request.category == "ALL_ROUNDERS" else 1)):
                continue
            if request.category in ("BOWLERS", "ALL_ROUNDERS") and (bowl_innings < max(request.minimum_innings, 8 if request.category == "ALL_ROUNDERS" else 1) or bowl_balls < max(request.minimum_legal_balls, 120 if request.category == "ALL_ROUNDERS" else 1)):
                continue
            bat_style = attrs.get("batting_style") or ""
            bowl_style = attrs.get("bowling_style") or ""
            nationality = attrs.get("nationality") or "Unknown"
            if request.nationality and request.nationality.casefold() != nationality.casefold():
                continue
            if request.batting_style and request.batting_style.lower() not in bat_style.lower():
                continue
            if request.bowling_style and request.bowling_style.lower() not in bowl_style.lower():
                continue
            style_group = "spin" if any(x in bowl_style.lower() for x in ("spin", "break", "orthodox")) else "pace" if any(x in bowl_style.lower() for x in ("fast", "pace", "medium")) else None
            if request.pace_spin and style_group != request.pace_spin:
                continue

            def ratio(n, d, multiplier=1.0):
                return round(float(n or 0) * multiplier / d, 2) if d else None
            bdismissals = int(bat.get("dismissals") or 0)
            bwickets = int(bowl.get("wickets") or 0)
            rec = {"player_id": pid, "player_name": "", "role": role, "age": age, "matches": matches,
                   "innings": bat_innings if bat else 0, "bowling_innings": bowl_innings,
                   "runs": int(bat.get("runs") or 0) if bat else None, "wickets": bwickets if bowl else None,
                   "balls_faced": bat_balls, "legal_balls": bowl_balls,
                   "powerplay_balls_faced": int(bat.get("pp_balls") or 0), "middle_balls_faced": int(bat.get("mid_balls") or 0),
                   "death_balls_faced": int(bat.get("death_balls") or 0),
                   "pace_balls_faced": int(bat.get("pace_balls") or 0), "spin_balls_faced": int(bat.get("spin_balls") or 0),
                   "powerplay_legal_balls": int(bowl.get("pp_legal") or 0), "middle_legal_balls": int(bowl.get("mid_legal") or 0),
                   "death_legal_balls": int(bowl.get("death_legal") or 0),
                   "batting_average": ratio(bat.get("runs"), bdismissals), "strike_rate": ratio(bat.get("runs"), bat_balls, 100),
                   "boundary_percentage": ratio(int(bat.get("boundaries") or 0), bat_balls, 100),
                   "dot_ball_percentage": ratio(int(bat.get("dots") or 0), bat_balls, 100),
                   "powerplay_strike_rate": ratio(bat.get("pp_runs"), bat.get("pp_balls"), 100),
                   "middle_over_strike_rate": ratio(bat.get("mid_runs"), bat.get("mid_balls"), 100),
                   "death_over_strike_rate": ratio(bat.get("death_runs"), bat.get("death_balls"), 100),
                   "pace_strike_rate": ratio(bat.get("pace_runs"), bat.get("pace_balls"), 100),
                   "spin_strike_rate": ratio(bat.get("spin_runs"), bat.get("spin_balls"), 100),
                   "bowling_average": ratio(bowl.get("runs_conceded"), bwickets),
                   "economy": ratio(bowl.get("runs_conceded"), bowl_balls, 6),
                   "bowling_strike_rate": ratio(bowl_balls, bwickets),
                   "wickets_per_match": ratio(bwickets, max(1, int(bowl.get("matches") or 0))),
                   "boundary_percentage_conceded": ratio(int(bowl.get("boundaries") or 0), bowl_balls, 100),
                   "powerplay_economy": ratio(bowl.get("pp_conceded"), bowl.get("pp_legal"), 6),
                   "middle_economy": ratio(bowl.get("mid_conceded"), bowl.get("mid_legal"), 6),
                   "death_economy": ratio(bowl.get("death_conceded"), bowl.get("death_legal"), 6),
                   "powerplay_wickets": int(bowl.get("pp_wickets") or 0) if int(bowl.get("pp_legal") or 0) else None,
                   "middle_wickets": int(bowl.get("mid_wickets") or 0) if int(bowl.get("mid_legal") or 0) else None,
                   "death_wickets": int(bowl.get("death_wickets") or 0) if int(bowl.get("death_legal") or 0) else None,
                   "death_boundary_percentage": ratio(int(bowl.get("death_boundaries") or 0), int(bowl.get("death_legal") or 0), 100),
                   "middle_dot_ball_percentage": ratio(int(bowl.get("mid_dots") or 0), int(bowl.get("mid_legal") or 0), 100),
                   "death_dot_ball_percentage": ratio(int(bowl.get("death_dots") or 0), int(bowl.get("death_legal") or 0), 100)}
            rec["nationality"] = nationality
            rec["batting_style"] = bat_style or None
            rec["bowling_style"] = bowl_style or None
            milestones = batting_milestones.get(pid)
            rec["fifties"] = milestones["fifties"] if milestones else (0 if bat else None)
            rec["hundreds"] = milestones["hundreds"] if milestones else (0 if bat else None)
            for side, prefix in (("batting", ""), ("bowling", "bowling_")):
                match_values = match_stats.get(side, {}).get(pid, [])
                if match_values:
                    metrics = [v for _, v in match_values]
                    cv = pstdev(metrics) / mean(metrics) if len(metrics) > 1 and mean(metrics) > 0 else None
                    rec[("consistency" if side == "batting" else "bowling_consistency")] = max(0.0, 100.0 * (1 - cv)) if cv is not None else None
                    recent = sorted(match_values, key=lambda x: x[0] or date.min, reverse=True)[:5]
                    rec[("recent_form" if side == "batting" else "bowling_recent_form")] = mean([v for _, v in recent]) if recent else None
                    if side == "batting":
                        rec["recent_match_runs"] = [{"date": when.isoformat() if when else None, "runs": value} for when, value in reversed(recent)]
                else:
                    rec[("consistency" if side == "batting" else "bowling_consistency")] = None
                    rec[("recent_form" if side == "batting" else "bowling_recent_form")] = None
                    if side == "batting":
                        rec["recent_match_runs"] = []
            rec["batting_consistency"] = rec.get("consistency")
            rec["batting_recent_form"] = rec.get("recent_form")
            rec["batting_sample"] = float(bat_innings) if bat else None
            rec["bowling_sample"] = float(bowl_innings) if bowl else None
            records.append(rec)

        names = {}
        if records:
            rows = db.execute(text("SELECT id, canonical_name FROM players WHERE id=ANY(:ids)"), {"ids": [r["player_id"] for r in records]}).mappings().all()
            names = {r["id"]: r["canonical_name"] for r in rows}
        for rec in records:
            rec["player_name"] = names.get(rec["player_id"], "Unknown")
        return records

    return get_or_build(key, build)


@router.post("/scouting/search", response_model=ScoutingResponse)
def scouting_search(request: ScoutingRequest, db: Session = Depends(get_db)):
    if request.format not in FORMATS:
        raise HTTPException(status_code=422, detail="Unsupported format")
    preset_map = SCOUTING_PRESETS[request.category]
    if request.preset and request.preset not in preset_map and request.preset != "Custom":
        raise HTTPException(status_code=422, detail="Preset is not valid for the selected scouting category")
    if request.category == "BOWLERS" and request.preset == "Pace Specialist" and not request.pace_spin:
        request.pace_spin = "pace"
    elif request.category == "BOWLERS" and request.preset == "Spin Specialist" and not request.pace_spin:
        request.pace_spin = "spin"
    if request.weights:
        weights = request.weights
    elif request.priorities and request.category == "BATTERS":
        weights = {"batting_average": request.priorities.get("batting_average", 0),
                   "strike_rate": request.priorities.get("strike_rate", 0),
                   "middle_over_strike_rate": request.priorities.get("middle_over_scoring", 0),
                   "death_over_strike_rate": request.priorities.get("death_over_scoring", 0),
                   "consistency": request.priorities.get("consistency", 0)}
    else:
        weights = preset_map.get(request.preset or next(iter(preset_map)))
    if not weights or any(value < 0 for value in weights.values()) or sum(weights.values()) <= 0:
        raise HTTPException(status_code=422, detail="Scoring weights must have a positive total and cannot be negative")

    # Do not mutate the cache entry when applying per-search metric bounds.
    records = [dict(record) for record in _candidate_rows(db, request)]
    # Role-specific phase and matchup objectives require an actual sample in the
    # named phase or matchup. An absent phase is unavailable evidence, never zero.
    required_sample = {
        "Powerplay Aggressor": "powerplay_balls_faced", "Middle-Order Anchor": "middle_balls_faced",
        "Finisher": "death_balls_faced", "Spin Dominator": "spin_balls_faced", "Pace Dominator": "pace_balls_faced",
        "Powerplay Specialist": "powerplay_legal_balls", "Death-Over Specialist": "death_legal_balls",
        "Middle-Over Controller": "middle_legal_balls",
    }.get(request.preset or "")
    if required_sample:
        records = [r for r in records if int(r.get(required_sample) or 0) >= 30]
    metric_alias = {"average": "batting_average", "strike_rate": "strike_rate", "economy": "economy", "bowling_average": "bowling_average"}
    for record in records:
        for key, minimum in request.metric_min.items():
            feature = metric_alias.get(key, key)
            if record.get(feature) is None or record[feature] < minimum:
                record["_filtered"] = True
        for key, maximum in request.metric_max.items():
            feature = metric_alias.get(key, key)
            if record.get(feature) is None or record[feature] > maximum:
                record["_filtered"] = True
    records = [r for r in records if not r.get("_filtered")]
    scored = score_cohort(records, request.category, weights)
    # Scores remain cohort-specific and format-specific; sorting is an optional view.
    sort_key = request.sort_by if request.sort_by in (set(weights) | {"score", "matches", "runs", "wickets", "age", "batting_average", "strike_rate", "economy", "bowling_average"}) else "score"
    scored.sort(key=lambda r: (r.get(sort_key) is not None, r.get("overall_score", 0) if sort_key == "score" else (r.get(sort_key) or 0)), reverse=request.sort_desc)
    total = len(scored)
    start = (request.page - 1) * request.page_size
    page_rows = scored[start:start + request.page_size]
    candidates = []
    for offset, row in enumerate(page_rows, start=start + 1):
        stats = {k: row.get(k) for k in ("runs", "fifties", "hundreds", "batting_average", "strike_rate", "boundary_percentage", "dot_ball_percentage", "pace_strike_rate", "spin_strike_rate", "powerplay_strike_rate", "middle_over_strike_rate", "death_over_strike_rate", "consistency", "recent_form", "batting_consistency", "batting_recent_form", "bowling_consistency", "bowling_recent_form", "batting_sample", "bowling_sample", "wickets", "wickets_per_match", "bowling_average", "economy", "bowling_strike_rate", "boundary_percentage_conceded", "powerplay_economy", "powerplay_wickets", "middle_economy", "middle_wickets", "death_economy", "death_wickets", "powerplay_balls_faced", "middle_balls_faced", "death_balls_faced", "pace_balls_faced", "spin_balls_faced", "powerplay_legal_balls", "middle_legal_balls", "death_legal_balls", "matches", "innings", "bowling_innings", "age")}
        sample_balls = row["balls_faced"] if request.category != "BOWLERS" else row["legal_balls"]
        sample_innings = row["innings"] if request.category != "BOWLERS" else row["bowling_innings"]
        confidence = "High" if row["matches"] >= 30 and sample_innings >= 25 and sample_balls >= 600 else "Medium" if row["matches"] >= 10 and sample_innings >= 10 else "Low · limited sample"
        candidates.append(ScoutingCandidate(
            rank=offset, player_id=row["player_id"], player_name=row["player_name"], role=row["role"],
            nationality=row.get("nationality"), batting_style=row.get("batting_style"), bowling_style=row.get("bowling_style"),
            recent_match_runs=row.get("recent_match_runs", []),
            matches=row["matches"], innings=row["innings"], bowling_innings=row["bowling_innings"],
            runs=row["runs"], wickets=row["wickets"], balls_faced=row["balls_faced"], legal_balls=row["legal_balls"],
            overall_score=row["overall_score"], suitability_score=row["suitability_score"],
            batting_score=row["batting_score"], bowling_score=row["bowling_score"],
            metric_scores=row["metric_scores"], stats=stats, confidence=confidence,
            strengths=row["strengths"], limitations=row["limitations"], explanation=row["explanation"],
            batting_average=row.get("batting_average"), strike_rate=row.get("strike_rate"),
            middle_over_strike_rate=row.get("middle_over_strike_rate"), death_over_strike_rate=row.get("death_over_strike_rate"),
        ))
    plot_rows = [row for row in scored if row.get("batting_average") is not None and row.get("strike_rate") is not None]
    plot_limit = 2500
    stride = max(1, ceil(len(plot_rows) / plot_limit))
    plot_points = [{
        "player_id": row["player_id"], "player_name": row["player_name"], "role": row["role"],
        "nationality": row.get("nationality") or "Unknown", "batting_style": row.get("batting_style"),
        "bowling_style": row.get("bowling_style"), "batting_average": row["batting_average"],
        "strike_rate": row["strike_rate"], "matches": row["matches"], "innings": row["innings"],
        "runs": row.get("runs"), "recent_form": row.get("recent_form"),
        "recent_match_runs": row.get("recent_match_runs", []), "overall_score": row.get("overall_score"),
    } for row in plot_rows[::stride][:plot_limit]]
    def distribution(key, fallback="Unknown"):
        counts = {}
        for row in scored:
            value = row.get(key) or fallback
            counts[value] = counts.get(value, 0) + 1
        return [{"label": name, "value": count} for name, count in sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))]
    def category_for(role):
        role = (role or "").casefold()
        if "all-rounder" in role or "all rounder" in role:
            return "All-Rounder"
        if "wicketkeeper" in role or "wicket keeper" in role or "keeper" in role:
            return "Wicketkeeper-Batter"
        if "bowler" in role:
            return "Bowler"
        if "batter" in role:
            return "Batter"
        return "Unclassified"
    category_counts = {}
    for row in scored:
        group = category_for(row.get("role"))
        category_counts[group] = category_counts.get(group, 0) + 1
    valid_plot = plot_rows
    visualization = {
        "points": plot_points, "eligible_batting_points": len(plot_rows),
        "sampled": len(plot_rows) > plot_limit, "plot_limit": plot_limit,
        "reference_average": mean([row["batting_average"] for row in valid_plot]) if valid_plot else None,
        "reference_strike_rate": mean([row["strike_rate"] for row in valid_plot]) if valid_plot else None,
        "nationality": distribution("nationality"), "role": distribution("role"),
        "batting_style": distribution("batting_style"), "bowling_style": distribution("bowling_style"),
        "player_category": [{"label": name, "value": count} for name, count in sorted(category_counts.items(), key=lambda pair: (-pair[1], pair[0]))],
        "cohort_size": len(scored),
    }
    return ScoutingResponse(
        candidates=candidates, total_eligible=total, page=request.page, page_size=request.page_size,
        total_pages=ceil(total / request.page_size) if total else 0,
        filters_applied=request.model_dump(exclude={"weights", "priorities", "metric_min", "metric_max"}),
        visualization=visualization,
        score_explanation=(
            f"{request.category.title()} · {request.format} · {request.preset or 'Custom'}: weighted percentile scores are calculated only within this format and filtered cohort. "
            f"Configured weights: {', '.join(f'{name.replace(chr(95), chr(32))} {weight / sum(weights.values()):.0%}' for name, weight in weights.items())}. "
            "Missing metrics are omitted and remaining weights renormalized; scores are evaluation rankings, not forecasts."
        ),
    )
