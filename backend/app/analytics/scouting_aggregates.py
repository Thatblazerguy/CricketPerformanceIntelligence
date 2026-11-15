"""Persisted per-innings pre-aggregations that back the scouting engine.

Scouting needs innings-level evidence (batting position, entry situation, chase
outcomes, per-innings consistency) across every player in a format. Recomputing
that from ~12M delivery rows on each request is too slow, so the derivation is
done once here and refreshed for affected matches after every import
(``app.ingestion.dependent_refresh``).

Rules applied (all consistent with ``app.domain.cricket_rules``):

* Super overs are excluded.
* Balls faced = ``is_ball_faced_by_batter`` (wides excluded, no-balls included).
* Batter dot ball = ball faced with zero batter runs.
* Boundaries = ``is_boundary_four`` / ``is_boundary_six`` on balls faced.
* Legal balls bowled = ``is_legal_ball``; runs conceded = ``bowling_runs``
  (byes/leg-byes/penalties excluded); bowler dot = legal ball with 0 bowling runs.
* Wides = deliveries not faced; no-balls = faced but not legal.
* Dismissals are attributed to ``wickets.player_out_id`` (so a non-striker run
  out is charged to the non-striker, not the striker); ``is_batter_dismissed``
  excludes retired hurt / retired not out.
* Bowler wickets use ``wickets.is_bowler_wicket``.
* Batting position = order of first appearance at the crease (striker or
  non-striker) within the innings; the striker of the first ball is #1. A
  player dismissed without reaching the crease (timed out) takes the position
  at the delivery of the dismissal.
* Pace/spin and detailed bowling style come from ``player_attributes``
  (``bowling_type`` / ``bowling_style``). Deliveries from unclassified bowlers
  are counted separately and never attributed to pace or spin.
"""
from __future__ import annotations

import logging
from typing import Iterable, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

LIMITED_OVERS = ("T20", "T20I", "ODI", "ODM")
ALL_FORMATS = ("T20", "T20I", "ODI", "ODM", "Test", "MDM")

DDL = [
    """
    CREATE TABLE IF NOT EXISTS scouting_bat_innings (
        player_id varchar(36) NOT NULL,
        innings_id varchar(36) NOT NULL,
        match_id varchar(36) NOT NULL,
        match_format varchar(32) NOT NULL,
        gender varchar(16) NOT NULL,
        start_date date NOT NULL,
        season varchar(16),
        tournament_id varchar(36),
        venue_id varchar(36),
        team_id varchar(36),
        opponent_id varchar(36),
        innings_number smallint NOT NULL,
        is_chase boolean NOT NULL DEFAULT false,
        team_won boolean,
        batting_position smallint,
        entry_wickets smallint,
        entry_over smallint,
        runs integer NOT NULL DEFAULT 0,
        balls integer NOT NULL DEFAULT 0,
        runs_sq integer NOT NULL DEFAULT 0,
        fours integer NOT NULL DEFAULT 0,
        sixes integer NOT NULL DEFAULT 0,
        dots integer NOT NULL DEFAULT 0,
        rotations integer NOT NULL DEFAULT 0,
        dismissed boolean NOT NULL DEFAULT false,
        dismissal_type varchar(64),
        pp_runs integer NOT NULL DEFAULT 0, pp_balls integer NOT NULL DEFAULT 0,
        pp_dots integer NOT NULL DEFAULT 0, pp_bnd integer NOT NULL DEFAULT 0, pp_outs integer NOT NULL DEFAULT 0,
        mid_runs integer NOT NULL DEFAULT 0, mid_balls integer NOT NULL DEFAULT 0,
        mid_dots integer NOT NULL DEFAULT 0, mid_bnd integer NOT NULL DEFAULT 0, mid_outs integer NOT NULL DEFAULT 0,
        death_runs integer NOT NULL DEFAULT 0, death_balls integer NOT NULL DEFAULT 0,
        death_dots integer NOT NULL DEFAULT 0, death_bnd integer NOT NULL DEFAULT 0, death_outs integer NOT NULL DEFAULT 0,
        pace_runs integer NOT NULL DEFAULT 0, pace_balls integer NOT NULL DEFAULT 0,
        pace_dots integer NOT NULL DEFAULT 0, pace_bnd integer NOT NULL DEFAULT 0, pace_outs integer NOT NULL DEFAULT 0,
        spin_runs integer NOT NULL DEFAULT 0, spin_balls integer NOT NULL DEFAULT 0,
        spin_dots integer NOT NULL DEFAULT 0, spin_bnd integer NOT NULL DEFAULT 0, spin_outs integer NOT NULL DEFAULT 0,
        PRIMARY KEY (innings_id, player_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_sbi_scope ON scouting_bat_innings (match_format, gender, player_id)",
    "CREATE INDEX IF NOT EXISTS ix_sbi_player ON scouting_bat_innings (player_id, start_date)",
    "CREATE INDEX IF NOT EXISTS ix_sbi_match ON scouting_bat_innings (match_id)",
    """
    CREATE TABLE IF NOT EXISTS scouting_bat_vs_style (
        player_id varchar(36) NOT NULL,
        innings_id varchar(36) NOT NULL,
        match_id varchar(36) NOT NULL,
        bowling_style varchar(64) NOT NULL,
        runs integer NOT NULL DEFAULT 0,
        balls integer NOT NULL DEFAULT 0,
        dots integer NOT NULL DEFAULT 0,
        bnd integer NOT NULL DEFAULT 0,
        outs integer NOT NULL DEFAULT 0,
        PRIMARY KEY (innings_id, player_id, bowling_style)
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_sbvs_player ON scouting_bat_vs_style (player_id)",
    "CREATE INDEX IF NOT EXISTS ix_sbvs_match ON scouting_bat_vs_style (match_id)",
    """
    CREATE TABLE IF NOT EXISTS scouting_bowl_innings (
        player_id varchar(36) NOT NULL,
        innings_id varchar(36) NOT NULL,
        match_id varchar(36) NOT NULL,
        match_format varchar(32) NOT NULL,
        gender varchar(16) NOT NULL,
        start_date date NOT NULL,
        season varchar(16),
        tournament_id varchar(36),
        venue_id varchar(36),
        team_id varchar(36),
        opponent_id varchar(36),
        innings_number smallint NOT NULL,
        is_defending boolean NOT NULL DEFAULT false,
        team_won boolean,
        legal_balls integer NOT NULL DEFAULT 0,
        runs integer NOT NULL DEFAULT 0,
        runs_sq integer NOT NULL DEFAULT 0,
        wickets integer NOT NULL DEFAULT 0,
        dots integer NOT NULL DEFAULT 0,
        fours integer NOT NULL DEFAULT 0,
        sixes integer NOT NULL DEFAULT 0,
        wides integer NOT NULL DEFAULT 0,
        noballs integer NOT NULL DEFAULT 0,
        pp_balls integer NOT NULL DEFAULT 0, pp_runs integer NOT NULL DEFAULT 0, pp_wkts integer NOT NULL DEFAULT 0,
        pp_dots integer NOT NULL DEFAULT 0, pp_bnd integer NOT NULL DEFAULT 0,
        mid_balls integer NOT NULL DEFAULT 0, mid_runs integer NOT NULL DEFAULT 0, mid_wkts integer NOT NULL DEFAULT 0,
        mid_dots integer NOT NULL DEFAULT 0, mid_bnd integer NOT NULL DEFAULT 0,
        death_balls integer NOT NULL DEFAULT 0, death_runs integer NOT NULL DEFAULT 0, death_wkts integer NOT NULL DEFAULT 0,
        death_dots integer NOT NULL DEFAULT 0, death_bnd integer NOT NULL DEFAULT 0,
        wk_bowled integer NOT NULL DEFAULT 0, wk_lbw integer NOT NULL DEFAULT 0, wk_caught integer NOT NULL DEFAULT 0,
        wk_stumped integer NOT NULL DEFAULT 0, wk_other integer NOT NULL DEFAULT 0,
        PRIMARY KEY (innings_id, player_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_sboi_scope ON scouting_bowl_innings (match_format, gender, player_id)",
    "CREATE INDEX IF NOT EXISTS ix_sboi_player ON scouting_bowl_innings (player_id, start_date)",
    "CREATE INDEX IF NOT EXISTS ix_sboi_match ON scouting_bowl_innings (match_id)",
]

TABLES = ("scouting_bat_innings", "scouting_bat_vs_style", "scouting_bowl_innings")


def ensure_tables(conn) -> None:
    for statement in DDL:
        conn.execute(text(statement))


def _scope_sql(match_ids: Optional[list], match_format: Optional[str]) -> tuple[str, dict]:
    if match_ids is not None:
        return "m.id = ANY(:match_ids)", {"match_ids": list(match_ids)}
    return "m.match_format = :fmt", {"fmt": match_format}


# Scoped deliveries enriched with match context and bowler classification. A temp
# table keeps the three derived inserts from re-reading the deliveries table.
_SCOPED = """
CREATE TEMP TABLE _scout_sd ON COMMIT DROP AS
WITH btype AS (
    SELECT DISTINCT ON (player_id) player_id, lower(attribute_value) AS btype
    FROM player_attributes WHERE attribute_type = 'bowling_type' AND lower(attribute_value) IN ('pace','spin')
    ORDER BY player_id, CASE confidence WHEN 'high' THEN 3 WHEN 'medium' THEN 2 WHEN 'low' THEN 1 ELSE 0 END DESC, updated_at DESC
), bstyle AS (
    SELECT DISTINCT ON (player_id) player_id, attribute_value AS bstyle
    FROM player_attributes WHERE attribute_type = 'bowling_style' AND attribute_value NOT ILIKE 'other%'
    ORDER BY player_id, CASE confidence WHEN 'high' THEN 3 WHEN 'medium' THEN 2 WHEN 'low' THEN 1 ELSE 0 END DESC, updated_at DESC
)
SELECT d.id, d.innings_id, mi.match_id, mi.innings_number, mi.batting_team_id,
       (d.over_number::int * 1000 + d.delivery_sequence::int) AS seq, d.over_number,
       d.batter_id, d.non_striker_id, d.bowler_id, d.batter_runs, d.bowling_runs,
       d.is_legal_ball AS legal, d.is_ball_faced_by_batter AS faced,
       (d.is_boundary_four OR d.is_boundary_six) AS bnd, d.is_boundary_four AS b4, d.is_boundary_six AS b6,
       d.phase, bt.btype, bs.bstyle
FROM deliveries d
JOIN match_innings mi ON mi.id = d.innings_id
JOIN matches m ON m.id = mi.match_id
LEFT JOIN btype bt ON bt.player_id = d.bowler_id
LEFT JOIN bstyle bs ON bs.player_id = d.bowler_id
WHERE mi.is_super_over = FALSE AND {scope}
"""

_MATCH_CTX = """
SELECT mi.id AS innings_id, m.id AS match_id, m.match_format, lower(m.gender) AS gender, m.start_date, m.season,
       m.tournament_id, m.venue_id, mi.innings_number, mi.batting_team_id,
       CASE WHEN mi.batting_team_id = m.team1_id THEN m.team2_id ELSE m.team1_id END AS fielding_team_id,
       m.winner_id,
       (m.match_format IN ('T20','T20I','ODI','ODM') AND mi.innings_number = 2) AS second_innings_limited
FROM match_innings mi JOIN matches m ON m.id = mi.match_id
WHERE mi.is_super_over = FALSE AND {scope}
"""

_BAT_INSERT = """
INSERT INTO scouting_bat_innings (
    player_id, innings_id, match_id, match_format, gender, start_date, season, tournament_id, venue_id,
    team_id, opponent_id, innings_number, is_chase, team_won, batting_position, entry_wickets, entry_over,
    runs, balls, runs_sq, fours, sixes, dots, rotations, dismissed, dismissal_type,
    pp_runs, pp_balls, pp_dots, pp_bnd, pp_outs, mid_runs, mid_balls, mid_dots, mid_bnd, mid_outs,
    death_runs, death_balls, death_dots, death_bnd, death_outs,
    pace_runs, pace_balls, pace_dots, pace_bnd, pace_outs, spin_runs, spin_balls, spin_dots, spin_bnd, spin_outs)
WITH ctx AS ({ctx}),
appear AS (
    SELECT innings_id, player_id, MIN(k) AS k FROM (
        SELECT innings_id, batter_id AS player_id, seq * 2 AS k FROM _scout_sd WHERE batter_id IS NOT NULL
        UNION ALL
        SELECT innings_id, non_striker_id, seq * 2 + 1 FROM _scout_sd WHERE non_striker_id IS NOT NULL
        UNION ALL
        -- Dismissed without ever reaching the crease (e.g. timed out): still an innings and a batting position.
        SELECT sd.innings_id, w.player_out_id, sd.seq * 2 + 1 FROM wickets w JOIN _scout_sd sd ON sd.id = w.delivery_id
        WHERE w.player_out_id IS NOT NULL
    ) a GROUP BY 1, 2
),
pos AS (
    SELECT innings_id, player_id, k, ROW_NUMBER() OVER (PARTITION BY innings_id ORDER BY k) AS position
    FROM appear
),
outs AS (
    SELECT sd.innings_id, w.player_out_id AS player_id, sd.seq, sd.phase, w.dismissal_type,
           (sd.batter_id = w.player_out_id) AS striker_out, sd.btype, w.is_batter_dismissed
    FROM wickets w JOIN _scout_sd sd ON sd.id = w.delivery_id
    WHERE w.player_out_id IS NOT NULL
),
final_out AS (
    SELECT DISTINCT ON (innings_id, player_id) innings_id, player_id, dismissal_type, phase, striker_out, btype
    FROM outs WHERE is_batter_dismissed ORDER BY innings_id, player_id, seq
),
entry AS (
    SELECT p.innings_id, p.player_id, p.position, (p.k / 2) / 1000 AS entry_over,
           COUNT(o.seq) AS entry_wickets
    FROM pos p
    LEFT JOIN outs o ON o.innings_id = p.innings_id AND o.is_batter_dismissed AND o.seq < p.k / 2
    GROUP BY p.innings_id, p.player_id, p.position, p.k
),
face AS (
    SELECT innings_id, batter_id AS player_id,
        SUM(batter_runs) AS runs,
        COUNT(*) FILTER (WHERE faced) AS balls,
        SUM(batter_runs * batter_runs) FILTER (WHERE faced) AS runs_sq,
        COUNT(*) FILTER (WHERE faced AND b4) AS fours,
        COUNT(*) FILTER (WHERE faced AND b6) AS sixes,
        COUNT(*) FILTER (WHERE faced AND batter_runs = 0) AS dots,
        COUNT(*) FILTER (WHERE faced AND batter_runs BETWEEN 1 AND 3 AND NOT bnd) AS rotations,
        SUM(batter_runs) FILTER (WHERE phase = 'powerplay') AS pp_runs,
        COUNT(*) FILTER (WHERE faced AND phase = 'powerplay') AS pp_balls,
        COUNT(*) FILTER (WHERE faced AND phase = 'powerplay' AND batter_runs = 0) AS pp_dots,
        COUNT(*) FILTER (WHERE faced AND phase = 'powerplay' AND bnd) AS pp_bnd,
        SUM(batter_runs) FILTER (WHERE phase = 'middle') AS mid_runs,
        COUNT(*) FILTER (WHERE faced AND phase = 'middle') AS mid_balls,
        COUNT(*) FILTER (WHERE faced AND phase = 'middle' AND batter_runs = 0) AS mid_dots,
        COUNT(*) FILTER (WHERE faced AND phase = 'middle' AND bnd) AS mid_bnd,
        SUM(batter_runs) FILTER (WHERE phase = 'death') AS death_runs,
        COUNT(*) FILTER (WHERE faced AND phase = 'death') AS death_balls,
        COUNT(*) FILTER (WHERE faced AND phase = 'death' AND batter_runs = 0) AS death_dots,
        COUNT(*) FILTER (WHERE faced AND phase = 'death' AND bnd) AS death_bnd,
        SUM(batter_runs) FILTER (WHERE btype = 'pace') AS pace_runs,
        COUNT(*) FILTER (WHERE faced AND btype = 'pace') AS pace_balls,
        COUNT(*) FILTER (WHERE faced AND btype = 'pace' AND batter_runs = 0) AS pace_dots,
        COUNT(*) FILTER (WHERE faced AND btype = 'pace' AND bnd) AS pace_bnd,
        SUM(batter_runs) FILTER (WHERE btype = 'spin') AS spin_runs,
        COUNT(*) FILTER (WHERE faced AND btype = 'spin') AS spin_balls,
        COUNT(*) FILTER (WHERE faced AND btype = 'spin' AND batter_runs = 0) AS spin_dots,
        COUNT(*) FILTER (WHERE faced AND btype = 'spin' AND bnd) AS spin_bnd
    FROM _scout_sd WHERE batter_id IS NOT NULL GROUP BY 1, 2
),
phase_outs AS (
    SELECT innings_id, player_id,
        COUNT(*) FILTER (WHERE phase = 'powerplay') AS pp_outs,
        COUNT(*) FILTER (WHERE phase = 'middle') AS mid_outs,
        COUNT(*) FILTER (WHERE phase = 'death') AS death_outs,
        COUNT(*) FILTER (WHERE striker_out AND btype = 'pace') AS pace_outs,
        COUNT(*) FILTER (WHERE striker_out AND btype = 'spin') AS spin_outs
    FROM outs WHERE is_batter_dismissed GROUP BY 1, 2
)
SELECT e.player_id, e.innings_id, c.match_id, c.match_format, c.gender, c.start_date, c.season, c.tournament_id, c.venue_id,
       c.batting_team_id, c.fielding_team_id, c.innings_number, c.second_innings_limited,
       CASE WHEN c.winner_id IS NULL THEN NULL ELSE c.winner_id = c.batting_team_id END,
       e.position, e.entry_wickets, e.entry_over,
       COALESCE(f.runs, 0), COALESCE(f.balls, 0), COALESCE(f.runs_sq, 0), COALESCE(f.fours, 0), COALESCE(f.sixes, 0),
       COALESCE(f.dots, 0), COALESCE(f.rotations, 0), (fo.player_id IS NOT NULL), fo.dismissal_type,
       COALESCE(f.pp_runs, 0), COALESCE(f.pp_balls, 0), COALESCE(f.pp_dots, 0), COALESCE(f.pp_bnd, 0), COALESCE(po.pp_outs, 0),
       COALESCE(f.mid_runs, 0), COALESCE(f.mid_balls, 0), COALESCE(f.mid_dots, 0), COALESCE(f.mid_bnd, 0), COALESCE(po.mid_outs, 0),
       COALESCE(f.death_runs, 0), COALESCE(f.death_balls, 0), COALESCE(f.death_dots, 0), COALESCE(f.death_bnd, 0), COALESCE(po.death_outs, 0),
       COALESCE(f.pace_runs, 0), COALESCE(f.pace_balls, 0), COALESCE(f.pace_dots, 0), COALESCE(f.pace_bnd, 0), COALESCE(po.pace_outs, 0),
       COALESCE(f.spin_runs, 0), COALESCE(f.spin_balls, 0), COALESCE(f.spin_dots, 0), COALESCE(f.spin_bnd, 0), COALESCE(po.spin_outs, 0)
FROM entry e
JOIN ctx c ON c.innings_id = e.innings_id
LEFT JOIN face f ON f.innings_id = e.innings_id AND f.player_id = e.player_id
LEFT JOIN final_out fo ON fo.innings_id = e.innings_id AND fo.player_id = e.player_id
LEFT JOIN phase_outs po ON po.innings_id = e.innings_id AND po.player_id = e.player_id
"""

_STYLE_INSERT = """
INSERT INTO scouting_bat_vs_style (player_id, innings_id, match_id, bowling_style, runs, balls, dots, bnd, outs)
SELECT sd.batter_id, sd.innings_id, MIN(sd.match_id), sd.bstyle,
       SUM(sd.batter_runs), COUNT(*) FILTER (WHERE sd.faced),
       COUNT(*) FILTER (WHERE sd.faced AND sd.batter_runs = 0),
       COUNT(*) FILTER (WHERE sd.faced AND sd.bnd),
       COUNT(w.id)
FROM _scout_sd sd
LEFT JOIN wickets w ON w.delivery_id = sd.id AND w.player_out_id = sd.batter_id AND w.is_batter_dismissed
WHERE sd.batter_id IS NOT NULL AND sd.bstyle IS NOT NULL
GROUP BY sd.batter_id, sd.innings_id, sd.bstyle
"""

_BOWL_INSERT = """
INSERT INTO scouting_bowl_innings (
    player_id, innings_id, match_id, match_format, gender, start_date, season, tournament_id, venue_id,
    team_id, opponent_id, innings_number, is_defending, team_won,
    legal_balls, runs, runs_sq, wickets, dots, fours, sixes, wides, noballs,
    pp_balls, pp_runs, pp_wkts, pp_dots, pp_bnd, mid_balls, mid_runs, mid_wkts, mid_dots, mid_bnd,
    death_balls, death_runs, death_wkts, death_dots, death_bnd,
    wk_bowled, wk_lbw, wk_caught, wk_stumped, wk_other)
WITH ctx AS ({ctx}),
wk AS (
    SELECT sd.id AS delivery_id,
        COUNT(*) AS wkts,
        COUNT(*) FILTER (WHERE w.dismissal_type = 'bowled') AS bowled,
        COUNT(*) FILTER (WHERE w.dismissal_type = 'lbw') AS lbw,
        COUNT(*) FILTER (WHERE w.dismissal_type IN ('caught', 'caught and bowled')) AS caught,
        COUNT(*) FILTER (WHERE w.dismissal_type = 'stumped') AS stumped
    FROM wickets w JOIN _scout_sd sd ON sd.id = w.delivery_id
    WHERE w.is_bowler_wicket
    GROUP BY sd.id
),
agg AS (
    SELECT sd.innings_id, sd.bowler_id AS player_id,
        COUNT(*) FILTER (WHERE sd.legal) AS legal_balls,
        SUM(sd.bowling_runs) AS runs,
        SUM(sd.bowling_runs * sd.bowling_runs) AS runs_sq,
        COALESCE(SUM(wk.wkts), 0) AS wickets,
        COUNT(*) FILTER (WHERE sd.legal AND sd.bowling_runs = 0) AS dots,
        COUNT(*) FILTER (WHERE sd.faced AND sd.b4) AS fours,
        COUNT(*) FILTER (WHERE sd.faced AND sd.b6) AS sixes,
        COUNT(*) FILTER (WHERE NOT sd.faced) AS wides,
        COUNT(*) FILTER (WHERE sd.faced AND NOT sd.legal) AS noballs,
        COUNT(*) FILTER (WHERE sd.legal AND sd.phase = 'powerplay') AS pp_balls,
        COALESCE(SUM(sd.bowling_runs) FILTER (WHERE sd.phase = 'powerplay'), 0) AS pp_runs,
        COALESCE(SUM(wk.wkts) FILTER (WHERE sd.phase = 'powerplay'), 0) AS pp_wkts,
        COUNT(*) FILTER (WHERE sd.legal AND sd.phase = 'powerplay' AND sd.bowling_runs = 0) AS pp_dots,
        COUNT(*) FILTER (WHERE sd.faced AND sd.phase = 'powerplay' AND sd.bnd) AS pp_bnd,
        COUNT(*) FILTER (WHERE sd.legal AND sd.phase = 'middle') AS mid_balls,
        COALESCE(SUM(sd.bowling_runs) FILTER (WHERE sd.phase = 'middle'), 0) AS mid_runs,
        COALESCE(SUM(wk.wkts) FILTER (WHERE sd.phase = 'middle'), 0) AS mid_wkts,
        COUNT(*) FILTER (WHERE sd.legal AND sd.phase = 'middle' AND sd.bowling_runs = 0) AS mid_dots,
        COUNT(*) FILTER (WHERE sd.faced AND sd.phase = 'middle' AND sd.bnd) AS mid_bnd,
        COUNT(*) FILTER (WHERE sd.legal AND sd.phase = 'death') AS death_balls,
        COALESCE(SUM(sd.bowling_runs) FILTER (WHERE sd.phase = 'death'), 0) AS death_runs,
        COALESCE(SUM(wk.wkts) FILTER (WHERE sd.phase = 'death'), 0) AS death_wkts,
        COUNT(*) FILTER (WHERE sd.legal AND sd.phase = 'death' AND sd.bowling_runs = 0) AS death_dots,
        COUNT(*) FILTER (WHERE sd.faced AND sd.phase = 'death' AND sd.bnd) AS death_bnd,
        COALESCE(SUM(wk.bowled), 0) AS wk_bowled, COALESCE(SUM(wk.lbw), 0) AS wk_lbw,
        COALESCE(SUM(wk.caught), 0) AS wk_caught, COALESCE(SUM(wk.stumped), 0) AS wk_stumped
    FROM _scout_sd sd LEFT JOIN wk ON wk.delivery_id = sd.id
    WHERE sd.bowler_id IS NOT NULL
    GROUP BY sd.innings_id, sd.bowler_id
)
SELECT a.player_id, a.innings_id, c.match_id, c.match_format, c.gender, c.start_date, c.season, c.tournament_id, c.venue_id,
       c.fielding_team_id, c.batting_team_id, c.innings_number, c.second_innings_limited,
       CASE WHEN c.winner_id IS NULL THEN NULL ELSE c.winner_id = c.fielding_team_id END,
       a.legal_balls, a.runs, a.runs_sq, a.wickets, a.dots, a.fours, a.sixes, a.wides, a.noballs,
       a.pp_balls, a.pp_runs, a.pp_wkts, a.pp_dots, a.pp_bnd, a.mid_balls, a.mid_runs, a.mid_wkts, a.mid_dots, a.mid_bnd,
       a.death_balls, a.death_runs, a.death_wkts, a.death_dots, a.death_bnd,
       a.wk_bowled, a.wk_lbw, a.wk_caught, a.wk_stumped,
       a.wickets - a.wk_bowled - a.wk_lbw - a.wk_caught - a.wk_stumped
FROM agg a JOIN ctx c ON c.innings_id = a.innings_id
"""


def _rebuild_scope(db: Session, scope: str, params: dict) -> dict:
    db.execute(text("DROP TABLE IF EXISTS _scout_sd"))
    db.execute(text(_SCOPED.format(scope=scope)), params)
    db.execute(text("CREATE INDEX ON _scout_sd (id)"))
    db.execute(text("ANALYZE _scout_sd"))
    ctx = _MATCH_CTX.format(scope=scope)
    counts = {}
    counts["bat"] = db.execute(text(_BAT_INSERT.format(ctx=ctx)), params).rowcount
    counts["style"] = db.execute(text(_STYLE_INSERT), params).rowcount
    counts["bowl"] = db.execute(text(_BOWL_INSERT.format(ctx=ctx)), params).rowcount
    db.execute(text("DROP TABLE IF EXISTS _scout_sd"))
    return counts


def tables_exist(db: Session) -> bool:
    return bool(db.execute(text("SELECT to_regclass('public.scouting_bat_innings') IS NOT NULL")).scalar())


def rebuild_for_matches(db: Session, match_ids: Iterable[str]) -> dict:
    """Delete and rebuild aggregates for specific matches (incremental refresh). Commits."""
    ids = [m for m in set(match_ids) if m]
    if not ids or not tables_exist(db):
        return {"matches": 0}
    for table in TABLES:
        db.execute(text(f"DELETE FROM {table} WHERE match_id = ANY(:ids)"), {"ids": ids})
    counts = _rebuild_scope(db, *_scope_sql(ids, None))
    db.commit()
    return {"matches": len(ids), **counts}


def rebuild_all(db: Session, formats: Iterable[str] = ALL_FORMATS) -> dict:
    """Full rebuild, one format at a time to bound temp-table size. Commits per format."""
    ensure_tables(db.connection())
    db.commit()
    summary = {}
    for fmt in formats:
        db.execute(text("DELETE FROM scouting_bat_vs_style s USING matches m WHERE m.id = s.match_id AND m.match_format = :fmt"), {"fmt": fmt})
        db.execute(text("DELETE FROM scouting_bat_innings WHERE match_format = :fmt"), {"fmt": fmt})
        db.execute(text("DELETE FROM scouting_bowl_innings WHERE match_format = :fmt"), {"fmt": fmt})
        summary[fmt] = _rebuild_scope(db, *_scope_sql(None, fmt))
        db.commit()
        logger.info("scouting aggregates rebuilt for %s: %s", fmt, summary[fmt])
    for table in TABLES:
        db.execute(text(f"ANALYZE {table}"))
    db.commit()
    return summary
