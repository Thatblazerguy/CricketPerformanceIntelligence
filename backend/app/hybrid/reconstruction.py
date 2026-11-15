"""Historical player reconstruction and coverage reporting.

Everything here is derived from stored records. Benchmark totals from outside
CPI are used only by the validation script, to measure the remaining gap.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.hybrid import coverage as cov
from app.hybrid import formats
from app.hybrid.career import player_career

# A player whose first record falls within this many days of their team's first
# record in a format, where that team's records begin during the source's
# ramp-up period, may well have played before records begin.
COVERAGE_START_WINDOW_DAYS = 400
# Ramp-up ends in the first year a format/gender reaches this share of its median
# annual match volume (data-derived: Cricsheet's early years are sparse).
RAMP_UP_SHARE = 0.6

RAMP_SQL = """
    yearly AS (
        SELECT format_class, gender, extract(year FROM start_date)::int AS yr, count(*) AS n
        FROM canonical_matches GROUP BY 1, 2, 3
    ), med AS (
        SELECT format_class, gender, percentile_cont(0.5) WITHIN GROUP (ORDER BY n) AS m FROM yearly GROUP BY 1, 2
    ), ramp AS (
        SELECT y.format_class, y.gender, make_date(min(y.yr), 12, 31) AS d
        FROM yearly y JOIN med ON med.format_class = y.format_class AND med.gender = y.gender
        WHERE y.n >= :share * med.m GROUP BY 1, 2
    )"""


def coverage_floors(db: Session) -> Dict[tuple, object]:
    return {(fc, g): d for fc, g, d in db.execute(text(
        "SELECT format_class, gender, min(start_date) FROM canonical_matches GROUP BY 1, 2"))}


def left_censored_formats(db: Session, player_id: str) -> List[Dict]:
    """Formats in which the player's recorded career starts when the source's coverage starts."""
    rows = db.execute(text("""
        WITH pf AS (
            SELECT c.format_class, c.gender, a.team_name, min(c.start_date) AS first_record, count(*) AS n
            FROM match_appearances a JOIN canonical_matches c ON c.id = a.canonical_match_id
            WHERE a.player_id = :p GROUP BY 1, 2, 3
        ), tf AS (
            SELECT format_class, gender, team, min(start_date) AS team_first FROM (
                SELECT format_class, gender, team1_name AS team, start_date FROM canonical_matches
                UNION ALL SELECT format_class, gender, team2_name, start_date FROM canonical_matches) t
            GROUP BY 1, 2, 3
        ), floor AS (SELECT format_class, gender, min(start_date) AS d FROM canonical_matches GROUP BY 1, 2),
        """ + RAMP_SQL + """
        SELECT pf.format_class, pf.gender, pf.team_name, pf.first_record, pf.n, tf.team_first, floor.d AS source_first,
               ramp.d AS ramp_up_end
        FROM pf JOIN tf ON tf.format_class = pf.format_class AND tf.gender = pf.gender AND tf.team = pf.team_name
        JOIN floor ON floor.format_class = pf.format_class AND floor.gender = pf.gender
        JOIN ramp ON ramp.format_class = pf.format_class AND ramp.gender = pf.gender
        WHERE pf.first_record <= tf.team_first + :w AND tf.team_first <= ramp.d"""),
        {"p": player_id, "w": COVERAGE_START_WINDOW_DAYS, "share": RAMP_UP_SHARE}).all()
    return [{"format_class": r.format_class, "label": formats.LABELS.get(r.format_class, r.format_class),
             "team": r.team_name, "first_record": r.first_record, "team_records_begin": r.team_first,
             "source_records_begin": r.source_first, "matches_recorded": r.n, "source_ramp_up_end": r.ramp_up_end,
             "message": f"First {formats.LABELS.get(r.format_class, r.format_class)} record for {r.team_name} is "
                        f"{r.first_record}, within {COVERAGE_START_WINDOW_DAYS} days of when available records for "
                        f"that team begin ({r.team_first}), during the period when source coverage of this format was "
                        f"still sparse (until {r.ramp_up_end.year}). Earlier and in-period matches are likely missing "
                        f"from every integrated source, so career totals in this format are probably incomplete."}
            for r in rows]


def team_year_gaps(db: Session, player_id: str) -> List[Dict]:
    """Years inside the player's recorded span in which their team has no record at all in that format."""
    spans = db.execute(text("""
        SELECT c.format_class, c.gender, a.team_name, min(c.start_date) AS f, max(c.start_date) AS l
        FROM match_appearances a JOIN canonical_matches c ON c.id = a.canonical_match_id
        WHERE a.player_id = :p AND c.format_class IN ('TEST', 'ODI', 'T20I') GROUP BY 1, 2, 3"""), {"p": player_id}).all()
    gaps = []
    for s in spans:
        years = {int(y) for (y,) in db.execute(text("""
            SELECT DISTINCT extract(year FROM start_date) FROM canonical_matches
            WHERE format_class = :fc AND gender = :g AND (team1_name = :t OR team2_name = :t)
              AND start_date BETWEEN :f AND :l"""), {"fc": s.format_class, "g": s.gender, "t": s.team_name,
                                                    "f": s.f, "l": s.l})}
        missing = [y for y in range(s.f.year, s.l.year + 1) if y not in years]
        if missing:
            gaps.append({"format_class": s.format_class, "team": s.team_name, "years_without_team_records": missing})
    return gaps


def player_coverage(db: Session, player_id: str) -> Dict:
    rows = db.execute(text("""
        SELECT c.id, c.format_class, c.coverage_status, c.start_date, c.competition_name, c.gender
        FROM match_appearances a JOIN canonical_matches c ON c.id = a.canonical_match_id
        WHERE a.player_id = :p ORDER BY c.start_date"""), {"p": player_id}).all()
    by_status, by_format, by_comp, by_year = defaultdict(int), defaultdict(lambda: defaultdict(int)), \
        defaultdict(lambda: defaultdict(int)), defaultdict(lambda: defaultdict(int))
    for r in rows:
        by_status[r.coverage_status] += 1
        by_format[r.format_class][r.coverage_status] += 1
        by_comp[r.competition_name or "Unknown"][r.coverage_status] += 1
        by_year[r.start_date.year][r.coverage_status] += 1
    last_sync = db.scalar(text("SELECT max(last_imported_at) FROM sync_sources"))
    last_scorecard = db.scalar(text("""SELECT max(created_at) FROM hybrid_ingestion_events
                                       WHERE action = 'import_scorecards' AND status IN ('ok', 'partial')"""))
    full = by_status.get(cov.FULL, 0)
    return {
        "player_id": player_id,
        "total_matches": len(rows),
        "verified_matches": sum(v for k, v in by_status.items() if k in (cov.FULL, cov.PARTIAL, cov.SCORECARD)),
        "by_status": dict(by_status),
        "labels": cov.LABELS,
        "by_format": [{"format_class": f, "label": formats.LABELS.get(f, f), "counts": dict(c),
                       "total": sum(c.values())} for f, c in sorted(by_format.items(), key=lambda x: -sum(x[1].values()))],
        "by_competition": [{"competition": k, "counts": dict(c), "total": sum(c.values())}
                           for k, c in sorted(by_comp.items(), key=lambda x: -sum(x[1].values()))[:25]],
        "by_year": [{"year": y, "counts": dict(c), "total": sum(c.values())} for y, c in sorted(by_year.items())],
        "earliest_record": rows[0].start_date if rows else None,
        "latest_record": rows[-1].start_date if rows else None,
        "last_ball_by_ball_sync": last_sync,
        "last_scorecard_import": last_scorecard,
        "analytics_basis": {
            "ball_by_ball_matches": full,
            "statement": f"Delivery-level analytics (matchups, phases, boundary and dismissal patterns) are based on "
                         f"{full} ball-by-ball match{'es' if full != 1 else ''}"
                         + (f" of {len(rows)} recorded." if len(rows) != full else "."),
        },
        "career_predates_records": left_censored_formats(db, player_id),
    }


def reconstruct_player(db: Session, player_id: str) -> Dict:
    """Full reconstruction: appearances, reconciled career totals and known gaps."""
    return {
        "coverage": player_coverage(db, player_id),
        "career": player_career(db, player_id),
        "team_year_gaps": team_year_gaps(db, player_id),
        "notes": [
            "Totals are derived only from stored ball-by-ball and verified scorecard records.",
            "Each innings is counted once even when several sources hold it.",
            "Cricsheet withholds matches involving Afghanistan men; such matches cannot appear here.",
        ],
    }
