"""Read-only APIs for offline-computed win probability and WPA artifacts."""
from __future__ import annotations

import gzip
import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.models import Match, MatchWinProbability, PlayerWinProbabilityImpact, Team

router = APIRouter()


@router.get("/matches/{match_id}/win-probability")
def match_win_probability(match_id: str, db: Session = Depends(get_db)):
    match = db.get(Match, match_id)
    if not match:
        raise HTTPException(404, "Match not found")
    row = db.get(MatchWinProbability, match_id)
    if not row:
        return {"status": "not_precomputed", "match_id": match_id, "points": []}
    team1 = db.get(Team, match.team1_id) if match.team1_id else None
    team2 = db.get(Team, match.team2_id) if match.team2_id else None
    points = []
    if row.predictions_gzip:
        delivery_positions = {}
        for sequence, item in enumerate(json.loads(gzip.decompress(row.predictions_gzip))):
            innings, over, ball, batter_id, bowler_id, team1_batting = item[:6]
            before, after = item[6:9], item[9:12]
            runs, wickets, flags = item[12:15]
            delivery_index = delivery_positions.get(innings, 0)
            delivery_positions[innings] = delivery_index + 1
            delta_team1 = after[0] - before[0]
            batting_delta = delta_team1 if team1_batting else -delta_team1
            points.append({
                "sequence": sequence,
                "innings_number": innings,
                "delivery_index": delivery_index,
                "over": over,
                "ball": ball,
                "batter_id": batter_id,
                "bowler_id": bowler_id,
                "team1_batting": bool(team1_batting),
                "before": {"team1_win": before[0], "team2_win": before[1], "draw_or_tie": before[2]},
                "after": {"team1_win": after[0], "team2_win": after[1], "draw_or_tie": after[2]},
                "wpa": round(delta_team1, 6),
                "batting_wpa": round(batting_delta, 6),
                "bowling_wpa": round(-batting_delta, 6),
                "runs": runs,
                "wickets": wickets,
                "boundary": "six" if flags & 2 else "four" if flags & 1 else None,
            })
    return {
        "status": row.status,
        "match_id": match_id,
        "match_format": row.match_format,
        "format_family": row.format_family,
        "model_version": row.model_version,
        "team1": team1.canonical_name if team1 else "Team 1",
        "team2": team2.canonical_name if team2 else "Team 2",
        "outcomes": ["team1_win", "team2_win", "draw_or_tie"],
        "delivery_count": row.delivery_count,
        "exclusion_reason": row.exclusion_reason,
        "points": points,
    }


@router.get("/win-probability/coverage")
def win_probability_coverage(db: Session = Depends(get_db)):
    raw = db.execute(select(Match.match_format, func.count(Match.id)).group_by(Match.match_format)).all()
    saved = db.execute(select(MatchWinProbability.match_format, MatchWinProbability.status,
                              func.count(MatchWinProbability.match_id), func.coalesce(func.sum(MatchWinProbability.delivery_count), 0))
                       .group_by(MatchWinProbability.match_format, MatchWinProbability.status)).all()
    by_format = {fmt: {"matches": int(count), "precomputed": 0, "deliveries": 0, "statuses": {}} for fmt, count in raw}
    for fmt, status, count, deliveries in saved:
        entry = by_format.setdefault(fmt, {"matches": 0, "precomputed": 0, "deliveries": 0, "statuses": {}})
        entry["precomputed"] += int(count)
        entry["deliveries"] += int(deliveries)
        entry["statuses"][status] = int(count)
    return {
        "supported_families": {"T20": ["T20", "T20I"], "ODI": ["ODI", "ODM"], "Test": ["Test", "MDM"]},
        "formats": by_format,
        "total_matches": sum(v["matches"] for v in by_format.values()),
        "total_precomputed_matches": sum(v["precomputed"] for v in by_format.values()),
        "total_precomputed_deliveries": sum(v["deliveries"] for v in by_format.values()),
    }


@router.get("/players/{player_id}/impact")
def player_win_probability_impact(player_id: str, db: Session = Depends(get_db)):
    rows = db.scalars(select(PlayerWinProbabilityImpact).where(
        PlayerWinProbabilityImpact.player_id == player_id
    ).order_by(PlayerWinProbabilityImpact.match_format)).all()
    return {
        "player_id": player_id,
        "available": bool(rows),
        "method": "Delivery-level change in the player's side win probability; bowling WPA is signed from the bowler's team's perspective.",
        "formats": [{
            "format": row.match_format,
            "matches": row.matches,
            "batting_wpa": round(row.batting_wpa, 6),
            "bowling_wpa": round(row.bowling_wpa, 6),
            "career_wpa": round(row.batting_wpa + row.bowling_wpa, 6),
            "average_wpa_per_match": round((row.batting_wpa + row.bowling_wpa) / row.matches, 6) if row.matches else None,
            "peak_delivery_impact": round(row.peak_delivery_impact, 6),
            "peak_match_id": row.peak_match_id,
        } for row in rows],
    }
