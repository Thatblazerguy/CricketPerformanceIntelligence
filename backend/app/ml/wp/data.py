"""Read CPI's already-ingested Cricsheet tables into pandas frames.

Nothing here re-ingests data: it only reads ``matches``, ``match_innings``,
``deliveries`` and ``wickets``. Large delivery extracts are streamed with
PostgreSQL ``COPY`` and cached as parquet keyed by a data fingerprint so
repeat training runs are reproducible and fast.
"""
from __future__ import annotations

import hashlib
import io
from pathlib import Path
from typing import Iterable, Optional

import pandas as pd
from sqlalchemy import text

MATCH_COLUMNS = (
    "m.id AS match_id, m.start_date, m.gender, m.match_format, m.venue_id, m.tournament_id, "
    "m.team1_id, m.team2_id, m.toss_winner_id, m.toss_decision, m.winner_id, m.result_type"
)


def _copy_frame(db, sql: str, params: Optional[dict] = None, dtype=None) -> pd.DataFrame:
    """Run ``COPY (sql) TO STDOUT`` for speed; ``params`` are bound safely first."""
    conn = db.connection().connection  # DBAPI (psycopg3) connection
    with conn.cursor() as cur:
        buf = io.BytesIO()
        # psycopg3 binds COPY parameters client-side (COPY has no server-side params).
        with cur.copy(f"COPY ({sql}) TO STDOUT WITH CSV HEADER", params or None) as copy:
            for chunk in copy:
                buf.write(chunk)
    buf.seek(0)
    return pd.read_csv(buf, dtype=dtype)


def data_fingerprint(db) -> str:
    row = db.execute(text(
        "SELECT count(*), coalesce(max(updated_at)::text,''), coalesce(max(source_data_version)::text,'') FROM matches"
    )).one()
    deliveries = db.execute(text("SELECT reltuples::bigint FROM pg_class WHERE relname='deliveries'")).scalar()
    return hashlib.sha1(f"{row[0]}|{row[1]}|{row[2]}|{deliveries}".encode()).hexdigest()[:12]


def load_matches(db) -> pd.DataFrame:
    frame = _copy_frame(db, f"SELECT {MATCH_COLUMNS} FROM matches m ORDER BY m.start_date, m.id")
    frame["start_date"] = pd.to_datetime(frame["start_date"])
    return frame


def load_innings_summary(db) -> pd.DataFrame:
    """One row per innings with totals; super overs flagged, never mixed into totals."""
    frame = _copy_frame(db, """
        SELECT i.id AS innings_id, i.match_id, i.innings_number, i.batting_team_id, i.target_runs,
               i.target_overs, i.is_super_over::int AS is_super_over,
               coalesce(sum(d.total_runs),0) AS runs,
               coalesce(sum(d.is_legal_ball::int),0) AS legal_balls,
               coalesce(sum(w.n),0) AS wickets
        FROM match_innings i
        LEFT JOIN deliveries d ON d.innings_id = i.id
        LEFT JOIN (SELECT delivery_id, count(*) FILTER (WHERE is_batter_dismissed) AS n
                   FROM wickets GROUP BY delivery_id) w ON w.delivery_id = d.id
        GROUP BY i.id, i.match_id, i.innings_number, i.batting_team_id, i.target_runs, i.target_overs, i.is_super_over
    """)
    return frame


def load_deliveries(db, formats: Iterable[str], cache_dir: Optional[Path] = None,
                    match_ids: Optional[Iterable[str]] = None) -> pd.DataFrame:
    """Regulation-innings deliveries in playing order for the given source formats.

    ``match_ids`` restricts the extract (incremental refresh); subsets are never cached.
    """
    formats = sorted(formats)
    cache = None
    if match_ids is not None:
        cache_dir = None
    if cache_dir is not None:
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache = cache_dir / f"deliveries_{'_'.join(formats)}_{data_fingerprint(db)}.parquet"
        if cache.exists():
            return pd.read_parquet(cache)
    frame = _copy_frame(db, """
        SELECT d.innings_id, d.over_number, d.delivery_sequence,
               d.batter_id, d.bowler_id, d.total_runs, d.is_legal_ball::int AS legal,
               (d.is_boundary_four::int + 2 * d.is_boundary_six::int) AS boundary,
               coalesce(w.n, 0) AS wickets
        FROM deliveries d
        JOIN match_innings i ON i.id = d.innings_id
        JOIN matches m ON m.id = i.match_id
        LEFT JOIN (SELECT delivery_id, count(*) FILTER (WHERE is_batter_dismissed) AS n
                   FROM wickets GROUP BY delivery_id) w ON w.delivery_id = d.id
        WHERE m.match_format = ANY(%(formats)s) AND NOT i.is_super_over
          {subset}
        ORDER BY d.innings_id, d.over_number, d.delivery_sequence
    """.replace("{subset}", "AND m.id = ANY(%(match_ids)s)" if match_ids is not None else ""),
        {"formats": formats, **({"match_ids": list(match_ids)} if match_ids is not None else {})}, dtype={"innings_id": "category", "batter_id": "category", "bowler_id": "category"})
    for column in ("over_number", "delivery_sequence", "total_runs", "legal", "boundary", "wickets"):
        frame[column] = frame[column].astype("int32")
    if cache is not None:
        for stale in cache_dir.glob(f"deliveries_{'_'.join(formats)}_*.parquet"):
            stale.unlink()
        frame.to_parquet(cache, index=False)
    return frame
