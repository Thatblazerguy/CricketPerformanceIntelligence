"""Data Health queries: what CPI holds, what is missing, and what needs fixing."""
from __future__ import annotations

from typing import Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.hybrid import coverage as cov
from app.hybrid import formats
from app.hybrid.identity import MATCHED, MatchKey, decide
from app.hybrid.reconstruction import COVERAGE_START_WINDOW_DAYS, RAMP_SQL, RAMP_UP_SHARE
from app.hybrid.registry import innings_totals


def _filters(f: Dict) -> tuple:
    clauses, params = [], {}
    if f.get("format_class"):
        clauses.append("c.format_class = :fc"); params["fc"] = f["format_class"]
    if f.get("gender"):
        clauses.append("c.gender = :g"); params["g"] = f["gender"]
    if f.get("season"):
        clauses.append("(c.season = :season OR extract(year FROM c.start_date)::text = :season)"); params["season"] = f["season"]
    if f.get("competition"):
        clauses.append("c.competition_name ILIKE :comp"); params["comp"] = f"%{f['competition']}%"
    if f.get("team"):
        clauses.append("(c.team1_name ILIKE :team OR c.team2_name ILIKE :team)"); params["team"] = f"%{f['team']}%"
    if f.get("player_id"):
        clauses.append("EXISTS (SELECT 1 FROM match_appearances a WHERE a.canonical_match_id = c.id AND a.player_id = :pid)")
        params["pid"] = f["player_id"]
    return (" AND ".join(clauses) or "TRUE"), params


def overview(db: Session, f: Dict) -> Dict:
    where, params = _filters(f)
    by_status = dict(db.execute(text(f"SELECT coverage_status, count(*) FROM canonical_matches c WHERE {where} GROUP BY 1"),
                                params).all())
    inv = dict(db.execute(text("SELECT status, count(*) FROM source_inventory GROUP BY 1")).all())
    last_inv = db.execute(text("""SELECT counts, created_at FROM hybrid_ingestion_events
                                  WHERE action = 'refresh_inventory' ORDER BY created_at DESC LIMIT 1""")).first()
    sync = db.execute(text("""SELECT max(last_imported_at), max(last_checked_at) FROM sync_sources""")).first()
    open_flags = db.scalar(text("SELECT count(*) FROM reconciliation_flags WHERE status = 'open'"))
    return {
        "total_matches": sum(by_status.values()),
        "by_status": {s: int(by_status.get(s, 0)) for s in cov.STATUSES},
        "labels": cov.LABELS,
        "missing_downloadable": int(inv.get("missing", 0)),
        "failed_imports": int(inv.get("failed", 0)),
        "inventory": {k: int(v) for k, v in inv.items()},
        "withheld_by_source": (last_inv.counts or {}).get("withheld_by_source") if last_inv else None,
        "inventory_refreshed_at": last_inv.created_at if last_inv else None,
        "duplicate_candidates": len(duplicate_candidates(db, limit=500)),
        "open_reconciliation_flags": int(open_flags or 0),
        "last_sync": sync[0] if sync else None,
        "last_sync_check": sync[1] if sync else None,
        "deliveries_imported": int(db.scalar(text(f"SELECT coalesce(sum(deliveries_imported), 0) FROM canonical_matches c WHERE {where}"), params) or 0),
    }


def competition_coverage(db: Session, f: Dict) -> Dict:
    where, params = _filters(f)

    def grouped(expr: str, limit: Optional[int] = None) -> List[Dict]:
        rows = db.execute(text(f"""SELECT {expr} AS k, coverage_status, count(*), min(start_date), max(start_date)
                                   FROM canonical_matches c WHERE {where} GROUP BY 1, 2"""), params).all()
        out: Dict = {}
        for k, s, n, lo, hi in rows:
            e = out.setdefault(k, {"key": k, "counts": {}, "total": 0, "first": lo, "last": hi})
            e["counts"][s] = n
            e["total"] += n
            e["first"], e["last"] = min(e["first"], lo), max(e["last"], hi)
        items = sorted(out.values(), key=lambda e: -e["total"])
        return items[:limit] if limit else items

    by_format = grouped("c.format_class")
    for e in by_format:
        e["label"] = formats.LABELS.get(e["key"], e["key"])
    return {
        "by_category": grouped("CASE WHEN c.format_class IN ('TEST','ODI','T20I') THEN 'International' "
                               "ELSE 'Domestic & franchise' END"),
        "by_format": by_format,
        "by_year": sorted(grouped("extract(year FROM c.start_date)::int"), key=lambda e: e["key"]),
        "by_country": grouped("coalesce(c.country, 'Unknown')", 40),
        "by_competition": grouped("coalesce(c.competition_name, 'Unknown')", 60),
        "source_coverage_starts": [
            {"format_class": fc, "label": formats.LABELS.get(fc, fc), "gender": g, "first": d}
            for fc, g, d in db.execute(text(f"""SELECT format_class, gender, min(start_date) FROM canonical_matches c
                                                WHERE {where} GROUP BY 1, 2 ORDER BY 1, 2"""), params)],
    }


def players_predating_records(db: Session, limit: int = 100, gender: Optional[str] = None) -> List[Dict]:
    """International players whose recorded career starts when source coverage of their team starts."""
    return [dict(r._mapping) for r in db.execute(text("""
        WITH pf AS (
            SELECT a.player_id, c.format_class, c.gender, a.team_name, min(c.start_date) AS first_record, count(*) AS n
            FROM match_appearances a JOIN canonical_matches c ON c.id = a.canonical_match_id
            WHERE c.format_class IN ('TEST', 'ODI', 'T20I') AND (CAST(:g AS text) IS NULL OR c.gender = :g)
            GROUP BY 1, 2, 3, 4
        ), tf AS (
            SELECT format_class, gender, team, min(start_date) AS team_first FROM (
                SELECT format_class, gender, team1_name AS team, start_date FROM canonical_matches
                UNION ALL SELECT format_class, gender, team2_name, start_date FROM canonical_matches) t
            GROUP BY 1, 2, 3
        ),""" + RAMP_SQL + """
        SELECT p.id AS player_id, p.canonical_name AS name, pf.format_class, pf.gender, pf.team_name AS team,
               pf.first_record, tf.team_first AS team_records_begin, pf.n AS matches_recorded
        FROM pf JOIN tf ON tf.format_class = pf.format_class AND tf.gender = pf.gender AND tf.team = pf.team_name
        JOIN ramp ON ramp.format_class = pf.format_class AND ramp.gender = pf.gender
        JOIN players p ON p.id = pf.player_id
        WHERE pf.first_record <= tf.team_first + :w AND tf.team_first <= ramp.d
        ORDER BY pf.n DESC LIMIT :lim"""), {"w": COVERAGE_START_WINDOW_DAYS, "lim": limit, "g": gender,
                                            "share": RAMP_UP_SHARE})]


def players_incomplete_ball_by_ball(db: Session, limit: int = 100) -> List[Dict]:
    return [dict(r._mapping) for r in db.execute(text("""
        SELECT p.id AS player_id, p.canonical_name AS name, count(*) AS matches,
               count(*) FILTER (WHERE c.coverage_status = 'FULL_BALL_BY_BALL') AS full,
               count(*) FILTER (WHERE c.coverage_status = 'PARTIAL_BALL_BY_BALL') AS partial,
               count(*) FILTER (WHERE c.coverage_status = 'SCORECARD_ONLY') AS scorecard_only
        FROM match_appearances a JOIN canonical_matches c ON c.id = a.canonical_match_id JOIN players p ON p.id = a.player_id
        GROUP BY 1, 2 HAVING count(*) FILTER (WHERE c.coverage_status <> 'FULL_BALL_BY_BALL') > 0
        ORDER BY count(*) FILTER (WHERE c.coverage_status <> 'FULL_BALL_BY_BALL') DESC LIMIT :lim"""), {"lim": limit})]


def players_needing_reconciliation(db: Session, limit: int = 100) -> List[Dict]:
    return [dict(r._mapping) for r in db.execute(text("""
        SELECT p.id AS player_id, p.canonical_name AS name, count(*) AS open_flags, count(DISTINCT f.canonical_match_id) AS matches
        FROM reconciliation_flags f JOIN players p ON p.id = f.player_id WHERE f.status = 'open'
        GROUP BY 1, 2 ORDER BY 3 DESC LIMIT :lim"""), {"lim": limit})]


def unresolved_identities(db: Session, limit: int = 100) -> List[Dict]:
    return [dict(r._mapping) for r in db.execute(text("""
        SELECT source_player_name AS name, count(*) AS rows FROM (
            SELECT source_player_name FROM scorecard_batting WHERE player_id IS NULL
            UNION ALL SELECT source_player_name FROM scorecard_bowling WHERE player_id IS NULL) t
        GROUP BY 1 ORDER BY 2 DESC LIMIT :lim"""), {"lim": limit})]


def duplicate_candidates(db: Session, limit: int = 200) -> List[Dict]:
    """Canonical matches the identity rules would treat as the same match. Same-day double-headers
    that innings totals or results tell apart are *not* reported."""
    pairs = db.execute(text("""
        SELECT a.id AS a, b.id AS b FROM canonical_matches a JOIN canonical_matches b
          ON a.id < b.id AND a.gender = b.gender AND a.start_date = b.start_date AND a.format_class = b.format_class
         AND least(a.team1_name, a.team2_name) = least(b.team1_name, b.team2_name)
         AND greatest(a.team1_name, a.team2_name) = greatest(b.team1_name, b.team2_name)
        LIMIT 5000""")).all()
    if not pairs:
        return []
    ids = list({x for p in pairs for x in p})
    recs = {r.id: r for r in db.execute(text("""SELECT id, start_date, gender, format_class, team1_name, team2_name,
        venue_name, competition_name, winner_name, result_type, coverage_status FROM canonical_matches WHERE id = ANY(:ids)"""),
        {"ids": ids})}
    totals = innings_totals(db, ids)

    def key(r):
        return MatchKey(r.start_date, r.gender, r.format_class, [r.team1_name, r.team2_name], r.venue_name,
                        r.competition_name, r.winner_name, r.result_type, totals.get(r.id, {}), r.id)
    out = []
    for a, b in pairs:
        d = decide(key(recs[a]), [key(recs[b])])
        if d.status == MATCHED:
            out.append({"a": a, "b": b, "date": recs[a].start_date, "teams": f"{recs[a].team1_name} v {recs[a].team2_name}",
                        "evidence": d.evidence})
            if len(out) >= limit:
                break
    return out


def double_headers(db: Session) -> int:
    """Same date/teams/format pairs that were correctly kept apart."""
    return int(db.scalar(text("""SELECT count(*) FROM canonical_matches a JOIN canonical_matches b
          ON a.id < b.id AND a.gender = b.gender AND a.start_date = b.start_date AND a.format_class = b.format_class
         AND least(a.team1_name, a.team2_name) = least(b.team1_name, b.team2_name)
         AND greatest(a.team1_name, a.team2_name) = greatest(b.team1_name, b.team2_name)""")) or 0)


def inventory_items(db: Session, status: Optional[str], limit: int = 200) -> List[Dict]:
    return [dict(r._mapping) for r in db.execute(text("""
        SELECT source_key, source_match_id, start_date, match_type, gender, teams, status, attempts, last_error, last_attempt_at
        FROM source_inventory WHERE (CAST(:s AS text) IS NULL OR status = :s) AND status <> 'imported'
        ORDER BY start_date DESC LIMIT :lim"""), {"s": status, "lim": limit})]


def flags(db: Session, status: str = "open", limit: int = 200) -> List[Dict]:
    return [dict(r._mapping) for r in db.execute(text("""
        SELECT f.id, f.canonical_match_id, f.innings_number, f.metric, f.values, f.status, f.resolution,
               p.canonical_name AS player, c.start_date, c.team1_name || ' v ' || c.team2_name AS match
        FROM reconciliation_flags f JOIN players p ON p.id = f.player_id JOIN canonical_matches c ON c.id = f.canonical_match_id
        WHERE f.status = :s ORDER BY c.start_date DESC LIMIT :lim"""), {"s": status, "lim": limit})]


def ingestion_log(db: Session, limit: int = 100) -> List[Dict]:
    hybrid = [dict(r._mapping) | {"kind": "hybrid"} for r in db.execute(text("""
        SELECT id::text, source_key, action, status, detail, counts, created_at FROM hybrid_ingestion_events
        ORDER BY created_at DESC LIMIT :lim"""), {"lim": limit})]
    sync = [dict(r._mapping) | {"kind": "cricsheet_sync"} for r in db.execute(text("""
        SELECT id::text, source_key, 'sync' AS action, status, error_detail AS detail,
               json_build_object('new', new_matches, 'updated', updated_matches, 'failed', failed_records) AS counts,
               started_at AS created_at FROM sync_history ORDER BY started_at DESC LIMIT :lim"""), {"lim": limit})]
    return sorted(hybrid + sync, key=lambda r: r["created_at"], reverse=True)[:limit]
