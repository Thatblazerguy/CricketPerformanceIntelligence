"""Canonical match registry: identity, source references, appearances and coverage.

Ball-by-ball matches are registered incrementally by the importer (one match at a
time, cheap) and in bulk by ``backfill_from_ball_by_ball`` for an existing
database. Scorecard matches are registered by the scorecard adapter through
``find_or_create_canonical`` so that a match already held ball-by-ball is linked,
not duplicated.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Dict, Iterable, List, Optional, Sequence

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.hybrid import coverage as cov
from app.hybrid.formats import from_cricsheet
from app.hybrid.identity import AMBIGUOUS, MATCHED, Decision, MatchKey, decide
from app.models.models import (
    CanonicalMatchRecord, HybridIngestionEvent, Match, MatchAppearance, MatchSourceRef,
    PlayerAlias, Provider,
)

logger = logging.getLogger(__name__)

CRICSHEET = "cricsheet"

FORMAT_CLASS_SQL = """CASE m.match_format WHEN 'Test' THEN 'TEST' WHEN 'ODI' THEN 'ODI' WHEN 'T20I' THEN 'T20I'
    WHEN 'T20' THEN 'T20_DOMESTIC' WHEN 'MDM' THEN 'MULTI_DAY' WHEN 'ODM' THEN 'ONE_DAY' ELSE upper(m.match_format) END"""


def log_event(db: Session, source_key: str, action: str, status: str, detail: str = "", **counts) -> None:
    db.add(HybridIngestionEvent(source_key=source_key, action=action, status=status, detail=detail[:4000], counts=counts))


# --------------------------------------------------------------------------- identity

def candidate_keys(db: Session, start: date, gender: str, window_days: int = 2) -> List[MatchKey]:
    rows = db.execute(select(CanonicalMatchRecord).where(
        CanonicalMatchRecord.gender == gender,
        CanonicalMatchRecord.start_date.between(start - timedelta(days=window_days), start + timedelta(days=window_days)),
    )).scalars().all()
    totals = innings_totals(db, [r.id for r in rows])
    return [MatchKey(r.start_date, r.gender, r.format_class, [r.team1_name, r.team2_name], r.venue_name,
                     r.competition_name, r.winner_name, r.result_type, totals.get(r.id, {}), r.id) for r in rows]


def innings_totals(db: Session, canonical_ids: Sequence[str]) -> Dict[str, Dict[int, int]]:
    """Innings totals per canonical match from whichever layer holds them."""
    out: Dict[str, Dict[int, int]] = {}
    if not canonical_ids:
        return out
    for cid, n, runs in db.execute(text("""
        SELECT c.id, i.innings_number, SUM(d.total_runs)
        FROM canonical_matches c JOIN match_innings i ON i.match_id = c.match_id
        JOIN deliveries d ON d.innings_id = i.id
        WHERE c.id = ANY(:ids) AND NOT i.is_super_over GROUP BY 1, 2
        UNION ALL
        SELECT s.canonical_match_id, s.innings_number, MAX(s.total_runs)
        FROM scorecard_innings s WHERE s.canonical_match_id = ANY(:ids) AND s.total_runs IS NOT NULL GROUP BY 1, 2
    """), {"ids": list(canonical_ids)}):
        out.setdefault(cid, {}).setdefault(int(n), int(runs))
    return out


def find_or_create_canonical(db: Session, key: MatchKey, *, defaults: Dict) -> tuple:
    """Return (record, Decision). Ambiguous identities create nothing and return (None, decision)."""
    decision = decide(key, candidate_keys(db, key.start_date, key.gender))
    if decision.status == MATCHED:
        return db.get(CanonicalMatchRecord, decision.canonical_id), decision
    if decision.status == AMBIGUOUS:
        return None, decision
    rec = CanonicalMatchRecord(start_date=key.start_date, gender=key.gender, format_class=key.format_class,
                               team1_name=key.teams[0], team2_name=key.teams[1], venue_name=key.venue,
                               competition_name=key.competition, winner_name=key.winner,
                               result_type=key.result_type, **defaults)
    db.add(rec)
    db.flush()
    return rec, decision


# --------------------------------------------------------------------------- ball-by-ball (incremental)

def register_ball_by_ball(db: Session, match_id: str, parsed) -> CanonicalMatchRecord:
    """Register one imported Cricsheet match. Called by MatchImporter after each import."""
    m = db.get(Match, match_id)
    rec = db.scalar(select(CanonicalMatchRecord).where(CanonicalMatchRecord.match_id == match_id))
    if rec is None:
        key = MatchKey(m.start_date, m.gender, from_cricsheet(m.match_format), list(parsed.teams), parsed.venue_name,
                       parsed.competition_name, parsed.winner, _result(parsed),
                       {i.innings_number: sum(d.total_runs for d in i.deliveries)
                        for i in parsed.innings if not i.is_super_over and i.deliveries})
        # A scorecard-only record for this match may already exist: link it rather than duplicate.
        decision = decide(key, [k for k in candidate_keys(db, key.start_date, key.gender) if not _has_bb(db, k.canonical_id)])
        if decision.status == MATCHED:
            rec = db.get(CanonicalMatchRecord, decision.canonical_id)
            log_event(db, CRICSHEET, "link_existing_canonical", "ok",
                      f"Cricsheet {parsed.source_match_id} linked to existing canonical match {rec.id}",
                      confidence=decision.confidence)
        else:
            rec = CanonicalMatchRecord(start_date=m.start_date, gender=m.gender, format_class=key.format_class,
                                       match_format=m.match_format, team1_name=parsed.teams[0], team2_name=parsed.teams[1])
            db.add(rec)
    rec.match_id = m.id
    _copy_match_fields(rec, m, parsed)
    db.flush()

    ref = db.scalar(select(MatchSourceRef).where(MatchSourceRef.source_key == CRICSHEET,
                                                 MatchSourceRef.source_match_id == parsed.source_match_id))
    evidence = {
        "forfeited_innings": [i.innings_number for i in parsed.innings if i.forfeited],
        "declared_innings": [i.innings_number for i in parsed.innings if i.declared],
        "missing_fields": list(parsed.missing_fields),
        "result_method": getattr(parsed, "result_method", None),
    }
    if ref is None:
        ref = MatchSourceRef(canonical_match_id=rec.id, source_key=CRICSHEET, source_match_id=parsed.source_match_id,
                             data_level="ball_by_ball", match_method="primary", match_confidence=1.0,
                             source_url=f"https://cricsheet.org/matches/{parsed.source_match_id}",
                             attribution="Cricsheet (ODbL 1.0)")
        db.add(ref)
    ref.canonical_match_id = rec.id
    ref.checksum = parsed.checksum
    ref.match_evidence = evidence
    ref.retrieved_at = datetime.utcnow()
    rec.missing_fields = sorted(set(parsed.missing_fields))

    provider_id = db.scalar(select(Provider.id).where(Provider.name == CRICSHEET))
    ids = {sid: pid for sid, pid in db.execute(select(PlayerAlias.source_player_id, PlayerAlias.player_id).where(
        PlayerAlias.provider_id == provider_id, PlayerAlias.source_player_id.in_(list(parsed.registry.values()))))}
    existing = set(db.scalars(select(MatchAppearance.player_id).where(MatchAppearance.canonical_match_id == rec.id)))
    for team, names in (parsed.players or {}).items():
        for name in names:
            pid = ids.get(parsed.registry.get(name))
            if pid and pid not in existing:
                db.add(MatchAppearance(canonical_match_id=rec.id, player_id=pid, team_name=team, source_key=CRICSHEET))
                existing.add(pid)
    db.flush()
    refresh_coverage(db, [rec.id])
    return rec


def _has_bb(db: Session, canonical_id: str) -> bool:
    return db.scalar(select(CanonicalMatchRecord.match_id).where(CanonicalMatchRecord.id == canonical_id)) is not None


def _result(parsed) -> Optional[str]:
    rt = getattr(parsed, "result_type", None)
    return getattr(rt, "value", rt)


def _copy_match_fields(rec: CanonicalMatchRecord, m: Match, parsed) -> None:
    rec.start_date, rec.gender, rec.match_format = m.start_date, m.gender, m.match_format
    rec.format_class = from_cricsheet(m.match_format)
    rec.season, rec.tournament_id, rec.venue_id = m.season, m.tournament_id, m.venue_id
    rec.team1_id, rec.team2_id = m.team1_id, m.team2_id
    rec.result_type = m.result_type
    rec.toss_decision = m.toss_decision
    if parsed is not None:
        rec.end_date = parsed.end_date
        rec.team1_name, rec.team2_name = parsed.teams[0], parsed.teams[1]
        rec.venue_name, rec.competition_name = parsed.venue_name, parsed.competition_name
        rec.toss_winner_name, rec.winner_name = parsed.toss_winner, parsed.winner


# --------------------------------------------------------------------------- coverage

def refresh_coverage(db: Session, canonical_ids: Optional[Sequence[str]] = None) -> Dict[str, int]:
    """Recompute coverage for the given canonical matches (all when None). Returns status counts."""
    where = "WHERE c.id = ANY(:ids)" if canonical_ids is not None else ""
    params = {"ids": list(canonical_ids)} if canonical_ids is not None else {}
    recs = db.execute(text(f"""
        SELECT c.id, c.match_id, c.format_class, c.result_type,
               (SELECT count(*) FROM match_source_refs r WHERE r.canonical_match_id = c.id) AS refs,
               (SELECT count(*) FROM scorecard_innings s WHERE s.canonical_match_id = c.id) AS sc_innings,
               (SELECT count(*) FROM scorecard_innings s WHERE s.canonical_match_id = c.id
                  AND s.validation_status = 'inconsistent') AS sc_bad,
               (SELECT count(*) FROM reconciliation_flags f WHERE f.canonical_match_id = c.id AND f.status = 'open') AS open_flags,
               (SELECT r.match_evidence FROM match_source_refs r WHERE r.canonical_match_id = c.id
                  AND r.source_key = 'cricsheet' LIMIT 1) AS bb_evidence
        FROM canonical_matches c {where}"""), params).all()
    if not recs:
        return {}
    match_ids = [r.match_id for r in recs if r.match_id]
    evidence: Dict[str, List[cov.InningsEvidence]] = {}
    for chunk in _chunks(match_ids, 2000):
        for mid, n, sup, dels, overs, max_over in db.execute(text("""
            SELECT i.match_id, i.innings_number, i.is_super_over, count(d.id),
                   count(DISTINCT d.over_number), max(d.over_number)
            FROM match_innings i LEFT JOIN deliveries d ON d.innings_id = i.id
            WHERE i.match_id = ANY(:ids) GROUP BY 1, 2, 3"""), {"ids": chunk}):
            evidence.setdefault(mid, []).append(cov.InningsEvidence(int(n), int(dels), int(overs),
                                                                    None if max_over is None else int(max_over),
                                                                    False, bool(sup)))
    now = datetime.utcnow()
    counts: Dict[str, int] = {}
    updates = []
    for r in recs:
        inns = evidence.get(r.match_id, []) if r.match_id else []
        forfeited = set((r.bb_evidence or {}).get("forfeited_innings", []))
        for i in inns:
            i.forfeited = i.innings_number in forfeited
        expected = cov.expected_innings(r.format_class, r.result_type, (r.bb_evidence or {}).get("result_method"))
        status, notes = cov.classify(inns, has_ball_by_ball_source=bool(r.match_id),
                                     has_scorecard=r.sc_innings > 0, expected=expected)
        if r.match_id is None and r.sc_innings == 0 and r.refs > 0:
            status = cov.METADATA
        if r.open_flags:
            validation = "conflict"
        elif r.sc_bad:
            validation = "inconsistent"
        elif status == cov.FULL:
            validation = "source_consistent"
        elif status == cov.SCORECARD:
            validation = "scorecard_validated"
        else:
            validation = "needs_review"
        regular = [i for i in inns if not i.is_super_over]
        updates.append({
            "id": r.id, "status": status, "notes": _json(notes), "validation": validation,
            "avail": len(regular) if r.match_id else r.sc_innings, "expected": expected,
            "dels": sum(i.deliveries for i in inns), "refs": r.refs, "now": now,
        })
        counts[status] = counts.get(status, 0) + 1
    for chunk in _chunks(updates, 5000):
        db.execute(text("""UPDATE canonical_matches SET coverage_status = :status, coverage_notes = CAST(:notes AS json),
            validation_status = :validation, innings_available = :avail, innings_expected = :expected,
            deliveries_imported = :dels, source_count = :refs, last_ingested_at = :now, updated_at = :now
            WHERE id = :id"""), chunk)
    return counts


def _json(value) -> str:
    import json
    return json.dumps(value)


def _chunks(items: Sequence, size: int) -> Iterable[Sequence]:
    for i in range(0, len(items), size):
        yield items[i:i + size]


# --------------------------------------------------------------------------- bulk backfill

def backfill_from_ball_by_ball(db: Session) -> Dict[str, int]:
    """Create canonical records + Cricsheet source refs for every ``matches`` row lacking one (pure SQL)."""
    created = db.execute(text(f"""
        INSERT INTO canonical_matches (id, match_id, start_date, gender, match_format, format_class, season,
            competition_name, tournament_id, venue_id, venue_name, country, team1_id, team2_id, team1_name, team2_name,
            toss_winner_name, toss_decision, winner_name, result_type, coverage_status, innings_available,
            deliveries_imported, source_count, missing_fields, coverage_notes, validation_status, created_at, updated_at)
        SELECT gen_random_uuid()::text, m.id, m.start_date, m.gender, m.match_format, {FORMAT_CLASS_SQL}, m.season,
            tr.name, m.tournament_id, m.venue_id, v.name, v.country, m.team1_id, m.team2_id,
            coalesce(t1.name, '?'), coalesce(t2.name, '?'), tw.name, m.toss_decision, w.name, m.result_type,
            'UNKNOWN', 0, 0, 0, '[]'::json, '[]'::json, 'unvalidated', now(), now()
        FROM matches m
        LEFT JOIN tournaments tr ON tr.id = m.tournament_id LEFT JOIN venues v ON v.id = m.venue_id
        LEFT JOIN teams t1 ON t1.id = m.team1_id LEFT JOIN teams t2 ON t2.id = m.team2_id
        LEFT JOIN teams tw ON tw.id = m.toss_winner_id LEFT JOIN teams w ON w.id = m.winner_id
        WHERE NOT EXISTS (SELECT 1 FROM canonical_matches c WHERE c.match_id = m.id)""")).rowcount
    refs = db.execute(text("""
        INSERT INTO match_source_refs (id, canonical_match_id, source_key, source_match_id, data_level, match_method,
            match_confidence, match_evidence, source_url, attribution, checksum, retrieved_at)
        SELECT gen_random_uuid()::text, c.id, p.name, m.source_match_id, 'ball_by_ball', 'primary', 1.0, '{}'::json,
            'https://cricsheet.org/matches/' || m.source_match_id, 'Cricsheet (ODbL 1.0)', m.raw_source_checksum, now()
        FROM canonical_matches c JOIN matches m ON m.id = c.match_id JOIN providers p ON p.id = m.provider_id
        ON CONFLICT (source_key, source_match_id) DO NOTHING""")).rowcount
    return {"canonical_created": created, "source_refs_created": refs}
