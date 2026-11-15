"""Hybrid data engine against a real (throwaway) PostgreSQL database.

Imports the Cricsheet fixtures through the normal importer, then exercises the
scorecard layer, cross-source matching, reconciliation, coverage, identity
resolution, inventory comparison and layer isolation. Scorecards are built in
the test from the fixture match itself (same match, second "source"), or are
synthetic fixtures with invented teams; no real player totals are encoded.
"""
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.db.base import Base
from app.hybrid import coverage as cov
from app.hybrid.career import player_career
from app.hybrid.people import NAME_TEAM, RESOLVED, UNRESOLVED, resolve_player
from app.hybrid.registry import refresh_coverage
from app.hybrid.sources.cricsheet_inventory import CricsheetInventoryAdapter
from app.hybrid.sources.scorecard_file import ScorecardBundleError, ScorecardFileAdapter
from app.ingestion.importer import MatchImporter
from app.ingestion.providers.cricsheet import CricsheetParser
from app.models.models import (
    CanonicalMatchRecord, Delivery, Match, MatchAppearance, MatchSourceRef, Player, ReconciliationFlag,
    SourceInventoryItem,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "cricsheet"
SRC = {"key": "test_archive", "name": "Test archive", "licence": "Test fixture, no real data"}


@pytest.fixture(scope="module")
def engine():
    url = make_url(settings.DATABASE_URL)
    test_db = f"{url.database}_hybrid_test"
    try:
        admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{test_db}" WITH (FORCE)'))
            conn.execute(text(f'CREATE DATABASE "{test_db}"'))
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Cannot create test database: {exc}")
    eng = create_engine(url.set(database=test_db))
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{test_db}" WITH (FORCE)'))


@pytest.fixture(scope="module")
def db(engine):
    session = sessionmaker(bind=engine)()
    parser, importer = CricsheetParser(), MatchImporter(session)
    for f in sorted(FIXTURES.glob("*.json")):
        importer.import_match(parser.parse_file(f)[0])
    session.commit()
    yield session
    session.close()


def canonical_for(db, source_match_id):
    return db.scalar(select(CanonicalMatchRecord).join(MatchSourceRef, MatchSourceRef.canonical_match_id == CanonicalMatchRecord.id)
                     .where(MatchSourceRef.source_key == "cricsheet", MatchSourceRef.source_match_id == source_match_id))


def scorecard_from_ball_by_ball(db, rec, *, runs_delta=None):
    """Build a scorecard bundle for the same match from the fixture's own deliveries."""
    rows = db.execute(text("""
        SELECT i.innings_number, t.name AS team, p.canonical_name AS name, pa.source_player_id AS sid,
               sum(d.batter_runs) AS runs, count(*) FILTER (WHERE d.is_ball_faced_by_batter) AS balls,
               bool_or(EXISTS (SELECT 1 FROM wickets w WHERE w.delivery_id = d.id AND w.player_out_id = d.batter_id)) AS out
        FROM deliveries d JOIN match_innings i ON i.id = d.innings_id JOIN teams t ON t.id = i.batting_team_id
        JOIN players p ON p.id = d.batter_id JOIN player_aliases pa ON pa.player_id = p.id
        WHERE i.match_id = :m AND NOT i.is_super_over GROUP BY 1, 2, 3, 4 ORDER BY 1"""), {"m": rec.match_id}).all()
    totals = dict(db.execute(text("""SELECT i.innings_number, sum(d.total_runs) FROM deliveries d
        JOIN match_innings i ON i.id = d.innings_id WHERE i.match_id = :m GROUP BY 1"""), {"m": rec.match_id}).all())
    innings = {}
    for r in rows:
        inn = innings.setdefault(r.innings_number, {"number": r.innings_number, "team": r.team,
                                                    "total": int(totals[r.innings_number]), "batting": []})
        runs = int(r.runs) + (runs_delta.get(r.name, 0) if runs_delta else 0)
        inn["batting"].append({"name": r.name, "id": f"cricsheet:{r.sid}", "runs": runs, "balls": int(r.balls),
                               "out": bool(r.out)})
    return {"source": SRC, "matches": [{
        "source_match_id": f"T-{rec.id[:8]}", "start_date": rec.start_date.isoformat(), "gender": rec.gender,
        "format_class": rec.format_class, "teams": [rec.team1_name, rec.team2_name], "venue": rec.venue_name,
        "competition": rec.competition_name, "result": {"type": rec.result_type, "winner": rec.winner_name},
        "innings": list(innings.values())}]}


# 10. provenance / coverage for ball-by-ball imports -----------------------------------------

def test_import_registers_canonical_matches_with_coverage(db):
    assert db.scalar(select(func.count()).select_from(CanonicalMatchRecord)) == 3
    for rec in db.scalars(select(CanonicalMatchRecord)):
        assert rec.coverage_status == cov.FULL and rec.match_id is not None
        ref = db.scalar(select(MatchSourceRef).where(MatchSourceRef.canonical_match_id == rec.id))
        assert ref.source_key == "cricsheet" and ref.data_level == "ball_by_ball"
        assert db.scalar(select(func.count()).select_from(MatchAppearance)
                         .where(MatchAppearance.canonical_match_id == rec.id)) == 22


# 1. duplicate detection: re-importing never duplicates ---------------------------------------

def test_reimport_is_idempotent(db):
    MatchImporter(db).import_match(CricsheetParser().parse_file(FIXTURES / "829807.json")[0], force=True)
    db.commit()
    assert db.scalar(select(func.count()).select_from(CanonicalMatchRecord)) == 3
    assert db.scalar(select(func.count()).select_from(MatchSourceRef)) == 3


# 2. cross-source matching / 3. reconciliation / 4. aggregation / 9. identity ------------------

def test_scorecard_for_same_match_links_and_counts_once(db):
    rec = canonical_for(db, "1259551")
    report = ScorecardFileAdapter().import_bundle(db, scorecard_from_ball_by_ball(db, rec))
    db.commit()
    assert report.linked_to_existing == 1 and report.created == 0 and not report.rejected
    assert db.scalar(select(func.count()).select_from(CanonicalMatchRecord)) == 3
    db.refresh(rec)
    assert rec.coverage_status == cov.FULL and rec.source_count == 2

    batter = db.execute(text("""SELECT b.player_id, b.runs FROM scorecard_batting b
        WHERE b.canonical_match_id = :c AND b.runs > 0 ORDER BY b.runs DESC LIMIT 1"""), {"c": rec.id}).first()
    career = player_career(db, batter.player_id)
    fmt = career["formats"]["T20_DOMESTIC"]
    bb_only = db.scalar(text("""SELECT sum(d.batter_runs) FROM deliveries d JOIN match_innings i ON i.id = d.innings_id
        JOIN matches m ON m.id = i.match_id WHERE d.batter_id = :p AND NOT i.is_super_over"""), {"p": batter.player_id})
    assert fmt["batting"]["runs"]["value"] == bb_only           # not doubled
    assert fmt["provenance"]["batting"].get("both_agree") == 1
    assert not career["conflicts"]


def test_disagreement_is_flagged_not_silently_chosen(db):
    rec = canonical_for(db, "1182656")
    top = db.execute(text("""SELECT p.canonical_name, p.id FROM deliveries d JOIN match_innings i ON i.id = d.innings_id
        JOIN players p ON p.id = d.batter_id WHERE i.match_id = :m GROUP BY 1, 2 ORDER BY sum(d.batter_runs) DESC LIMIT 1"""),
        {"m": rec.match_id}).first()
    bundle = scorecard_from_ball_by_ball(db, rec, runs_delta={top.canonical_name: 2})
    for inn in bundle["matches"][0]["innings"]:
        inn.pop("total")          # keep the identity on dates/teams/venue; the altered total must not block linking
    ScorecardFileAdapter().import_bundle(db, bundle)
    db.commit()
    flag = db.scalar(select(ReconciliationFlag).where(ReconciliationFlag.player_id == top.id,
                                                      ReconciliationFlag.metric == "runs"))
    assert flag is not None and flag.status == "open"
    assert len(set(flag.values.values())) == 2 and set(flag.values) == {"cricsheet", "test_archive"}
    assert "complete_ball_by_ball_precedence" in flag.resolution
    db.refresh(rec)
    assert rec.validation_status == "conflict"


def test_scorecard_only_match_is_classified_and_isolated(db):
    before = (db.scalar(select(func.count()).select_from(Match)), db.scalar(select(func.count()).select_from(Delivery)))
    bundle = {"source": SRC, "matches": [{
        "source_match_id": "SC-1", "start_date": "1994-02-03", "gender": "male", "format_class": "FIRST_CLASS",
        "teams": ["Testshire", "Fixtureton"], "venue": "Example Ground", "balls_per_over": 6,
        "result": {"type": "draw"}, "toss": {"winner": "Testshire", "decision": "bat"},
        "innings": [{"number": 1, "team": "Testshire", "total": 31, "wickets": 2,
                     "extras": {"byes": 1, "leg_byes": 0, "wides": 0, "no_balls": 0},
                     "batting": [{"name": "A Example", "runs": 20, "out": True}, {"name": "B Example", "runs": 10, "dismissal": "not out"},
                                 {"name": "C Example", "runs": 0, "dismissal": "bowled"}],
                     "bowling": [{"name": "D Example", "overs": "10.3", "maidens": 2, "runs": 30, "wickets": 2}]}]}]}
    report = ScorecardFileAdapter().import_bundle(db, bundle)
    db.commit()
    assert report.created == 1
    rec = db.scalar(select(CanonicalMatchRecord).where(CanonicalMatchRecord.team1_name == "Testshire"))
    assert rec.coverage_status == cov.SCORECARD and rec.match_id is None
    assert rec.validation_status == "scorecard_validated"
    bowl = db.execute(text("SELECT legal_balls FROM scorecard_bowling WHERE canonical_match_id = :c"), {"c": rec.id}).scalar()
    assert bowl == 63
    # Phase 9: the ball-by-ball layer is untouched by scorecard imports.
    assert (db.scalar(select(func.count()).select_from(Match)), db.scalar(select(func.count()).select_from(Delivery))) == before


def test_bundle_without_licence_is_rejected(db):
    with pytest.raises(ScorecardBundleError):
        ScorecardFileAdapter().import_bundle(db, {"source": {"key": "x", "name": "x"}, "matches": []})
    with pytest.raises(ScorecardBundleError):
        ScorecardFileAdapter().import_bundle(db, {"source": {**SRC, "key": "cricsheet"}, "matches": []})


def test_inconsistent_scorecard_is_stored_but_excluded(db):
    bundle = {"source": SRC, "matches": [{
        "source_match_id": "SC-BAD", "start_date": "1995-01-01", "gender": "male", "format_class": "LIST_A",
        "teams": ["Testshire", "Fixtureton"],
        "innings": [{"number": 1, "team": "Testshire", "total": 99, "extras": {"total": 0},
                     "batting": [{"name": "A Example", "runs": 20, "out": True}]}]}]}
    report = ScorecardFileAdapter().import_bundle(db, bundle)
    db.commit()
    assert report.innings_inconsistent == 1
    rec = db.scalar(select(CanonicalMatchRecord).where(CanonicalMatchRecord.format_class == "LIST_A"))
    assert rec.validation_status == "inconsistent"


def test_identity_resolution(db):
    sid, pid = db.execute(text("SELECT source_player_id, player_id FROM player_aliases LIMIT 1")).first()
    assert resolve_player(db, source_player_id=f"cricsheet:{sid}", name="whatever") == (pid, RESOLVED)
    name, team = db.execute(text("""SELECT p.canonical_name, a.team_name FROM match_appearances a
        JOIN players p ON p.id = a.player_id WHERE a.source_key = 'cricsheet' LIMIT 1""")).first()
    assert resolve_player(db, source_player_id=None, name=name, team_name=team)[1] == NAME_TEAM
    assert resolve_player(db, source_player_id=None, name=name, team_name="Some Other XI") == (None, UNRESOLVED)
    assert resolve_player(db, source_player_id=None, name="Nobody Atall", team_name=team) == (None, UNRESOLVED)


# 7. missing innings / 8. incomplete deliveries -----------------------------------------------

def test_deleted_deliveries_make_match_partial(db):
    rec = canonical_for(db, "829807")
    inn_id = db.execute(text("SELECT id FROM match_innings WHERE match_id = :m AND innings_number = 2"), {"m": rec.match_id}).scalar()
    nested = db.begin_nested()
    db.execute(text("DELETE FROM delivery_extras WHERE delivery_id IN (SELECT id FROM deliveries WHERE innings_id = :i AND over_number = 2)"), {"i": inn_id})
    db.execute(text("DELETE FROM wickets WHERE delivery_id IN (SELECT id FROM deliveries WHERE innings_id = :i AND over_number = 2)"), {"i": inn_id})
    db.execute(text("DELETE FROM deliveries WHERE innings_id = :i AND over_number = 2"), {"i": inn_id})
    refresh_coverage(db, [rec.id])
    db.refresh(rec)
    assert rec.coverage_status == cov.PARTIAL and any("missing 1 over" in n for n in rec.coverage_notes)
    nested.rollback()
    refresh_coverage(db, [rec.id])
    db.refresh(rec)
    assert rec.coverage_status == cov.FULL


# inventory comparison and recovery -----------------------------------------------------------

def test_inventory_detects_and_recovers_missing_match(db, tmp_path):
    readme = ("This archive contains 2 matches. A further 5 matches have been withheld due to policy.\n\n"
              "2015-05-15 - club - IPL - male - 829807 - Sunrisers Hyderabad vs Royal Challengers Bangalore\n"
              "2030-01-01 - club - XYZ - male - 999999 - Alpha vs Beta\n")
    (tmp_path / "README.txt").write_text(readme)
    adapter = CricsheetInventoryAdapter(archive_path=tmp_path / "absent.zip", gamedata_dir=tmp_path)
    counts = adapter.refresh_inventory(db)
    assert counts["imported"] == 1 and counts["missing"] == 1 and counts["withheld_by_source"] == 5
    out = adapter.import_missing(db)
    assert out["needs_download"] == 1   # not in the local archive: queued, not invented
    item = db.scalar(select(SourceInventoryItem).where(SourceInventoryItem.source_match_id == "999999"))
    assert item.status == "missing" and item.attempts == 1
    db.rollback()
