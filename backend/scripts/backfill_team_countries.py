"""Backfill teams.country only from consistent, auditable CPI evidence.

Run after Alembic migration 20261107teamcountry. The script never overwrites an
existing country and can be previewed with --dry-run.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, text, func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.models import Team
from app.models.models import Match, Venue


NATIONAL_SIDE_SQL = text("""
WITH player_sides AS (
  SELECT i.batting_team_id AS team_id, d.batter_id AS player_id
  FROM matches m JOIN match_innings i ON i.match_id=m.id AND i.is_super_over=FALSE
  JOIN deliveries d ON d.innings_id=i.id
  WHERE m.match_format IN ('Test','ODI','T20I') AND i.batting_team_id IS NOT NULL
  UNION ALL
  SELECT CASE WHEN i.batting_team_id=m.team1_id THEN m.team2_id ELSE m.team1_id END AS team_id,
         d.bowler_id AS player_id
  FROM matches m JOIN match_innings i ON i.match_id=m.id AND i.is_super_over=FALSE
  JOIN deliveries d ON d.innings_id=i.id
  WHERE m.match_format IN ('Test','ODI','T20I') AND i.batting_team_id IS NOT NULL
), votes AS (
  SELECT ps.team_id, e.nationality AS country, COUNT(DISTINCT ps.player_id) AS players
  FROM player_sides ps JOIN player_nationality_evidence e ON e.player_id=ps.player_id
  WHERE ps.team_id IS NOT NULL AND e.verification_status IN ('verified','resolved')
    AND e.nationality NOT IN ('Unknown','Indian','Overseas','')
  GROUP BY ps.team_id,e.nationality
), ranked AS (
  SELECT team_id,country,players,
         SUM(players) OVER (PARTITION BY team_id) AS all_players,
         ROW_NUMBER() OVER (PARTITION BY team_id ORDER BY players DESC,country) AS rank
  FROM votes
)
SELECT team_id,country,players,all_players FROM ranked
WHERE rank=1 AND players >= 3 AND players::numeric / NULLIF(all_players,0) >= 0.60
""")

TOURNAMENT_SQL = text("""
WITH national_teams AS (
  SELECT DISTINCT team_id FROM matches
  CROSS JOIN LATERAL (VALUES (team1_id),(team2_id)) AS sides(team_id)
  WHERE match_format IN ('Test','ODI','T20I') AND team_id IS NOT NULL
), team_country_matches AS (
  SELECT sides.team_id,t.country,m.id AS match_id
  FROM matches m JOIN tournaments t ON t.id=m.tournament_id
  CROSS JOIN LATERAL (VALUES (m.team1_id),(m.team2_id)) AS sides(team_id)
  WHERE sides.team_id IS NOT NULL AND t.country IS NOT NULL AND trim(t.country)<>''
    AND NOT EXISTS (SELECT 1 FROM national_teams n WHERE n.team_id=sides.team_id)
), country_counts AS (
  SELECT team_id,COUNT(DISTINCT country) AS country_count FROM team_country_matches GROUP BY team_id
), countries AS (
  SELECT team_id,country,COUNT(DISTINCT match_id) AS matches
  FROM team_country_matches GROUP BY team_id,country
), ranked AS (
  SELECT c.*,cc.country_count,ROW_NUMBER() OVER (PARTITION BY c.team_id ORDER BY c.matches DESC,c.country) AS rank
  FROM countries c JOIN country_counts cc USING (team_id)
)
SELECT team_id,country,matches FROM ranked WHERE rank=1 AND country_count=1 AND matches >= 5
""")


def is_composite_team(name: str) -> bool:
    """All-star/invitational XIs do not have a single represented country."""
    return bool(re.search(r"\bxi\b", name or "", flags=re.IGNORECASE))


def run():
    engine = create_engine(settings.DATABASE_URL)
    dry_run = "--dry-run" in sys.argv
    with Session(engine) as db:
        total_teams = db.query(Team).count()
        teams = {team.id: team for team in db.query(Team).all()}
        cleared_composite = 0
        for team in teams.values():
            if is_composite_team(team.canonical_name) and team.country_source in {
                "verified_international_player_affiliations", "consistent_tournament_country"
            }:
                team.country = team.country_source = team.country_confidence = None
                cleared_composite += 1
        existing = {row.id: row for row in db.query(Team).filter(Team.country.is_not(None)).all()}
        candidates = {}
        for row in db.execute(NATIONAL_SIDE_SQL).mappings():
            if not is_composite_team(teams[row["team_id"]].canonical_name):
                candidates[row["team_id"]] = (row["country"], "verified_international_player_affiliations", "high")
        for row in db.execute(TOURNAMENT_SQL).mappings():
            if not is_composite_team(teams[row["team_id"]].canonical_name):
                candidates.setdefault(row["team_id"], (row["country"], "consistent_tournament_country", "medium"))
        updated = []
        for team_id, (country, source, confidence) in candidates.items():
            team = existing.get(team_id) or db.get(Team, team_id)
            if team is None or team.country:
                continue
            updated.append({"team": team.canonical_name, "country": country, "source": source, "confidence": confidence})
            if not dry_run:
                team.country, team.country_source, team.country_confidence = country, source, confidence
        venue_totals = db.query(Venue).count()
        venue_country_mapped = db.query(Venue).filter(Venue.country.is_not(None)).count()
        team_country_mapped = db.query(Team).filter(Team.country.is_not(None)).count()
        unresolved = total_teams - team_country_mapped
        mapped_team_rows = db.query(Team).filter(Team.country.is_not(None)).order_by(Team.canonical_name).all()
        mapped_sources = {source or "unspecified": count for source, count in db.query(
            Team.country_source, func.count(Team.id)).filter(Team.country.is_not(None)).group_by(Team.country_source).all()}
        gender_matches = {gender: count for gender, count in db.query(Match.gender, func.count(Match.id)).group_by(Match.gender).all()}
        if not dry_run:
            db.commit()
        else:
            db.rollback()
        report = {"dry_run": dry_run, "total_teams": total_teams, "composite_country_mappings_cleared": cleared_composite,
            "already_mapped_before_run": len(existing), "country_mappings_written": len(updated),
            "team_country_coverage": {"total_teams": total_teams, "mapped_teams": team_country_mapped,
                                      "unmapped_teams": total_teams - team_country_mapped,
                                      "source_counts": mapped_sources,
                                      "mapped_examples": [{"team": t.canonical_name, "country": t.country,
                                          "source": t.country_source, "confidence": t.country_confidence}
                                          for t in mapped_team_rows[:30]]},
            "unresolved_after_backfill": max(0, unresolved), "matches_by_gender": gender_matches,
            "venue_country_coverage": {"total_venues": venue_totals, "mapped_venues": venue_country_mapped,
                                       "unmapped_venues": venue_totals - venue_country_mapped},
            "examples": updated[:30]}
        print(json.dumps(report, indent=2, default=str))
        if not dry_run:
            report_path = Path(__file__).resolve().parents[2] / "data/reports/team_country_backfill.json"
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")


if __name__ == "__main__":
    run()
