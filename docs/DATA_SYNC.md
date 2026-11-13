# Cricsheet automatic synchronisation

CPI keeps its PostgreSQL dataset current with [Cricsheet](https://cricsheet.org/downloads/)
using a local background worker. It runs without the browser or the React app and
reuses the existing parser (`CricsheetParser`) and importer (`MatchImporter`).

## What is monitored

| Source key | Archive | Local mirror |
|---|---|---|
| `cricsheet_all` | `https://cricsheet.org/downloads/all_json.zip` | `gamedata/` (the 23k-match dataset CPI was built from) |
| `cricsheet_ipl` | `https://cricsheet.org/downloads/ipl_json.zip` | `data/raw/ipl/matches` |
| `cricsheet_t20i` | `https://cricsheet.org/downloads/t20s_json.zip` | `data/raw/t20i/matches` |

`all_json` already contains the IPL and T20I matches; matches are keyed by
`(provider, source_match_id)` and file SHA-256, so the subset archives never create
duplicates. Each source can be switched off in Settings → Data Management.

## How a sync works

For each enabled archive (state recorded on a `sync_history` row, visible in the UI):

1. **Checking source** – HTTP `HEAD`; compare `ETag` / `Last-Modified` with `sync_sources`.
   Unchanged → status `no_changes`, nothing is downloaded.
2. **Downloading archive** – only when changed, or when the server sends no HTTP
   metadata (then the archive SHA-256 is compared). Transient network errors are retried
   twice; a truncated body is detected via `Content-Length`.
3. **Extracting files** – the ZIP is validated (no absolute/`..` paths, no symlinks,
   size and compression-ratio limits, CRC checked while reading). Each `*.json` member is
   hashed in memory and compared with `raw_matches.checksum`; only new or changed files
   are written to a per-run staging folder (`data/staging/sync/<run>/`).
4. **Validating matches** – staged files are parsed; malformed files are recorded in
   `sync_history.failed_files` and skipped.
5. **Importing matches** – `MatchImporter.import_match`, **one transaction per match**.
   A corrected match has its innings/deliveries/wickets/extras deleted and re-inserted
   inside that transaction, and a `sync_match_revisions` row (old/new checksum) is
   committed with it. If anything fails the transaction rolls back and the previously
   imported version stays intact. Internal match/player IDs are preserved.
6. **Refreshing statistics** – see below.
7. **Completed** – the archive is kept as `data/raw/archives/<source>.zip`, the JSON
   mirror is updated, and `sync_sources` metadata advances.

If an archive is invalid or the network fails, nothing in PostgreSQL changes and the
stored ETag/checksum are not advanced, so the next check retries. If individual
matches fail, the run is `partial`; those matches are retried the next time Cricsheet
republishes the archive.

## Dependent statistics

Scorecards, batting/bowling, career profiles, team records, partnerships, venues,
head-to-head, scouting and visualisation datasets are computed on demand from
`matches` / `match_innings` / `deliveries`, so they are correct as soon as a match is
committed. The API drops its in-process caches (grounds, similarity/scouting cohorts,
auction form, XI presets) within 30 s of a sync that imported or corrected matches.

Persisted derived data is recomputed **only for affected entities**:

* `match_win_probabilities` – curves for new/corrected matches are rebuilt with the
  saved models in `backend/artifacts/win_probability/` (stale curves for corrected
  matches are deleted first).
* `player_win_probability_impact` – rebuilt only for players who appear in affected
  matches (including players removed by a correction).
* Player nationality evidence – refreshed per match by the importer.

Retraining the ML models themselves remains an explicit offline step
(`scripts/build_win_probability.py`, `scripts/train_match_simulator.py`).

## Running the worker

```bash
./start.sh                               # API + worker + frontend; Ctrl+C stops what it started
backend/scripts/sync_worker.sh start     # worker only, in the background
backend/scripts/sync_worker.sh status    # health, schedule, data freshness, latest result
backend/scripts/sync_worker.sh logs      # follow backend/logs/sync_worker.log
backend/scripts/sync_worker.sh stop      # graceful: finishes the current match
backend/scripts/sync_worker.sh once      # one sync cycle in the foreground
```

### Start at login (optional, macOS)

```bash
backend/scripts/install_launchd.sh install     # ~/Library/LaunchAgents/com.cpi.syncworker.plist
backend/scripts/install_launchd.sh status
backend/scripts/install_launchd.sh uninstall
```

launchd restarts the worker after a crash. PostgreSQL should also start at login
(`brew services start postgresql@16`); the worker waits until the database accepts
connections.

## Scheduling and restarts

* Default interval: 6 hours (Settings, or `POST /api/v1/data-sync/settings`; 15 min–7 days).
* On start the worker checks immediately, unless a check succeeded in the last 15 minutes
  or "Check when the worker starts" is off; otherwise it resumes the schedule persisted in
  `sync_worker_state.next_check_at` (catching up immediately if a check was missed while
  the computer was off or asleep).
* Only one worker can run per database (PostgreSQL advisory lock). Only one sync can run
  at a time (a second advisory lock), whether started by the schedule, the worker CLI or
  the **Sync Now** button.
* A sync left `running` by a killed process is marked `interrupted` on the next run.
* The worker writes a heartbeat every 30 s; the UI shows it as not responding after 2 min.

## API

All under `/api/v1/data-sync` (also reachable as `/api/data-sync`):

| Method | Path | Purpose |
|---|---|---|
| GET | `/status` | `data_updated_through` (latest match date in the DB), `last_checked_at` (last successful Cricsheet check), last import, totals, latest/current sync with phase and progress, next check, worker health, settings, sources |
| GET | `/history?page=&page_size=&source_key=&status=` | paginated `sync_history` |
| POST | `/trigger` | manual sync. 202 `queued` (worker will run it) or `started` (worker down, API runs it); 409 if one is already running |
| GET/POST | `/settings` | `auto_sync_enabled`, `interval_hours`, `check_on_start`, `sources: {key: bool}` |
| GET | `/health` | database, worker heartbeat, sync lock; 503 if the database is unreachable |

## Tables (migration `20261112autosync1`)

`sync_sources`, `sync_history`, `sync_match_revisions`, `sync_settings` (singleton),
`sync_worker_state` (singleton). Apply with `cd backend && .venv/bin/alembic upgrade head`.

## Configuration (`backend/.env`)

`GAMEDATA_DIR`, `SYNC_ARCHIVE_DIR`, `SYNC_STAGING_DIR`, `SYNC_DEFAULT_INTERVAL_HOURS`,
`SYNC_HTTP_TIMEOUT_SECONDS`, `SYNC_MAX_ARCHIVE_BYTES`, `SYNC_MAX_UNCOMPRESSED_BYTES`,
`SYNC_MAX_MEMBER_BYTES`, `SYNC_ENABLE_ALL_JSON`, `SYNC_ENABLE_IPL_JSON`,
`SYNC_ENABLE_T20I_JSON`. Relative paths resolve against `backend/`.

## Tests

```bash
cd backend && .venv/bin/python -m pytest tests/integration/test_cricsheet_sync.py
```

The suite creates and drops a separate `<db>_sync_test` database; it never writes to
the CPI database. Archives are built from real Cricsheet files in
`tests/fixtures/cricsheet/` and served by a local HTTP server.
