"""Persisted per-innings team totals that back Team Analytics and Venue Analytics.

Team and venue profiles need innings totals, phase splits and boundary counts
for every innings in a format. Summing ~12M delivery rows per request is too
slow (≈13 s for all T20 innings), so the derivation is done once here and
refreshed for affected matches after every import
(``app.ingestion.dependent_refresh``), exactly like the scouting aggregates.

Rules (consistent with ``app.domain.cricket_rules`` and PHASE_RULES.md):

* One row per non-super-over innings that has at least one delivery.
* ``runs`` = sum of ``total_runs`` (bat + extras + penalties).
* ``legal_balls`` = ``is_legal_ball``; ``dots`` = legal balls with 0 total runs.
* ``wickets`` = ``wickets.is_batter_dismissed`` (retired hurt excluded).
* Phases come from ``deliveries.phase`` (powerplay / middle / death for
  limited-overs formats only).
* ``bowling_team_id`` is the other side of the match.
"""
from __future__ import annotations

import logging
from typing import Iterable

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

ALL_FORMATS = ("T20", "T20I", "ODI", "ODM", "Test", "MDM")
TABLE = "team_innings_summary"

DDL = [
    f"""
    CREATE TABLE IF NOT EXISTS {TABLE} (
        innings_id varchar(36) PRIMARY KEY,
        match_id varchar(36) NOT NULL,
        match_format varchar(32) NOT NULL,
        gender varchar(16) NOT NULL,
        start_date date NOT NULL,
        season varchar(16),
        tournament_id varchar(36),
        venue_id varchar(36),
        innings_number smallint NOT NULL,
        batting_team_id varchar(36),
        bowling_team_id varchar(36),
        target_runs integer,
        target_overs smallint,
        runs integer NOT NULL DEFAULT 0,
        legal_balls integer NOT NULL DEFAULT 0,
        wickets integer NOT NULL DEFAULT 0,
        fours integer NOT NULL DEFAULT 0,
        sixes integer NOT NULL DEFAULT 0,
        dots integer NOT NULL DEFAULT 0,
        extras integer NOT NULL DEFAULT 0,
        pp_runs integer NOT NULL DEFAULT 0, pp_balls integer NOT NULL DEFAULT 0, pp_wkts integer NOT NULL DEFAULT 0, pp_bnd integer NOT NULL DEFAULT 0,
        mid_runs integer NOT NULL DEFAULT 0, mid_balls integer NOT NULL DEFAULT 0, mid_wkts integer NOT NULL DEFAULT 0, mid_bnd integer NOT NULL DEFAULT 0,
        death_runs integer NOT NULL DEFAULT 0, death_balls integer NOT NULL DEFAULT 0, death_wkts integer NOT NULL DEFAULT 0, death_bnd integer NOT NULL DEFAULT 0
    )
    """,
    f"CREATE INDEX IF NOT EXISTS ix_tis_scope ON {TABLE} (match_format, gender, start_date)",
    f"CREATE INDEX IF NOT EXISTS ix_tis_match ON {TABLE} (match_id)",
    f"CREATE INDEX IF NOT EXISTS ix_tis_venue ON {TABLE} (venue_id, match_format)",
    f"CREATE INDEX IF NOT EXISTS ix_tis_bat_team ON {TABLE} (batting_team_id, match_format)",
    f"CREATE INDEX IF NOT EXISTS ix_tis_bowl_team ON {TABLE} (bowling_team_id, match_format)",
]

_INSERT = f"""
INSERT INTO {TABLE} (
    innings_id, match_id, match_format, gender, start_date, season, tournament_id, venue_id, innings_number,
    batting_team_id, bowling_team_id, target_runs, target_overs, runs, legal_balls, wickets, fours, sixes, dots, extras,
    pp_runs, pp_balls, pp_wkts, pp_bnd, mid_runs, mid_balls, mid_wkts, mid_bnd, death_runs, death_balls, death_wkts, death_bnd)
WITH w AS (
    SELECT w.delivery_id, COUNT(*) AS outs
    FROM wickets w JOIN deliveries d ON d.id = w.delivery_id
    JOIN match_innings mi ON mi.id = d.innings_id JOIN matches m ON m.id = mi.match_id
    WHERE w.is_batter_dismissed AND mi.is_super_over = FALSE AND {{scope}}
    GROUP BY w.delivery_id
)
SELECT mi.id, m.id, m.match_format, lower(m.gender), m.start_date, m.season, m.tournament_id, m.venue_id, mi.innings_number,
       mi.batting_team_id,
       CASE WHEN mi.batting_team_id = m.team1_id THEN m.team2_id WHEN mi.batting_team_id = m.team2_id THEN m.team1_id END,
       mi.target_runs, mi.target_overs,
       SUM(d.total_runs),
       COUNT(*) FILTER (WHERE d.is_legal_ball),
       COALESCE(SUM(w.outs), 0),
       COUNT(*) FILTER (WHERE d.is_boundary_four),
       COUNT(*) FILTER (WHERE d.is_boundary_six),
       COUNT(*) FILTER (WHERE d.is_legal_ball AND d.total_runs = 0),
       SUM(d.extras_runs),
       COALESCE(SUM(d.total_runs) FILTER (WHERE d.phase = 'powerplay'), 0),
       COUNT(*) FILTER (WHERE d.phase = 'powerplay' AND d.is_legal_ball),
       COALESCE(SUM(w.outs) FILTER (WHERE d.phase = 'powerplay'), 0),
       COUNT(*) FILTER (WHERE d.phase = 'powerplay' AND (d.is_boundary_four OR d.is_boundary_six)),
       COALESCE(SUM(d.total_runs) FILTER (WHERE d.phase = 'middle'), 0),
       COUNT(*) FILTER (WHERE d.phase = 'middle' AND d.is_legal_ball),
       COALESCE(SUM(w.outs) FILTER (WHERE d.phase = 'middle'), 0),
       COUNT(*) FILTER (WHERE d.phase = 'middle' AND (d.is_boundary_four OR d.is_boundary_six)),
       COALESCE(SUM(d.total_runs) FILTER (WHERE d.phase = 'death'), 0),
       COUNT(*) FILTER (WHERE d.phase = 'death' AND d.is_legal_ball),
       COALESCE(SUM(w.outs) FILTER (WHERE d.phase = 'death'), 0),
       COUNT(*) FILTER (WHERE d.phase = 'death' AND (d.is_boundary_four OR d.is_boundary_six))
FROM matches m
JOIN match_innings mi ON mi.match_id = m.id AND mi.is_super_over = FALSE
JOIN deliveries d ON d.innings_id = mi.id
LEFT JOIN w ON w.delivery_id = d.id
WHERE {{scope}}
GROUP BY mi.id, m.id
"""


def ensure_tables(conn) -> None:
    for statement in DDL:
        conn.execute(text(statement))


def tables_exist(db: Session) -> bool:
    return bool(db.execute(text(f"SELECT to_regclass('public.{TABLE}') IS NOT NULL")).scalar())


def rebuild_for_matches(db: Session, match_ids: Iterable[str]) -> dict:
    """Delete and rebuild rows for specific matches (incremental refresh). Commits."""
    ids = [m for m in set(match_ids) if m]
    if not ids or not tables_exist(db):
        return {"matches": 0}
    db.execute(text(f"DELETE FROM {TABLE} WHERE match_id = ANY(:ids)"), {"ids": ids})
    rows = db.execute(text(_INSERT.format(scope="m.id = ANY(:ids)")), {"ids": ids}).rowcount
    db.commit()
    return {"matches": len(ids), "innings": rows}


def rebuild_all(db: Session, formats: Iterable[str] = ALL_FORMATS) -> dict:
    """Full rebuild, one format at a time. Commits per format."""
    ensure_tables(db.connection())
    db.commit()
    summary = {}
    for fmt in formats:
        db.execute(text(f"DELETE FROM {TABLE} WHERE match_format = :fmt"), {"fmt": fmt})
        summary[fmt] = db.execute(text(_INSERT.format(scope="m.match_format = :fmt")), {"fmt": fmt}).rowcount
        db.commit()
        logger.info("team innings summary rebuilt for %s: %s innings", fmt, summary[fmt])
    db.execute(text(f"ANALYZE {TABLE}"))
    db.commit()
    return summary
