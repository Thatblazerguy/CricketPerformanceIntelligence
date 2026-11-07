"""Format-scoped bowling feature extraction for role-aware similarity."""
import pandas as pd
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.models.models import Delivery, Match, MatchInnings, Player, Wicket


BOWLING_FEATURE_COLUMNS = [
    "bowling_average", "economy", "bowling_strike_rate", "wickets_per_match",
    "dot_ball_pct", "boundary_pct_conceded", "powerplay_economy",
    "powerplay_wickets", "middle_economy", "middle_wickets",
    "death_economy", "death_wickets", "legal_balls_per_match",
]


def extract_bowling_feature_matrix(
    db: Session, format_filter: str = "T20", min_innings: int = 5, min_legal_balls: int = 60
) -> pd.DataFrame:
    """Aggregate bowler-only features; players enter only with actual bowling usage."""
    rows = db.execute(
        select(
            Delivery.bowler_id.label("player_id"),
            func.count(func.distinct(MatchInnings.id)).label("innings"),
            func.count(func.distinct(Match.id)).label("matches"),
            func.sum(case((Delivery.is_legal_ball, 1), else_=0)).label("legal_balls"),
            func.sum(Delivery.bowling_runs).label("runs_conceded"),
            func.sum(case((Delivery.is_legal_ball & (Delivery.bowling_runs == 0), 1), else_=0)).label("dots"),
            func.sum(case((Delivery.is_boundary_four | Delivery.is_boundary_six, 1), else_=0)).label("boundaries"),
            func.sum(case((Delivery.phase == "powerplay", Delivery.bowling_runs), else_=0)).label("pp_runs"),
            func.sum(case(((Delivery.phase == "powerplay") & Delivery.is_legal_ball, 1), else_=0)).label("pp_balls"),
            func.sum(case((Delivery.phase == "middle", Delivery.bowling_runs), else_=0)).label("mid_runs"),
            func.sum(case(((Delivery.phase == "middle") & Delivery.is_legal_ball, 1), else_=0)).label("mid_balls"),
            func.sum(case((Delivery.phase == "death", Delivery.bowling_runs), else_=0)).label("death_runs"),
            func.sum(case(((Delivery.phase == "death") & Delivery.is_legal_ball, 1), else_=0)).label("death_balls"),
        )
        .join(MatchInnings, Delivery.innings_id == MatchInnings.id)
        .join(Match, MatchInnings.match_id == Match.id)
        .where(Match.match_format == format_filter, MatchInnings.is_super_over.is_(False), Delivery.bowler_id.isnot(None))
        .group_by(Delivery.bowler_id)
        .having(
            func.count(func.distinct(MatchInnings.id)) >= min_innings,
            func.sum(case((Delivery.is_legal_ball, 1), else_=0)) >= min_legal_balls,
        )
    ).mappings().all()
    if not rows:
        return pd.DataFrame()

    ids = [row["player_id"] for row in rows]
    wickets = dict(db.execute(
        select(Delivery.bowler_id, func.count(Wicket.id))
        .join(Wicket, Wicket.delivery_id == Delivery.id)
        .join(MatchInnings, Delivery.innings_id == MatchInnings.id)
        .join(Match, MatchInnings.match_id == Match.id)
        .where(Match.match_format == format_filter, Wicket.is_bowler_wicket.is_(True), Delivery.bowler_id.in_(ids))
        .group_by(Delivery.bowler_id)
    ).all())
    names = {p.id: p.canonical_name for p in db.execute(select(Player).where(Player.id.in_(ids))).scalars()}

    records = []
    for row in rows:
        balls, runs = int(row["legal_balls"] or 0), int(row["runs_conceded"] or 0)
        wkts, matches = int(wickets.get(row["player_id"], 0)), int(row["matches"] or 0)
        def economy(r, b): return round((r or 0) * 6 / b, 3) if b else None
        records.append({
            "player_id": row["player_id"], "player_name": names.get(row["player_id"], "Unknown"),
            "innings": int(row["innings"] or 0), "matches": matches, "legal_balls": balls,
            "wickets": wkts, "runs_conceded": runs,
            "bowling_average": round(runs / wkts, 3) if wkts else None,
            "economy": economy(runs, balls), "bowling_strike_rate": round(balls / wkts, 3) if wkts else None,
            "wickets_per_match": round(wkts / matches, 3) if matches else None,
            "dot_ball_pct": round(int(row["dots"] or 0) * 100 / balls, 3) if balls else None,
            "boundary_pct_conceded": round(int(row["boundaries"] or 0) * 100 / balls, 3) if balls else None,
            "powerplay_economy": economy(row["pp_runs"], row["pp_balls"]),
            "powerplay_wickets": None, "middle_economy": economy(row["mid_runs"], row["mid_balls"]),
            "middle_wickets": None, "death_economy": economy(row["death_runs"], row["death_balls"]),
            "death_wickets": None, "legal_balls_per_match": round(balls / matches, 3) if matches else None,
        })
    # Add phase wickets from bowler-credited dismissals at the dismissal delivery's phase.
    for phase, key in (("powerplay", "powerplay_wickets"), ("middle", "middle_wickets"), ("death", "death_wickets")):
        phase_wickets = dict(db.execute(
            select(Delivery.bowler_id, func.count(Wicket.id))
            .join(Wicket, Wicket.delivery_id == Delivery.id)
            .join(MatchInnings, Delivery.innings_id == MatchInnings.id)
            .join(Match, MatchInnings.match_id == Match.id)
            .where(Match.match_format == format_filter, Delivery.phase == phase,
                   Wicket.is_bowler_wicket.is_(True), Delivery.bowler_id.in_(ids))
            .group_by(Delivery.bowler_id)
        ).all())
        for record in records:
            record[key] = int(phase_wickets.get(record["player_id"], 0))
    return pd.DataFrame(records).set_index("player_id")
