"""One-off / repeatable backfill of the hybrid registry for an existing CPI database.

Steps (all idempotent, safe to re-run):
  1. canonical_matches + match_source_refs for every ball-by-ball match (SQL).
  2. Scan the extracted Cricsheet JSON (GAMEDATA_DIR) for facts the delivery
     tables do not keep: playing XIs, forfeited/declared innings, info.missing
     markers and end dates.
  3. Cross-provider player identifiers from Cricsheet people.csv.
  4. Recompute coverage for every canonical match.
  5. Refresh the Cricsheet source inventory and compare it with the database.

Usage:  cd backend && .venv/bin/python -m scripts.backfill_hybrid_registry [--skip-json]
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import resolve_backend_path, settings  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.hybrid import registry  # noqa: E402
from app.hybrid.people import import_external_ids  # noqa: E402
from app.hybrid.sources.cricsheet_inventory import CricsheetInventoryAdapter  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("backfill_hybrid")


def _scan(path: str):
    try:
        with open(path, "rb") as fh:
            data = json.loads(fh.read())
    except Exception as exc:  # noqa: BLE001 - report and continue
        return Path(path).stem, None, str(exc)
    info = data.get("info", {})
    missing = []
    for item in info.get("missing") or []:
        missing.extend([item] if isinstance(item, str) else list(item) if isinstance(item, dict) else [])
    inns = data.get("innings", [])
    dates = info.get("dates") or []
    reg = (info.get("registry") or {}).get("people", {})
    xi = [(team, reg.get(name)) for team, names in (info.get("players") or {}).items() for name in names if reg.get(name)]
    return Path(path).stem, {
        "forfeited_innings": [n for n, i in enumerate(inns, 1) if i.get("forfeited")],
        "declared_innings": [n for n, i in enumerate(inns, 1) if i.get("declared")],
        "missing_fields": sorted(set(missing)),
        "end_date": str(dates[-1]) if dates else None,
        "result_method": (info.get("outcome") or {}).get("method"),
        "xi": xi,
    }, None


def scan_json(db) -> dict:
    gamedata = resolve_backend_path(settings.GAMEDATA_DIR)
    files = sorted(str(p) for p in gamedata.glob("*.json"))
    log.info("Scanning %d Cricsheet JSON files in %s", len(files), gamedata)
    ref_ids = dict(db.execute(text("""SELECT r.source_match_id, r.canonical_match_id FROM match_source_refs r
                                      WHERE r.source_key = 'cricsheet'""")).all())
    player_ids = dict(db.execute(text("""SELECT pa.source_player_id, pa.player_id FROM player_aliases pa
                                         JOIN providers p ON p.id = pa.provider_id WHERE p.name = 'cricsheet'""")).all())
    ref_rows, app_rows, date_rows, errors = [], [], [], []
    with ProcessPoolExecutor() as pool:
        for sid, facts, err in pool.map(_scan, files, chunksize=200):
            if err:
                errors.append((sid, err))
                continue
            cid = ref_ids.get(sid)
            if not cid:
                continue
            ev = {k: facts[k] for k in ("forfeited_innings", "declared_innings", "missing_fields", "result_method")}
            ref_rows.append({"sid": sid, "ev": json.dumps(ev), "cid": cid, "missing": json.dumps(facts["missing_fields"])})
            if facts["end_date"]:
                date_rows.append({"cid": cid, "d": facts["end_date"]})
            seen = set()
            for team, reg_id in facts["xi"]:
                pid = player_ids.get(reg_id)
                if pid and pid not in seen:
                    seen.add(pid)
                    app_rows.append({"cid": cid, "pid": pid, "team": team})
    for chunk in registry._chunks(ref_rows, 5000):
        db.execute(text("""UPDATE match_source_refs SET match_evidence = CAST(:ev AS json)
                           WHERE source_key = 'cricsheet' AND source_match_id = :sid"""), chunk)
        db.execute(text("UPDATE canonical_matches SET missing_fields = CAST(:missing AS json) WHERE id = :cid"), chunk)
    for chunk in registry._chunks(date_rows, 5000):
        db.execute(text("UPDATE canonical_matches SET end_date = CAST(:d AS date) WHERE id = :cid"), chunk)
    for chunk in registry._chunks(app_rows, 10000):
        db.execute(text("""INSERT INTO match_appearances (id, canonical_match_id, player_id, team_name, source_key)
                           VALUES (gen_random_uuid()::text, :cid, :pid, :team, 'cricsheet')
                           ON CONFLICT (canonical_match_id, player_id) DO NOTHING"""), chunk)
    return {"files": len(files), "evidence_rows": len(ref_rows), "appearances": len(app_rows), "errors": len(errors)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-json", action="store_true", help="skip the Cricsheet JSON scan (step 2)")
    args = ap.parse_args()
    t0 = time.time()
    with SessionLocal() as db:
        out = registry.backfill_from_ball_by_ball(db)
        db.commit()
        log.info("Canonical registry: %s", out)
        if not args.skip_json:
            scanned = scan_json(db)
            db.commit()
            log.info("JSON scan: %s", scanned)
            out.update({f"json_{k}": v for k, v in scanned.items()})
        ext = import_external_ids(db)
        db.commit()
        log.info("External player ids: %s", ext)
        counts = registry.refresh_coverage(db)
        db.commit()
        log.info("Coverage: %s", counts)
        inv = CricsheetInventoryAdapter().refresh_inventory(db)
        db.commit()
        log.info("Inventory: %s", inv)
        registry.log_event(db, "cricsheet", "backfill_hybrid_registry", "ok", "",
                           **{k: v for k, v in out.items() if isinstance(v, int)}, **counts)
        db.commit()
    log.info("Done in %.1fs", time.time() - t0)


if __name__ == "__main__":
    main()
