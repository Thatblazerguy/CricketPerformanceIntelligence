"""
End-to-end tests for Cricsheet automatic synchronisation.

Runs against a throw-away PostgreSQL database (``<db>_sync_test``) on the same
server as CPI, never the real CPI database. Archives are built from real
Cricsheet match files (tests/fixtures/cricsheet) and served by a local HTTP
server that can emit ETag/Last-Modified, omit them, truncate bodies or fail.
"""
from __future__ import annotations

import io
import json
import threading
import time
import zipfile
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.ingestion import cricsheet_sync_service as svc_mod
from app.ingestion.cricsheet_sync_service import (
    SYNC_LOCK_KEY,
    AdvisoryLock,
    CricsheetSyncService,
    SourceSpec,
    build_status,
)
from app.ingestion.importer import MatchImporter
from app.ingestion.sync_worker import SyncWorker
from app.models.models import (
    Base,
    Delivery,
    Match,
    MatchInnings,
    MatchWinProbability,
    PlayerAlias,
    RawMatch,
    SyncHistory,
    SyncMatchRevision,
    SyncSettings,
    SyncSource,
    SyncWorkerState,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "cricsheet"
MATCH_A, MATCH_B, MATCH_C = "829807", "1182656", "1259551"


# --------------------------------------------------------------------------- database

@pytest.fixture(scope="module")
def test_engine():
    url = make_url(settings.DATABASE_URL)
    test_db = f"{url.database}_sync_test"
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{test_db}" WITH (FORCE)'))
            conn.execute(text(f'CREATE DATABASE "{test_db}"'))
    except Exception as exc:  # pragma: no cover - depends on local PostgreSQL
        pytest.skip(f"Cannot create test database: {exc}")
    engine = create_engine(url.set(database=test_db), pool_pre_ping=True)
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{test_db}" WITH (FORCE)'))
    admin.dispose()


@pytest.fixture()
def Session(test_engine):
    # Fresh, empty tables for every test (TRUNCATE in FK-safe order via CASCADE).
    names = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
    with test_engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))
    svc_mod._counts_cache.update(marker=object(), at=0.0, value=None)
    return sessionmaker(bind=test_engine, autocommit=False, autoflush=False)


# --------------------------------------------------------------------------- HTTP server

class ArchiveServer:
    """Serves /<name>.zip with controllable headers and failure modes."""

    def __init__(self):
        self.routes = {}
        self.requests = []
        self.headers_seen = []
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _serve(self, with_body: bool):
                server.requests.append((self.command, self.path))
                server.headers_seen.append((self.command, self.path, dict(self.headers)))
                route = server.routes.get(self.path)
                if route is None:
                    self.send_response(404)
                    self.end_headers()
                    return
                if route.get("mode") == "error500":
                    self.send_response(500)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                body = route["body"]
                rng, if_range = self.headers.get("Range"), self.headers.get("If-Range")
                if with_body and rng and route.get("etag") and if_range == route["etag"]:
                    start = int(rng.split("=")[1].split("-")[0])
                    self.send_response(206)
                    self.send_header("Content-Range", f"bytes {start}-{len(body) - 1}/{len(body)}")
                    self.send_header("ETag", route["etag"])
                    self.send_header("Content-Length", str(len(body) - start))
                    self.end_headers()
                    rest = body[start:]
                    if route.get("mode") == "truncate":  # network that never recovers
                        self.wfile.write(rest[: len(rest) // 3])
                        self.close_connection = True
                        return
                    self.wfile.write(rest)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/zip")
                if route.get("etag"):
                    self.send_header("ETag", route["etag"])
                if route.get("last_modified"):
                    self.send_header("Last-Modified", route["last_modified"])
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                if not with_body:
                    return
                if route.get("mode") == "truncate" or (route.get("mode") == "truncate_once" and not route.get("cut")):
                    route["cut"] = True
                    self.wfile.write(body[: len(body) // 3])
                    self.wfile.flush()
                    self.close_connection = True
                    return
                if route.get("delay"):
                    time.sleep(route["delay"])
                self.wfile.write(body)

            def do_HEAD(self):
                self._serve(False)

            def do_GET(self):
                self._serve(True)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    @property
    def base(self):
        return f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def publish(self, name, body, etag=None, last_modified=None, mode="ok", delay=0):
        self.routes[f"/{name}.zip"] = {"body": body, "etag": etag, "last_modified": last_modified,
                                       "mode": mode, "delay": delay}

    def count(self, method, name):
        return sum(1 for m, p in self.requests if m == method and p == f"/{name}.zip")

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture()
def server():
    s = ArchiveServer()
    yield s
    s.close()


# --------------------------------------------------------------------------- helpers

def fixture_bytes(match_id):
    return (FIXTURES / f"{match_id}.json").read_bytes()


def corrected_bytes(match_id=MATCH_A):
    """Real file with one delivery corrected: DA Warner's 0.3 single becomes a three."""
    data = json.loads(fixture_bytes(match_id))
    ball = data["innings"][0]["overs"][0]["deliveries"][2]
    assert ball["batter"] == "DA Warner" and ball["runs"]["batter"] == 1
    ball["runs"]["batter"], ball["runs"]["total"] = 3, 3
    return json.dumps(data).encode()


def make_zip(files: dict, extra=None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("README.txt", "Cricsheet test archive")
        for name, data in files.items():
            zf.writestr(f"{name}.json" if not name.endswith(".json") else name, data)
        for name, data in (extra or {}).items():
            zf.writestr(name, data)
    return buf.getvalue()


@pytest.fixture()
def env(tmp_path, server, Session, test_engine, monkeypatch):
    """Two sources (like all_json + ipl_json) pointing at the local server."""
    specs = [
        SourceSpec("cricsheet_all", "All matches", f"{server.base}/all_json.zip", tmp_path / "gamedata"),
        SourceSpec("cricsheet_ipl", "IPL", f"{server.base}/ipl_json.zip", tmp_path / "ipl"),
    ]
    monkeypatch.setattr(svc_mod, "default_sources", lambda: specs)

    def make_service(**kw):
        opts = dict(session_factory=Session, engine=test_engine, sources=specs,
                    archive_dir=tmp_path / "archives", staging_dir=tmp_path / "staging", retry_delays=(0, 0))
        opts.update(kw)
        return CricsheetSyncService(**opts)

    # The IPL archive starts empty of JSON: only all_json carries data unless a test publishes it.
    server.publish("ipl_json", make_zip({MATCH_A: fixture_bytes(MATCH_A)}), etag='"ipl-1"')
    return {"specs": specs, "service": make_service, "tmp": tmp_path}


def counts(Session):
    with Session() as db:
        return {
            "matches": db.execute(select(func.count()).select_from(Match)).scalar_one(),
            "innings": db.execute(select(func.count()).select_from(MatchInnings)).scalar_one(),
            "deliveries": db.execute(select(func.count()).select_from(Delivery)).scalar_one(),
        }


def json_delivery_count(raw: bytes) -> int:
    data = json.loads(raw)
    return sum(len(o["deliveries"]) for inn in data["innings"] for o in inn["overs"])


def batter_runs(Session, match_source_id, batter_name):
    with Session() as db:
        return db.execute(text("""
            SELECT coalesce(sum(d.batter_runs), 0) FROM deliveries d
            JOIN match_innings i ON i.id = d.innings_id JOIN matches m ON m.id = i.match_id
            JOIN players p ON p.id = d.batter_id
            WHERE m.source_match_id = :m AND p.canonical_name = :b
        """), {"m": match_source_id, "b": batter_name}).scalar_one()


def history(Session, source_key="cricsheet_all"):
    with Session() as db:
        return db.execute(select(SyncHistory).where(SyncHistory.source_key == source_key)
                          .order_by(SyncHistory.id.desc())).scalars().first()


def only_all_source(Session):
    with Session() as db:
        db.execute(text("UPDATE sync_sources SET enabled = (source_key = 'cricsheet_all')"))
        db.commit()


def seed(env, server, Session, files=(MATCH_A, MATCH_B), etag='"v1"'):
    server.publish("all_json", make_zip({m: fixture_bytes(m) for m in files}), etag=etag,
                   last_modified="Wed, 12 Nov 2026 10:00:00 GMT")
    with Session() as db:
        svc_mod.ensure_bootstrap(db, env["specs"])
    only_all_source(Session)
    return env["service"]().run_sync(triggered_by="manual")


# --------------------------------------------------------------------------- tests

def test_initial_worker_startup_runs_first_check_and_schedules_next(env, server, Session, test_engine):
    server.publish("all_json", make_zip({MATCH_A: fixture_bytes(MATCH_A)}), etag='"v1"')
    t0 = datetime(2026, 11, 13, 12, 0, 0)
    worker = SyncWorker(Session, test_engine, service_factory=lambda stop: env["service"](stop_event=stop),
                        heartbeat_seconds=3600, clock=lambda: t0)
    assert worker.start()
    try:
        with Session() as db:
            st = db.get(SyncWorkerState, 1)
            assert st.state == "idle" and st.pid and st.heartbeat_at == t0
            assert st.next_check_at == t0  # never checked before -> initial check now
        result = worker.tick()
        assert result["status"] == "completed"
        assert result["sources"]["cricsheet_all"]["new_matches"] == 1
        with Session() as db:
            assert db.get(SyncWorkerState, 1).next_check_at == t0 + timedelta(hours=6)
            assert db.get(SyncWorkerState, 1).last_success_at is not None
        # a second instance is refused while the first holds the worker lock
        other = SyncWorker(Session, test_engine, service_factory=lambda stop: env["service"](stop_event=stop))
        assert other.start() is False
    finally:
        worker.shutdown()
    with Session() as db:
        assert db.get(SyncWorkerState, 1).state == "stopped"


def test_no_archive_changes_skips_download(env, server, Session):
    first = seed(env, server, Session)
    assert first["status"] == "completed"
    before = counts(Session)
    gets_before = server.count("GET", "all_json")

    second = env["service"]().run_sync()
    assert second["sources"]["cricsheet_all"]["status"] == "no_changes"
    assert server.count("GET", "all_json") == gets_before  # HEAD only
    assert counts(Session) == before
    h = history(Session)
    assert h.status == "no_changes" and h.phase == "completed" and h.archive_changed is False


def test_no_http_metadata_falls_back_to_archive_checksum(env, server, Session):
    body = make_zip({MATCH_A: fixture_bytes(MATCH_A)})
    server.publish("all_json", body)  # no ETag / Last-Modified
    with Session() as db:
        svc_mod.ensure_bootstrap(db, env["specs"])
    only_all_source(Session)
    assert env["service"]().run_sync()["status"] == "completed"
    again = env["service"]().run_sync()
    assert again["sources"]["cricsheet_all"]["status"] == "no_changes"
    assert server.count("GET", "all_json") == 2  # had to download to compare checksums
    # refreshed archive whose bytes differ but contains no new matches
    server.publish("all_json", make_zip({MATCH_A: fixture_bytes(MATCH_A)}, extra={"LICENSE.txt": "x"}))
    third = env["service"]().run_sync()["sources"]["cricsheet_all"]
    assert third["status"] == "completed" and third["new_matches"] == 0 and third["unchanged_matches"] == 1


def test_new_matches_detected_and_imported(env, server, Session):
    seed(env, server, Session)
    assert counts(Session)["matches"] == 2
    server.publish("all_json", make_zip({m: fixture_bytes(m) for m in (MATCH_A, MATCH_B, MATCH_C)}), etag='"v2"')
    res = env["service"]().run_sync()["sources"]["cricsheet_all"]
    assert (res["new_matches"], res["updated_matches"], res["unchanged_matches"]) == (1, 0, 2)
    c = counts(Session)
    assert c["matches"] == 3
    assert c["deliveries"] == sum(json_delivery_count(fixture_bytes(m)) for m in (MATCH_A, MATCH_B, MATCH_C))
    assert (env["tmp"] / "gamedata" / f"{MATCH_C}.json").read_bytes() == fixture_bytes(MATCH_C)
    with Session() as db:
        status = build_status(db)
    assert status["data_updated_through"] == "2021-09-19"  # newest fixture's match date
    assert status["last_checked_at"] is not None and status["last_checked_at"] != status["data_updated_through"]
    assert status["new_matches_latest_sync"] == 1 and status["total_matches"] == 3


def test_corrected_match_replaced_not_appended_and_player_stats_correct(env, server, Session):
    seed(env, server, Session)
    with Session() as db:
        match_id = db.execute(select(Match.id).where(Match.source_match_id == MATCH_A)).scalar_one()
        old_checksum = db.execute(select(RawMatch.checksum).where(RawMatch.source_match_id == MATCH_A)).scalar_one()
        players_before = db.execute(select(func.count()).select_from(PlayerAlias)).scalar_one()
    runs_before = batter_runs(Session, MATCH_A, "DA Warner")
    before = counts(Session)

    server.publish("all_json", make_zip({MATCH_A: corrected_bytes(), MATCH_B: fixture_bytes(MATCH_B)}), etag='"v2"')
    res = env["service"]().run_sync()["sources"]["cricsheet_all"]
    assert (res["new_matches"], res["updated_matches"], res["unchanged_matches"]) == (0, 1, 1)

    assert counts(Session) == before  # same innings/deliveries: replaced, not appended
    assert batter_runs(Session, MATCH_A, "DA Warner") == runs_before + 2
    with Session() as db:
        # stable identity: same internal match id and no new players
        assert db.execute(select(Match.id).where(Match.source_match_id == MATCH_A)).scalar_one() == match_id
        assert db.execute(select(func.count()).select_from(PlayerAlias)).scalar_one() == players_before
        rev = db.execute(select(SyncMatchRevision)).scalars().one()
        assert rev.match_id == match_id and rev.previous_checksum == old_checksum
        assert rev.new_checksum == db.execute(select(RawMatch.checksum).where(RawMatch.source_match_id == MATCH_A)).scalar_one()
        wp = db.get(MatchWinProbability, match_id)
    h = history(Session)
    assert h.stats_refresh["affected_matches"] == 1
    if (Path(svc_mod.__file__).resolve().parents[2] / "artifacts" / "win_probability" / "t20.joblib").exists():
        assert wp is not None and wp.built_at >= h.started_at - timedelta(seconds=5)
        assert h.stats_refresh["win_probability_matches"] == 1


def test_duplicate_imports_prevented_across_sources_and_reruns(env, server, Session):
    seed(env, server, Session)
    with Session() as db:
        db.execute(text("UPDATE sync_sources SET enabled = true"))
        db.commit()
    # ipl_json contains MATCH_A, already imported from all_json
    res = env["service"]().run_sync()
    assert res["sources"]["cricsheet_ipl"]["new_matches"] == 0
    assert res["sources"]["cricsheet_ipl"]["unchanged_matches"] == 1
    # same content republished under a new ETag
    server.publish("all_json", make_zip({m: fixture_bytes(m) for m in (MATCH_A, MATCH_B)}), etag='"v3"')
    env["service"]().run_sync()
    c = counts(Session)
    assert c["matches"] == 2
    assert c["deliveries"] == json_delivery_count(fixture_bytes(MATCH_A)) + json_delivery_count(fixture_bytes(MATCH_B))
    with Session() as db:
        dupes = db.execute(text("""SELECT count(*) FROM (SELECT innings_id, over_number, delivery_sequence
            FROM deliveries GROUP BY 1,2,3 HAVING count(*) > 1) x""")).scalar_one()
    assert dupes == 0


@pytest.mark.parametrize("body,needle", [
    (b"this is not a zip file at all", "ZIP"),
    (make_zip({}, extra={"../../evil.json": "{}"}), "Unsafe path"),
    (make_zip({}), "no match JSON"),
])
def test_invalid_zip_rejected_and_dataset_preserved(env, server, Session, body, needle):
    seed(env, server, Session)
    before = counts(Session)
    with Session() as db:
        src_before = db.execute(select(SyncSource.etag, SyncSource.latest_checksum)
                                .where(SyncSource.source_key == "cricsheet_all")).one()
    server.publish("all_json", body, etag='"broken"')
    res = env["service"]().run_sync()
    assert res["sources"]["cricsheet_all"]["status"] == "failed"
    assert needle in res["sources"]["cricsheet_all"]["error"]
    assert counts(Session) == before
    with Session() as db:
        src = db.execute(select(SyncSource).where(SyncSource.source_key == "cricsheet_all")).scalar_one()
        assert (src.etag, src.latest_checksum) == tuple(src_before)  # not advanced: retried next check
        assert src.last_error
    assert not (env["tmp"] / "staging").exists() or not any((env["tmp"] / "staging").rglob("*.json"))
    assert history(Session).phase == "failed"


def test_malformed_json_is_isolated(env, server, Session):
    seed(env, server, Session)
    server.publish("all_json", make_zip({
        MATCH_A: fixture_bytes(MATCH_A), MATCH_B: fixture_bytes(MATCH_B), MATCH_C: fixture_bytes(MATCH_C),
        "9999901": b'{"meta": {"data_version": "1.1.0"}, "info": {',          # truncated JSON
        "9999902": b'{"meta": {}, "info": {"teams": []}, "innings": []}',     # missing required fields
    }), etag='"v2"')
    res = env["service"]().run_sync()["sources"]["cricsheet_all"]
    assert res["status"] == "partial"
    assert (res["new_matches"], res["failed_records"]) == (1, 2)
    h = history(Session)
    assert sorted(f["file"] for f in h.failed_files) == ["9999901.json", "9999902.json"]
    assert counts(Session)["matches"] == 3
    with Session() as db:
        assert db.execute(select(func.count()).select_from(RawMatch)
                          .where(RawMatch.source_match_id.in_(["9999901", "9999902"]))).scalar_one() == 0


def test_network_interruption_handled(env, server, Session):
    seed(env, server, Session)
    before = counts(Session)
    server.publish("all_json", make_zip({m: fixture_bytes(m) for m in (MATCH_A, MATCH_B, MATCH_C)}),
                   etag='"v2"', mode="truncate")
    res = env["service"]().run_sync()["sources"]["cricsheet_all"]
    assert res["status"] == "failed"
    assert server.count("GET", "all_json") >= 1 + 3  # seed + initial attempt + 2 retries
    assert counts(Session) == before

    server.publish("all_json", b"", etag='"v2"', mode="error500")
    assert env["service"]().run_sync()["sources"]["cricsheet_all"]["status"] == "failed"

    # server unreachable
    dead = env["service"](sources=[SourceSpec("cricsheet_all", "x", "http://127.0.0.1:9/all_json.zip",
                                              env["tmp"] / "gamedata")])
    out = dead.run_sync()["sources"]["cricsheet_all"]
    assert out["status"] == "failed" and "Connect" in out["error"]
    assert counts(Session) == before

    # recovers once the network is back
    server.publish("all_json", make_zip({m: fixture_bytes(m) for m in (MATCH_A, MATCH_B, MATCH_C)}), etag='"v2"')
    assert env["service"]().run_sync()["sources"]["cricsheet_all"]["new_matches"] == 1


def test_failed_match_import_rolls_back_to_previous_version(env, server, Session, monkeypatch):
    seed(env, server, Session)
    runs_before = batter_runs(Session, MATCH_A, "DA Warner")
    before = counts(Session)
    with Session() as db:
        old_checksum = db.execute(select(RawMatch.checksum).where(RawMatch.source_match_id == MATCH_A)).scalar_one()

    real_insert = MatchImporter._insert_delivery
    calls = {"n": 0}

    def flaky_insert(self, dl, innings_id):
        calls["n"] += 1
        if calls["n"] == 40:  # fail midway through the corrected match's deliveries
            raise RuntimeError("simulated failure mid-import")
        return real_insert(self, dl, innings_id)

    monkeypatch.setattr(MatchImporter, "_insert_delivery", flaky_insert)
    server.publish("all_json", make_zip({MATCH_A: corrected_bytes(), MATCH_B: fixture_bytes(MATCH_B),
                                         MATCH_C: fixture_bytes(MATCH_C)}), etag='"v2"')
    res = env["service"]().run_sync()["sources"]["cricsheet_all"]
    assert res["status"] == "partial" and res["failed_records"] == 1
    assert res["new_matches"] == 1  # the next match still imported after the rollback

    # previous version of the failed match is fully intact
    assert batter_runs(Session, MATCH_A, "DA Warner") == runs_before
    after = counts(Session)
    assert after["matches"] == before["matches"] + 1
    assert after["deliveries"] == before["deliveries"] + json_delivery_count(fixture_bytes(MATCH_C))
    with Session() as db:
        assert db.execute(select(RawMatch.checksum).where(RawMatch.source_match_id == MATCH_A)).scalar_one() == old_checksum
        assert db.execute(select(func.count()).select_from(SyncMatchRevision)).scalar_one() == 0

    # next archive refresh retries it successfully
    monkeypatch.setattr(MatchImporter, "_insert_delivery", real_insert)
    server.publish("all_json", make_zip({MATCH_A: corrected_bytes(), MATCH_B: fixture_bytes(MATCH_B),
                                         MATCH_C: fixture_bytes(MATCH_C)}), etag='"v3"')
    res = env["service"]().run_sync()["sources"]["cricsheet_all"]
    assert res["updated_matches"] == 1 and res["failed_records"] == 0
    assert batter_runs(Session, MATCH_A, "DA Warner") == runs_before + 2


def test_concurrent_sync_requests_prevented(env, server, Session, test_engine):
    seed(env, server, Session)
    holder = AdvisoryLock(test_engine, SYNC_LOCK_KEY)
    assert holder.acquire()
    try:
        assert env["service"]().run_sync() == {"status": "already_running"}
        assert svc_mod.advisory_lock_held(test_engine)
    finally:
        holder.release()
    assert not svc_mod.advisory_lock_held(test_engine)

    # two real overlapping runs: slow download keeps the first one inside the lock
    server.publish("all_json", make_zip({m: fixture_bytes(m) for m in (MATCH_A, MATCH_B, MATCH_C)}),
                   etag='"v2"', delay=1.5)
    results = []
    t = threading.Thread(target=lambda: results.append(env["service"]().run_sync()))
    t.start()
    time.sleep(0.5)
    results.append(env["service"]().run_sync())
    t.join(30)
    statuses = sorted(r["status"] for r in results)
    assert statuses == ["already_running", "completed"]
    assert counts(Session)["matches"] == 3


def test_worker_resumes_schedule_after_restart(env, server, Session, test_engine):
    seed(env, server, Session)
    t0 = datetime.utcnow()
    factory = lambda stop: env["service"](stop_event=stop)
    w1 = SyncWorker(Session, test_engine, service_factory=factory, heartbeat_seconds=3600, clock=lambda: t0)
    assert w1.start()
    w1.next_check_at = t0  # force a scheduled run now
    assert w1.tick()["status"] in ("completed", "no_changes")
    w1.shutdown()
    with Session() as db:
        persisted = db.get(SyncWorkerState, 1).next_check_at
    assert persisted == t0 + timedelta(hours=6)

    # simulate a crash mid-sync: a history row left 'running'
    with Session() as db:
        db.add(SyncHistory(run_id="crashed", source_key="cricsheet_all", status="running",
                           phase="importing", started_at=t0))
        db.commit()

    # restart shortly afterwards: keeps the persisted schedule, no immediate check
    soon = t0 + timedelta(minutes=5)
    w2 = SyncWorker(Session, test_engine, service_factory=factory, heartbeat_seconds=3600, clock=lambda: soon)
    assert w2.start()
    assert w2.next_check_at == persisted
    assert w2.tick() is None
    w2.shutdown()

    # restart after the due time: runs immediately, and the stale row is marked interrupted
    late = t0 + timedelta(hours=7)
    w3 = SyncWorker(Session, test_engine, service_factory=factory, heartbeat_seconds=3600,
                    clock=lambda: late, check_on_start=False)
    assert w3.start()
    assert w3.next_check_at <= late
    assert w3.tick() is not None
    w3.shutdown()
    with Session() as db:
        crashed = db.execute(select(SyncHistory).where(SyncHistory.run_id == "crashed")).scalar_one()
        assert crashed.status == "interrupted"


def _api_client(Session, test_engine, monkeypatch):
    from fastapi.testclient import TestClient
    from app.api.routes import data_sync
    from app.db.session import get_db
    from app.main import app

    def _get_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    monkeypatch.setattr(data_sync, "engine", test_engine)
    monkeypatch.setattr(data_sync, "SessionLocal", Session)
    app.dependency_overrides[get_db] = _get_db
    return TestClient(app), app, get_db


def test_auto_sync_can_be_disabled(env, server, Session, test_engine, monkeypatch):
    seed(env, server, Session)
    client, app, get_db = _api_client(Session, test_engine, monkeypatch)
    try:
        r = client.post("/api/v1/data-sync/settings", json={"auto_sync_enabled": False, "interval_hours": 12})
        assert r.status_code == 200 and r.json()["auto_sync_enabled"] is False and r.json()["interval_hours"] == 12
        assert client.post("/api/data-sync/settings", json={"interval_hours": 0.01}).status_code == 422
    finally:
        app.dependency_overrides.pop(get_db, None)

    t = datetime.utcnow() + timedelta(days=2)  # long overdue
    worker = SyncWorker(Session, test_engine, service_factory=lambda stop: env["service"](stop_event=stop),
                        heartbeat_seconds=3600, clock=lambda: t)
    assert worker.start()
    try:
        assert worker.next_check_at is None
        assert worker.tick() is None
        with Session() as db:
            assert db.get(SyncWorkerState, 1).next_check_at is None
            # a manual request still runs while automatic sync is off
            db.get(SyncSettings, 1).manual_requested_at = datetime.utcnow()
            db.commit()
        assert worker.tick()["triggered_by"] == "manual"
        with Session() as db:
            assert db.get(SyncWorkerState, 1).next_check_at is None
    finally:
        worker.shutdown()


def test_manual_sync_via_api(env, server, Session, test_engine, monkeypatch):
    server.publish("all_json", make_zip({MATCH_A: fixture_bytes(MATCH_A)}), etag='"v1"')
    with Session() as db:
        svc_mod.ensure_bootstrap(db, env["specs"])
    only_all_source(Session)
    from app.api.routes import data_sync
    monkeypatch.setattr(data_sync, "CricsheetSyncService",
                        lambda **kw: env["service"]())  # same service class, test DB + local server
    client, app, get_db = _api_client(Session, test_engine, monkeypatch)
    try:
        # worker not running -> API runs the shared service itself
        r = client.post("/api/v1/data-sync/trigger")
        assert r.status_code == 202 and r.json()["handled_by"] == "api"
        data_sync._api_thread.join(60)
        status = client.get("/api/v1/data-sync/status").json()
        assert status["latest_sync"]["status"] == "completed"
        assert status["latest_sync"]["triggered_by"] == "manual"
        assert status["new_matches_latest_sync"] == 1 and status["total_matches"] == 1
        assert status["data_updated_through"] == "2015-05-15"
        hist = client.get("/api/data-sync/history?page_size=5").json()
        assert hist["total"] == 1 and hist["items"][0]["phase"] == "completed"

        # lock held -> 409, no second import launched
        holder = AdvisoryLock(test_engine, SYNC_LOCK_KEY)
        assert holder.acquire()
        try:
            assert client.post("/api/v1/data-sync/trigger").status_code == 409
        finally:
            holder.release()

        # healthy worker -> request is queued for it, and the worker consumes it
        worker = SyncWorker(Session, test_engine, service_factory=lambda stop: env["service"](stop_event=stop),
                            heartbeat_seconds=3600, check_on_start=False)
        assert worker.start()
        try:
            r = client.post("/api/v1/data-sync/trigger")
            assert r.json() == {**r.json(), "status": "queued", "handled_by": "worker"}
            assert worker.tick()["triggered_by"] == "manual"
            health = client.get("/api/v1/data-sync/health").json()
            assert health["status"] == "ok" and health["worker"]["healthy"] is True
        finally:
            worker.shutdown()
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_interrupted_download_resumes_with_range_request(env, server, Session):
    seed(env, server, Session)
    body = make_zip({m: fixture_bytes(m) for m in (MATCH_A, MATCH_B, MATCH_C)})
    server.publish("all_json", body, etag='"v2"', mode="truncate_once")
    res = env["service"]().run_sync()["sources"]["cricsheet_all"]
    assert res["status"] == "completed" and res["new_matches"] == 1
    gets = [h for m, p, h in server.headers_seen if m == "GET" and p == "/all_json.zip"]
    assert "Range" not in gets[-2] and gets[-1]["Range"].startswith("bytes=") and gets[-1]["If-Range"] == '"v2"'
    with Session() as db:
        import hashlib
        stored = db.execute(select(SyncSource.latest_checksum).where(SyncSource.source_key == "cricsheet_all")).scalar_one()
    assert stored == hashlib.sha256(body).hexdigest()  # resumed bytes hash to the full archive
