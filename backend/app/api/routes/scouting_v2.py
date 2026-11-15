"""Scouting intelligence API: recruitment requirements, role rankings, reports, comparisons.

The original ``/scouting/search`` endpoints remain available unchanged.
"""
from typing import Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.analytics import scouting_engine as engine
from app.analytics import scouting_report as reports
from app.analytics.scouting_aggregates import tables_exist
from app.analytics.scouting_roles import LIMITED, METRICS, POSITION_SHARE, metric_catalog, role_catalog, thresholds
from app.db.session import get_db

router = APIRouter(prefix="/scouting/v2")


class ScopeIn(BaseModel):
    format: Literal["T20", "T20I", "ODI", "ODM", "Test", "MDM"] = "T20"
    gender: Literal["male", "female", "all"] = "male"
    competitions: List[str] = Field(default_factory=list)
    seasons: List[str] = Field(default_factory=list)
    start_year: Optional[int] = None
    end_year: Optional[int] = None

    @model_validator(mode="after")
    def _years(self):
        if self.start_year and self.end_year and self.start_year > self.end_year:
            raise ValueError("start_year must be on or before end_year")
        return self

    def to_scope(self) -> engine.Scope:
        return engine.Scope(self.format, self.gender, tuple(sorted(self.competitions)), tuple(sorted(self.seasons)),
                            self.start_year, self.end_year)


class Bound(BaseModel):
    metric: str
    op: Literal["min", "max"]
    value: float


class RankRequest(ScopeIn):
    role: str = "batter"
    nationality: Optional[str] = None
    batting_hand: Optional[str] = None
    bowling_arm: Optional[str] = None
    bowling_styles: List[str] = Field(default_factory=list)
    bowling_type: Optional[Literal["pace", "spin"]] = None
    positions: List[int] = Field(default_factory=list)
    min_matches: int = Field(0, ge=0)
    min_innings: int = Field(0, ge=0)
    min_dual_matches: int = Field(0, ge=0)
    min_age: Optional[int] = Field(None, ge=10, le=60)
    max_age: Optional[int] = Field(None, ge=10, le=60)
    requirements: List[Bound] = Field(default_factory=list)
    weights: Optional[Dict[str, float]] = None
    allrounder_batting_weight: float = Field(0.5, ge=0, le=1)
    min_tier: Optional[Literal["Established", "Promising"]] = None
    limit: int = Field(100, ge=1, le=500)

    @model_validator(mode="after")
    def _validate(self):
        if self.role not in engine.ROLES:
            raise ValueError(f"Unknown role model '{self.role}'")
        for bound in self.requirements:
            if bound.metric not in METRICS:
                raise ValueError(f"Unknown metric '{bound.metric}'")
            if METRICS[bound.metric].limited_only and self.format not in LIMITED:
                raise ValueError(f"{METRICS[bound.metric].label} is not defined for {self.format}")
        if self.weights:
            unknown = [k for k in self.weights if k not in METRICS]
            if unknown:
                raise ValueError(f"Unknown weight metrics: {', '.join(unknown)}")
            if any(v < 0 for v in self.weights.values()) or sum(self.weights.values()) <= 0:
                raise ValueError("Weights must be non-negative with a positive total")
        if any(p < 1 or p > 11 for p in self.positions):
            raise ValueError("Batting positions must be between 1 and 11")
        if self.min_age and self.max_age and self.min_age > self.max_age:
            raise ValueError("min_age must not exceed max_age")
        return self


class CompareRequest(ScopeIn):
    role: str = "batter"
    player_ids: List[str] = Field(min_length=1, max_length=8)


def _require_tables(db: Session):
    if not tables_exist(db):
        raise HTTPException(status_code=503, detail="Scouting aggregates are not built. Run "
                                                    "scripts/build_scouting_aggregates.py after `alembic upgrade head`.")


@router.get("/options")
def options(db: Session = Depends(get_db)):
    _require_tables(db)
    coverage = db.execute(text("""
        SELECT
          (SELECT COUNT(DISTINCT player_id) FROM player_attributes WHERE attribute_type = 'bowling_type') AS bowling_type,
          (SELECT COUNT(DISTINCT player_id) FROM player_attributes WHERE attribute_type = 'bowling_style') AS bowling_style,
          (SELECT COUNT(DISTINCT player_id) FROM player_attributes WHERE attribute_type = 'batting_style') AS batting_hand,
          (SELECT COUNT(DISTINCT player_id) FROM player_attributes WHERE attribute_type = 'date_of_birth') AS date_of_birth,
          (SELECT COUNT(DISTINCT player_id) FROM player_attributes WHERE attribute_type = 'nationality'
                  AND attribute_value <> 'Unknown') AS nationality,
          (SELECT COUNT(*) FROM players) AS players
    """)).mappings().one()
    styles = [r[0] for r in db.execute(text("""
        SELECT attribute_value FROM player_attributes WHERE attribute_type = 'bowling_style'
          AND attribute_value NOT ILIKE 'other%' GROUP BY 1 ORDER BY COUNT(*) DESC""")).all()]
    nationalities = [r[0] for r in db.execute(text("""
        SELECT attribute_value FROM player_attributes WHERE attribute_type = 'nationality' AND attribute_value <> 'Unknown'
        GROUP BY 1 ORDER BY 1""")).all()]
    competitions = db.execute(text("""
        SELECT t.name, m.match_format, lower(m.gender) AS gender, COUNT(*) AS matches
        FROM matches m JOIN tournaments t ON t.id = m.tournament_id GROUP BY 1, 2, 3 ORDER BY 4 DESC""")).mappings().all()
    seasons = db.execute(text("""
        SELECT season, match_format, lower(gender) AS gender, COUNT(*) AS matches FROM matches
        GROUP BY 1, 2, 3 ORDER BY 1 DESC""")).mappings().all()
    return {
        "formats": ["T20", "T20I", "ODI", "ODM", "Test", "MDM"],
        "roles": role_catalog(),
        "metrics": metric_catalog(),
        "thresholds": {f: thresholds(f) for f in ("T20", "ODI", "Test")},
        "position_share": POSITION_SHARE,
        "bowling_styles": styles,
        "bowling_arms": ["right-arm", "left-arm"],
        "nationalities": nationalities,
        "competitions": [dict(r) for r in competitions],
        "seasons": [dict(r) for r in seasons],
        "coverage": {
            **dict(coverage),
            "notes": [
                f"Pace/spin classification is sourced for {coverage['bowling_type']} bowlers; deliveries from other "
                "bowlers are excluded from pace/spin splits (each split reports its classified share).",
                f"Detailed bowling style is sourced for {coverage['bowling_style']} bowlers.",
                f"Batting hand is sourced for only {coverage['batting_hand']} players, so left/right-handed matchup "
                "analysis and batting-hand filters cannot be supported reliably.",
                f"Verified date of birth exists for only {coverage['date_of_birth']} players; age filters exclude "
                "everyone else rather than guessing.",
                "No auction-value or salary data source is linked to scouting; budget filters are not offered.",
                "Pitch-type data does not exist in the Cricsheet feed; 'conditions' are shown by venue country only.",
                "Wicketkeeping quality is not scored: catches cannot be attributed to the keeper. Keeper identity uses "
                "stumping evidence or verified metadata.",
            ],
        },
    }


@router.post("/rank")
def rank(request: RankRequest, db: Session = Depends(get_db)):
    _require_tables(db)
    req = engine.Requirements(
        role=request.role, nationality=request.nationality, batting_hand=request.batting_hand,
        bowling_arm=request.bowling_arm, bowling_styles=tuple(request.bowling_styles), bowling_type=request.bowling_type,
        positions=tuple(sorted(set(request.positions))), min_matches=request.min_matches, min_innings=request.min_innings,
        min_dual_matches=request.min_dual_matches, min_age=request.min_age, max_age=request.max_age,
        bounds=tuple((b.metric, b.op, b.value) for b in request.requirements), weights=request.weights,
        allrounder_batting_weight=request.allrounder_batting_weight,
        min_tier={"Established": "Established", "Promising": "Promising – limited evidence"}.get(request.min_tier or ""),
    )
    try:
        return engine.rank(db, request.to_scope(), req, limit=request.limit)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/player/{player_id}/report")
def report(player_id: str, format: str = Query("T20"), gender: str = Query("male"),
           competitions: List[str] = Query(default=[]), seasons: List[str] = Query(default=[]),
           start_year: Optional[int] = None, end_year: Optional[int] = None, role: Optional[str] = None,
           db: Session = Depends(get_db)):
    _require_tables(db)
    scope = ScopeIn(format=format, gender=gender, competitions=competitions, seasons=seasons,
                    start_year=start_year, end_year=end_year).to_scope()
    if not db.execute(text("SELECT 1 FROM players WHERE id = :p"), {"p": player_id}).scalar():
        raise HTTPException(status_code=404, detail="Player not found")
    return reports.build_report(db, scope, player_id, role)


@router.get("/player/{player_id}/formats")
def player_formats(player_id: str, gender: str = Query("male"), db: Session = Depends(get_db)):
    """Format suitability: the player's record in each format against that format's regulars."""
    _require_tables(db)
    return reports.format_suitability(db, engine.Scope("T20", gender), player_id)


@router.post("/compare")
def compare(request: CompareRequest, db: Session = Depends(get_db)):
    _require_tables(db)
    try:
        return reports.compare(db, request.to_scope(), request.player_ids, request.role)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
