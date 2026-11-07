"""
Player Feature Extraction for Similarity & Machine Learning.
Computes multi-dimensional performance feature vectors from actual delivery data.
"""
from typing import Dict, List, Optional
import pandas as pd
import numpy as np
from sqlalchemy.orm import Session
from sqlalchemy import select, func, case

from app.models.models import Delivery, MatchInnings, Match, Wicket, Player


FEATURE_COLUMNS = [
    "batting_average",
    "strike_rate",
    "boundary_pct",
    "dot_ball_pct",
    "powerplay_sr",
    "middle_over_sr",
    "death_over_sr",
    "innings",
]


def extract_player_feature_matrix(
    db: Session,
    format_filter: str = "T20",
    min_innings: int = 10,
    min_balls: int = 60,
) -> pd.DataFrame:
    """
    Extract aggregated statistical features for all players meeting sample criteria.
    Returns DataFrame indexed by player_id.
    """
    # 1. Deliveries aggregated per batter
    delivery_stats = db.execute(
        select(
            Delivery.batter_id,
            func.count(func.distinct(MatchInnings.id)).label("innings"),
            func.sum(case((Delivery.is_ball_faced_by_batter == True, 1), else_=0)).label("balls_faced"),
            func.sum(Delivery.batter_runs).label("runs"),
            func.sum(case((Delivery.is_legal_ball & (Delivery.batter_runs == 0), 1), else_=0)).label("dot_balls"),
            func.sum(case((Delivery.is_boundary_four | Delivery.is_boundary_six, 1), else_=0)).label("boundaries"),
            # Phase runs & balls
            func.sum(case((Delivery.phase == "powerplay", Delivery.batter_runs), else_=0)).label("pp_runs"),
            func.sum(case(((Delivery.phase == "powerplay") & Delivery.is_ball_faced_by_batter, 1), else_=0)).label("pp_balls"),
            func.sum(case((Delivery.phase == "middle", Delivery.batter_runs), else_=0)).label("mid_runs"),
            func.sum(case(((Delivery.phase == "middle") & Delivery.is_ball_faced_by_batter, 1), else_=0)).label("mid_balls"),
            func.sum(case((Delivery.phase == "death", Delivery.batter_runs), else_=0)).label("death_runs"),
            func.sum(case(((Delivery.phase == "death") & Delivery.is_ball_faced_by_batter, 1), else_=0)).label("death_balls"),
        )
        .join(MatchInnings, Delivery.innings_id == MatchInnings.id)
        .join(Match, MatchInnings.match_id == Match.id)
        .where(
            Match.match_format == format_filter,
            MatchInnings.is_super_over == False,
            Delivery.batter_id.isnot(None),
        )
        .group_by(Delivery.batter_id)
        .having(
            func.count(func.distinct(MatchInnings.id)) >= min_innings,
            func.sum(case((Delivery.is_ball_faced_by_batter == True, 1), else_=0)) >= min_balls,
        )
    ).fetchall()

    if not delivery_stats:
        return pd.DataFrame()

    player_ids = [row[0] for row in delivery_stats]

    # 2. Dismissals per player
    dismissal_rows = db.execute(
        select(Wicket.player_out_id, func.count(Wicket.id).label("dismissals"))
        .join(Delivery, Wicket.delivery_id == Delivery.id)
        .join(MatchInnings, Delivery.innings_id == MatchInnings.id)
        .join(Match, MatchInnings.match_id == Match.id)
        .where(
            Match.match_format == format_filter,
            Wicket.is_batter_dismissed == True,
            Wicket.player_out_id.in_(player_ids),
        )
        .group_by(Wicket.player_out_id)
    ).fetchall()
    dismissals_map = {row[0]: row[1] for row in dismissal_rows}

    # 3. Canonical player names
    names = {
        p.id: p.canonical_name
        for p in db.execute(select(Player).where(Player.id.in_(player_ids))).scalars().all()
    }

    records = []
    for row in delivery_stats:
        pid, inn, balls, runs, dots, bounds, pp_r, pp_b, mid_r, mid_b, death_r, death_b = row
        dismissals = dismissals_map.get(pid, 0)

        # An undefined average (no dismissals) is missing data, not a zero/one-out average.
        avg = (runs / dismissals) if dismissals > 0 else None
        sr = (runs / balls * 100) if balls > 0 else 0.0
        boundary_pct = (bounds / balls * 100) if balls > 0 else 0.0
        dot_pct = (dots / balls * 100) if balls > 0 else 0.0

        pp_sr = (pp_r / pp_b * 100) if pp_b > 0 else None
        mid_sr = (mid_r / mid_b * 100) if mid_b > 0 else None
        death_sr = (death_r / death_b * 100) if death_b > 0 else None

        records.append({
            "player_id": pid,
            "player_name": names.get(pid, "Unknown"),
            "innings": inn,
            "balls_faced": balls,
            "runs": runs,
            "batting_average": round(avg, 2) if avg is not None else None,
            "strike_rate": round(sr, 2),
            "boundary_pct": round(boundary_pct, 2),
            "dot_ball_pct": round(dot_pct, 2),
            "powerplay_sr": round(pp_sr, 2) if pp_sr is not None else None,
            "middle_over_sr": round(mid_sr, 2) if mid_sr is not None else None,
            "death_over_sr": round(death_sr, 2) if death_sr is not None else None,
        })

    df = pd.DataFrame(records).set_index("player_id")
    return df
