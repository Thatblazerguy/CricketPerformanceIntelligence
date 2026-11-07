# CPI: Cricket Performance Intelligence — Progress Log

## Cricsheet migration and intelligence rebuild (2026-11-07)

- Began an archive-wide audit of `gamedata/` (23,241 JSON match files; README and license are also present).
- Captured a pre-migration PostgreSQL custom-format backup at `data/backups/cpi_db_pre_cricsheet_migration_20261107.dump` (87 MB).
- Baseline database before this migration: 7,940 matches, 16,235 innings, 2,235,224 deliveries, 9,937 players; formats: ODI 184, Other 290, T20 1,618, T20I 5,783, Test 65.
- Started incremental ingestion through the existing checksum-idempotent importer. At the latest checkpoint, 9,800 of 23,241 source files had been processed, with 6,534 newly inserted, 3,266 skipped, and no failures. Imports commit in 500-file batches.
- Added a durable per-file ingestion CSV log to future runs and an archive/database reconciliation utility (`backend/scripts/audit_gamedata.py`) that writes `DATA_AUDIT.md` against the pre-migration dump. The active ingestion process started before the logging change, so its counts will be reconciled from the final database state.
- Remaining: finish the active migration, generate and review the audit, validate target-player statistics and format separation, address role-aware similarity/scouting and player enrichment, and run the requested automated validation suite.
- Implemented a dedicated bowling feature matrix and role-specific KNN endpoint (`/players/{player_id}/similar-bowlers`) with bowling-only features, minimum sample thresholds, and match/difference explanations. Added unit tests for ranking and missing phase data (2 passing).
- Implemented an all-rounder similarity endpoint (`/players/{player_id}/similar-all-rounders`) that requires qualifying batting and bowling usage, fits separate feature spaces, and combines their scores with equal 50/50 weights. Added unit tests validating both-discipline eligibility and score composition.
- Replaced the profile's misleading batter/bowler role heuristic with sample-gated usage classification. Explicit `primary_role` metadata wins; otherwise the profile reports a specialist or all-rounder category, plus classification source and confidence. Added unit tests for occasional bowling and explicit wicketkeeper metadata.
- Integrated Batter/Bowler similarity modes into the existing player profile. Corrected similarity percentages to display on a 0–100 scale. Frontend production build passes.

## Current Status: Archive migration and role-aware player intelligence implemented

## Performance, reference-data and phase work (2026-11-07)

- Players directory now starts with no request; submitting a non-empty search requests a paged player summary. Format and role filters are applied server-side. Directory results contain basic sourced bio fields only, and the player list caps page size at 100. Bio attributes are fetched in one batch instead of one SQL query per player.
- Matches page now starts with no request and has submit-driven filters for format, text, competition, team, venue, country, year range and dates. It requests paged summaries; list summary lookup changed from per-row `db.get()` calls to batched team/venue/tournament lookups. Added a separate single-match innings/delivery endpoint and lazy detail route.
- Inspected all four supplied reference CSVs and copied them under `data/reference/cricsheet/`. Applied the Alembic migration and identifier-only importer: 4,737 player-name aliases, 15,088 sourced unique-name attributes, 279 venue aliases and 26 standardized venue names. 3,380 Cricsheet people identifiers did not map to a player present in this dataset; there were no fuzzy name merges.
- Consolidated venue identity by exact Cricsheet registry ID: merged 32 duplicate venue rows and relinked 1,296 matches, preserving source spellings as venue aliases. Match summaries and filter metadata now use standardized venue names, and future ingestion checks registry IDs before creating venue rows.
- Replaced T20-only phase assignment with T20/T20I and ODI/ODM boundaries; Test/MDM phases now use `unknown`, and super overs remain separate. Recalculated **3,432,250** changed delivery phase labels; validation shows Test and MDM now have only `unknown`, while the limited-overs formats use their format-appropriate boundaries. See `PHASE_RULES.md`.
- Audited the exact Cricsheet event name `ICC Cricket World Cup`: found 39 2023 ODI files and verified all 39 are returned by the exact competition, ODI and year filters. Opening one lazily returned two innings/569 deliveries. Detailed list and source-ID evidence: `data/reports/world_cup_2023_audit.md`.
- Created `PERFORMANCE_AUDIT.md` and recorded local single-run timings for players (174.5 ms on KL Rahul ODI search), matches (73.6 ms for 39 World Cup summaries), and one match detail (65.0 ms including extras and wickets). These are not benchmark distributions. Query counts are stated as structural code counts, not DB telemetry.
- Final follow-up: match details now include innings batting teams, ball-by-ball extras and wicket details. Confirmed alias search `K L Rahul` returns canonical KL Rahul; exact World Cup search returns 39 rows across 10 standardized venues; match/delivery totals remain 23,241 / 11,739,488; venue source IDs have no remaining duplicate groups.
- Full test run reached 145 passed and one failure because the matchup phase test expected three phases without a format filter. The behavior is now intentionally format-scoped; the test now requests T20 and passes when rerun. Unit/parser suite passes 117/117; compileall and frontend production build pass.
- Remaining: measure repeated latency and production query plans; split player profile career summary from advanced analytics requests; represent innings progression bands for Test/MDM; support revised innings-length phase adjustments; and extend every analytics view to expose the non-limited-overs progression model. API/database functionality validated on the local DB after applying migration and phase refresh.

### 2026-11-07 completion update

- Completed the full `gamedata/` migration. The archive contains 23,241 structurally valid, unique source matches; the database now contains 23,241 Cricsheet matches, 51,428 innings, and 11,739,488 deliveries across MDM, ODI, ODM, T20, T20I, and Test. The 23,241 source files remain preserved under `gamedata/`.
- Created and verified the pre-migration database backup at `data/backups/cpi_db_pre_cricsheet_migration_20261107.dump`. Import is incremental and checksum-idempotent; namespace collisions and 24 legacy duplicate rows were reconciled without deleting distinct matches. Format reconciliation corrected 4,336 domestic multi-day/one-day matches.
- Added source-file action/error logging and reconciliation tooling. `DATA_AUDIT.md` contains match coverage by format, year, and competition plus innings/delivery counts. The final attempt to regenerate the audit's per-file migration status CSV was blocked when the sandbox denied PostgreSQL access; the already-generated `DATA_AUDIT.md` remains from the successful database reconciliation before that restriction.
- Resolved requested established player identities using Cricsheet registry IDs; preserved aliases and source names, separated the unrelated Indonesian Rohit identity, and added sourced DOB/role/style attributes for the six requested India players. Age is calculated dynamically. KL Rahul has 67 Test and 87 ODI match appearances in this imported archive, with T20 and T20I kept separate; these are archive-derived counts, not asserted global career totals.
- Rebuilt profile role classification around explicit metadata and sample-gated batting/bowling usage. Added format-scoped bowler-only similarity and a balanced all-rounder similarity model with separate batting and bowling vectors, sample thresholds, and explanations. Updated the profile UI and directory role display.
- Added unit coverage for format parsing, roles, missing-value handling, bowling similarity, and all-rounder similarity. Focused unit/parser suite: 114 passed. Frontend production build passes.
- Full `pytest -q`: 114 passed; 29 database integration tests could not run successfully because PostgreSQL connections from the test process are denied by the current sandbox (`Operation not permitted` to localhost:5432). The tests failed at database connection rather than assertions in the changed analytics paths. Targeted live DB validation was performed during implementation before this sandbox restriction surfaced.
- Remaining scope: the existing scouting endpoint and UI still provide batting-oriented ranking only; role-specific bowler/all-rounder scouting and the full set of user-requested filters are not complete. Advanced phase/pace-spin/venue/year/recent-form analytics coverage and ML quality benchmarking/training metadata also need further work. Do not treat this update as claiming those requested pieces are finished.

---

## Completed Milestones

### Milestone 1: Dataset Inspection & Data Engineering
- Inspected raw Cricsheet data files across IPL (1,243 matches) and Men's T20I (5,851 matches).
- Generated `docs/data-dictionary.md` mapping metadata, innings, overs, deliveries, extras, wickets, and player registries.
- Generated `docs/cricket-rules.md` formally standardising scoring conventions (legal deliveries, balls faced, bowling runs conceded, wicket credit, phase assignments, and boundary events).
- Built `CricsheetParser` supporting schema 1.3.0 with SHA-256 source checksums and revision tracking.

### Milestone 2: Canonical Database & PostgreSQL
- Designed normalised relational schema with UUID primary keys and provider separation:
  - `providers`, `tournaments`, `teams`, `team_aliases`, `players`, `player_aliases`, `player_attributes`, `venues`, `matches`, `match_innings`, `deliveries`, `delivery_extras`, `wickets`, `raw_matches`, `ingestion_runs`.
- Configured Alembic migrations (`migrations/versions/52035044457b_initial_schema.py`) and applied all tables.
- PostgreSQL 16 installed and running locally with database `cpi_db`.

### Milestone 3: Ingestion Pipeline
- Implemented `MatchImporter` with complete idempotency (checksum-based change detection, deletion of obsolete child innings on revisions, zero duplicates on re-runs).
- Implemented `IngestionOrchestrator` with transaction boundaries and audit run logging in `ingestion_runs`.
- Ingested real ball-by-ball matches (over 4,200 matches and 970,000+ deliveries in database).

### Milestone 4: Cricket Analytics Engine
- Implemented pure deterministic analytics modules:
  - `app/analytics/batting.py`: Matches, innings, runs, not-outs, dismissals, batting average, strike rate, balls faced, 4s/6s, boundary percentage, dot-ball percentage, highest score.
  - `app/analytics/bowling.py`: Overs, legal balls, runs conceded, wickets, economy rate, bowling average, bowling strike rate, dot-ball percentage, boundary percentage.
  - Phase-wise breakdown: Powerplay (overs 1–6), Middle (overs 7–15), Death (overs 16–20).
  - Bowler-credited wickets isolated from fielding-only dismissals (e.g. run outs).
  - Extras properly categorized (byes/legbyes excluded from bowler economy, wides/noballs included).

### Milestone 5: FastAPI Backend API
- Implemented and validated REST endpoints:
  - `GET /api/v1/health`: Service & database connectivity check.
  - `GET /api/v1/dataset/coverage`: Dataset coverage, tournament counts, format breakdown, seasons list.
  - `GET /api/v1/players`: Paginated player listing with search.
  - `GET /api/v1/players/{id}`: Player details.
  - `GET /api/v1/players/{id}/batting`: Batting metrics with filter by format, competition, season.
  - `GET /api/v1/players/{id}/bowling`: Bowling metrics with overs formatting and rate stats.
  - `GET /api/v1/players/{id}/phases`: Phase-wise split for batting and bowling.
  - `GET /api/v1/players/{id}/similar`: Machine learning player similarity endpoint.
  - `GET /api/v1/matches`: Paginated match list and match details.
  - `GET /api/v1/matchups/{batter_id}/{bowler_id}`: Head-to-head metrics with sample-size warnings, fours, sixes, dot-ball %, boundary %, and phase breakdown.
  - `GET /api/v1/venues`: Ground statistics and 1st/2nd innings scoring averages.
  - `GET /api/v1/teams` & `GET /api/v1/teams/{id}`: Team performance, win %, batting-first vs chasing splits.
  - `POST /api/v1/scouting/search`: Multi-criteria weighted scouting ranker with strengths and caveats.
  - `POST /api/v1/ingestion/run-sync`: Ingestion triggering.

### Milestone 6: Machine Learning
- Implemented `PlayerSimilarityEngine` in `app/ml/similarity/model.py`:
  - Feature extraction across 8 core metrics (batting average, strike rate, boundary %, dot-ball %, phase strike rates, volume).
  - `StandardScaler` feature normalisation.
  - `NearestNeighbors` with cosine distance metric.
  - Explainable similarity outputs detailing the top statistical alignments.
- Implemented transparent, explainable scoring in `app/api/routes/scouting.py` with percentile ranking and auto-normalized weights.

### Milestone 7: Professional React + Vite Frontend
- Production-grade UI built using React 18, Vite, and Tailwind CSS in dark navy sports analytics aesthetic.
- Key views:
  - **Dashboard**: Dataset statistics, format coverage, seasons overview, recent matches.
  - **Players**: Searchable player directory with pagination and quick links.
  - **Player Profile**: Batting figures, bowling figures, phase breakdown table, visual run distribution bars, phase strike rate meters, ML cosine similarity recommendations, and one-click CSV export.
  - **Player Comparison**: Side-by-side comparison of up to 3 players with full database search, A-Z letter drawer, popular rivalry quick presets (e.g. Kohli vs Rohit, Russell vs Pollard), and visual phase strike rate meters.
  - **Matchups**: Head-to-head batter vs bowler analytics with access to the entire database (9,937 players), live debounced search, alphabetical A-Z browser drawer, famous rivalry presets, phase breakdowns (Powerplay/Middle/Death), and CSV export.
  - **Scouting Workspace**: Interactive priority weights, minimum sample thresholds, ranked candidates with strengths/limitations, and candidate shortlist CSV export.
  - **Teams & Venues Hub**: Tabbed dual-view interface:
    - *Grounds & Venues*: Average 1st/2nd innings scoring benchmarks, high-scoring/bowling-friendly classifications, and CSV export.
    - *Team Records & Splits*: 129 teams with matches played, overall win %, visual win/loss ratio bar, Batting First vs Chasing split gauges, tactical toss insight, and team CSV export.

### Milestone 8: Complete Matchup Analysis Overhaul
- Ingested 1,000 matches from `gamedata/` (881 new matches, bringing the total to 7,940 matches, 2,235,224 deliveries, and 9,937 players).
- Implemented comprehensive Matchup endpoints:
  - `GET /api/v1/matchups/filter-metadata`: Dynamic years, formats, competitions, venues.
  - `GET /api/v1/matchups/{batter_id}/{bowler_id}/summary`: Overall metrics, phases, innings breakdown.
  - `GET /api/v1/matchups/{batter_id}/{bowler_id}/dismissals`: Dismissal analysis distinguishing bowler-credited wickets from fielding dismissals.
  - `GET /api/v1/matchups/{batter_id}/{bowler_id}/by-match`: Detailed match-by-match log.
  - `GET /api/v1/matchups/{batter_id}/{bowler_id}/by-over`: Over-by-over analysis.
  - `GET /api/v1/matchups/{batter_id}/{bowler_id}/trends`: Performance trends over time.
- Rebuilt `frontend/src/features/matchups/Matchups.jsx` with full database player selectors, comprehensive filters, dismissals breakdown, interactive chart trends, and CSV export.

### Milestone 9: Players Page Performance Intelligence & Multi-Format Filtering
- **Strict Format Separation**:
  - Differentiated domestic/franchise `T20` (1,618 matches) from international `T20I` (5,783 matches) alongside `ODI` (184 matches) and `Test` (65 matches).
  - Both categories operate strictly independently.
- **Pace vs Spin Bowling Style Seeding**:
  - Seeded 166 prominent international and franchise bowlers into `player_attributes` (`attribute_type = 'bowling_style'`, values `'pace'` or `'spin'`).
  - Enabled delivery-level batting splits against pace and spin.
- **Backend Performance Intelligence Endpoints**:
  - `GET /api/v1/players/filter-metadata`: Dynamic formats, years (2005–2026), venues (384), teams (221), and bowling styles.
  - `GET /api/v1/players/performance`: Unified CTE aggregation calculating batting metrics, bowling metrics, phase splits (PP/Mid/Death), pace/spin splits, dismissal tallies, opponent team filtering (`vs_team_id`), venue filtering (`venue_id`), multi-metric threshold gates, sorting, and pagination in a single query.
- **Frontend Performance UI**:
  - Format toggle pills (`All Formats`, `T20I`, `T20`, `ODI`, `Test`).
  - Expandable filter drawer with sections for Timeline, Context, Batting Ranges, Bowling Ranges, Pace/Spin Splits, Phase SRs, and Sample Gates.
  - Active filter badges with one-click dismiss ('×') and "Reset All Filters".
  - View mode tabs (`All Stats`, `Batting Focus`, `Bowling Focus`, `Pace/Spin & Phases`).
  - Click-to-sort column headers, CSV export, and responsive pagination.
- **Testing & Quality Assurance**:
  - Added 9 comprehensive integration tests in `backend/tests/integration/test_player_performance.py` (all 9 passed in 46s).
  - 121 total backend tests passing without a single failure.
  - Frontend production build succeeds cleanly in 767ms.

### Milestone 10: Clean Separation of Players Directory & Comprehensive Player Profile
- **Players Directory Refactoring** (`frontend/src/features/players/Players.jsx`):
  - Streamlined into a clean, fast player discovery directory.
  - Retained essential metrics only: **Player Name**, **Role** (Batter/Bowler/All-Rounder badge), **Matches**, **Runs**, **Batting Average**, **Strike Rate**, **Wickets**.
  - Retained format selectors (`All Formats`, `T20I`, `T20`, `ODI`, `Test`), role toggles (`All Roles`, `Batters`, `Bowlers`, `All-Rounders`), player name search, click-to-sort columns, and pagination.
  - Removed cluttering advanced columns (pace/spin splits, phase metrics, death economy, etc.) from the directory table for speed and discovery clarity.
- **Individual Player Profile Workspace** (`frontend/src/features/players/PlayerProfile.jsx`):
  - Created a comprehensive individual player analytics workspace consolidating all detailed stats:
    1. *Career & Filtered Benchmarks*: Full batting (runs, avg, SR, balls, 4s, 6s, highest score, not outs, bound %, dot %) and bowling (wickets, economy, avg, SR, overs, runs conceded, dot %).
    2. *Pace vs Spin Analytics*: Head-to-head vs Pace and vs Spin (runs, balls faced, SR, average, boundaries, dot ball %).
    3. *Phase-by-Phase Performance*: Powerplay (1–6), Middle (7–15), and Death (16–20) breakdown with visual indicators.
    4. *Multi-Format Comparison*: Side-by-side comparison across Test, ODI, T20, and T20I.
    5. *Opponent & Venue Splits*: Performance against different opponent teams and grounds.
    6. *Career Trajectory & Recent Form*: Year-by-year trajectory and last 10 matches log.
    7. *Automated Strengths & Weaknesses*: Contextual insights generated from actual delivery-level splits.
    8. *Machine Learning Similarity*: Nearest-neighbor profile recommendations with match percentages.
  - Added dynamic profile-level filters: **Format**, **Start Year**, **End Year**, **Season**, **Opponent Team**, **Venue**, **Bowler Style (Pace vs Spin)**, and **Match Phase**.
  - Added one-click **Export Profile CSV**.
- **Backend Analytics Endpoint** (`backend/app/api/routes/players.py`):
  - Added `GET /api/v1/players/{player_id}/analytics` delivering all aggregated splits, opponent records, venue stats, and trajectory in a single optimized query response.
- **Testing & Verification**:
  - Added 3 new integration tests (`test_player_profile_analytics_unfiltered`, `test_player_profile_analytics_filtered`, `test_bowler_profile_analytics`) to `backend/tests/integration/test_player_performance.py` (12/12 passed in 48.96s).
  - Frontend production build verified in 778ms.

### Milestone 8: Complete Matchup Analysis Overhaul & Multi-Format Ingestion
- **Dataset Investigation**:
  - Examined the 23,241 Cricsheet JSON files (v1.3.0) in `gamedata/` spanning Test (923), ODI (3,237), T20 (14,425), MDM (2,242), ODM (2,094), IT20 (320) matches from 2001 to 2026.
  - Identified why the previous matchup view lacked depth: the backend only exposed an un-paginated single-call endpoint without year ranges, match-by-match breakdowns, dismissal categorizations, or over-by-over aggregates.
  - Added composite index `CREATE INDEX ix_deliveries_batter_bowler ON deliveries (batter_id, bowler_id);` for instant sub-10ms delivery lookups.
  - Implemented `backend/scripts/ingest_gamedata.py` supporting all match types with `wi_` prefix handling.
- **Dedicated Matchup API Endpoints (`backend/app/api/routes/matchups.py`)**:
  - `GET /api/v1/matchups/filter-metadata`: Dynamic years, formats, competitions, teams, and venues from actual database records.
  - `GET /api/v1/matchups/{batter_id}/{bowler_id}/summary`: Complete summary with year range, format, tournament, season, innings, phase, and over filters.
  - `GET /api/v1/matchups/{batter_id}/{bowler_id}/dismissals`: Bowler-credited wickets vs non-credited dismissals (run outs, obstructing field) broken down by dismissal type.
  - `GET /api/v1/matchups/{batter_id}/{bowler_id}/by-match`: Detailed match-by-match table with pagination, sorting by date, runs, balls, or strike rate.
  - `GET /api/v1/matchups/{batter_id}/{bowler_id}/by-over`: Over-by-over aggregate distribution across overs 1 to 20+.
  - `GET /api/v1/matchups/{batter_id}/{bowler_id}/trends`: Year-by-year head-to-head trajectory and innings-by-innings split.
- **Frontend Matchup Interface (`frontend/src/features/matchups/Matchups.jsx`)**:
  - Player search across the full database with debounced input and A-Z letter drawer.
  - Comprehensive filter panel: Year range (from/to dynamically populated), Format (T20, ODI, Test, Other), Competition, Innings, Phase (Powerplay, Middle, Death), Custom over range (1–80), Venue, Season, and sample gate.
  - Tabbed analytical workspace:
    - *Summary*: Stat cards, ball outcome distribution bar (sixes, fours, singles, dots), balls faced, strike rate, average.
    - *Phase Breakdown*: Powerplay, Middle, Death scoring rates, dismissal tallies, boundaries, and strike rate meters.
    - *Dismissals*: Bowler wickets vs non-bowler outs with credit badges.
    - *Over-by-Over*: Interactive bar chart highlighting wicket overs and high-scoring overs alongside granular table.
    - *Trends*: Year-wise runs bar chart, year progression table, and innings performance splits.
    - *Match-by-Match*: Paginated match log with team names, venue, date, balls, runs, dismissal info, and CSV export.

---

## Verification & Test Results
- **Backend Tests**: 120/120 passing (`backend/.venv/bin/pytest tests/unit/ tests/integration/ -v`).
  - Added `tests/integration/test_matchup_endpoints.py` validating metadata, summary, year range filtering, dismissals, by-match pagination, by-over, trends, and non-existent pairs.
- **Frontend Build**: Verified clean production build (`npm run build` in `frontend/`) in 1.12s with zero warnings or errors.
- **Database**: PostgreSQL 16 indexed with composite seek on `deliveries(batter_id, bowler_id)`. Active records: **7,940 matches**, **2,235,224 deliveries**, **9,937 players** across T20, ODI, Test, and Other formats.

---

## Files Created & Modified

### Backend
- `backend/requirements.txt`: Pinned dependencies.
- `backend/app/core/config.py`: Environment configuration.
- `backend/app/domain/enums.py`: Domain enumerations.
- `backend/app/domain/entities.py`: Canonical dataclasses.
- `backend/app/domain/cricket_rules.py`: Authoritative cricket calculation engine.
- `backend/app/models/models.py`: SQLAlchemy declarative schema (14 tables).
- `backend/app/db/session.py`: Database connection & session factory.
- `backend/app/db/base.py`: Model imports for Alembic.
- `backend/app/ingestion/providers/base.py`: Provider interface.
- `backend/app/ingestion/providers/cricsheet.py`: Cricsheet JSON parser.
- `backend/app/ingestion/providers/cricsheet_file.py`: File-based provider implementation.
- `backend/app/ingestion/importer.py`: Idempotent match importer.
- `backend/app/ingestion/sync.py`: Ingestion orchestrator.
- `backend/app/analytics/batting.py`: Batting analytics functions.
- `backend/app/analytics/bowling.py`: Bowling analytics functions.
- `backend/app/ml/features/player_features.py`: Feature matrix generator.
- `backend/app/ml/similarity/model.py`: ML KNN cosine similarity model.
- `backend/app/api/routes/health.py`: Health & coverage API.
- `backend/app/api/routes/players.py`: Players & similarity API.
- `backend/app/api/routes/matches.py`: Match listing & detail API.
- `backend/app/api/routes/analytics.py`: Matchups & venue stats API.
- `backend/app/api/routes/scouting.py`: Scouting ranking API.
- `backend/app/api/routes/ingestion.py`: Ingestion execution API.
- `backend/app/main.py`: FastAPI application entrypoint.
- `backend/scripts/inspect_cricsheet.py`: Inspection utility.
- `backend/scripts/ingest.py`: CLI ingestion runner.
- `backend/scripts/setup_db.py`: Migration runner.
- `backend/migrations/`: Alembic configuration and initial migration.

### Frontend
- `frontend/package.json` & `frontend/vite.config.js`: Build and dev server configuration.
- `frontend/tailwind.config.js` & `frontend/postcss.config.js`: Tailwind styling configuration.
- `frontend/index.html`: Entrypoint.
- `frontend/src/main.jsx`: React root mounting.
- `frontend/src/App.jsx`: Route hierarchy.
- `frontend/src/services/api.js`: Unified backend API client.
- `frontend/src/hooks/useApi.js`: Reactive request hook.
- `frontend/src/components/ui.jsx`: Shared atomic UI components (StatCard, Table, Badge, LoadingSpinner, SampleWarning).
- `frontend/src/components/Sidebar.jsx`: Navigation bar.
- `frontend/src/components/Layout.jsx`: Responsive layout container.
- `frontend/src/features/dashboard/Dashboard.jsx`: Overview dashboard.
- `frontend/src/features/players/Players.jsx`: Player directory.
- `frontend/src/features/players/PlayerProfile.jsx`: Comprehensive player profile with ML similarity.
- `frontend/src/features/comparisons/PlayerComparison.jsx`: Multi-player comparison.
- `frontend/src/features/matchups/Matchups.jsx`: Batter vs bowler head-to-head.
- `frontend/src/features/scouting/Scouting.jsx`: Scouting tool with custom weights.
- `frontend/src/features/venues/Venues.jsx`: Venue ground stats.

### Documentation & Tests
- `docs/data-dictionary.md`: Cricsheet data dictionary & schema mapping.
- `docs/cricket-rules.md`: Cricket rules calculation reference.
- `backend/tests/unit/test_cricket_rules.py`: 84 unit tests for legal deliveries, balls faced, dismissal attribution, overs formatting, and averages.
- `backend/tests/unit/test_similarity.py`: Unit tests for ML KNN similarity engine.
- `backend/tests/integration/test_cricsheet_parser.py`: Integration tests against real Cricsheet files.
- `backend/tests/integration/test_api.py`: FastAPI endpoint tests against PostgreSQL.

---

## Tests Performed
- **109 / 109 automated tests passing** across unit and integration suites (`pytest tests/unit/ tests/integration/ -v`).
- **Idempotency verification**: Ingestion of identical matches verified (0 duplicates inserted, existing records safely skipped).
- **Frontend build test**: Clean production build via `npm run build` (0 warnings).

---

## Known Issues / Future Enhancements
- Bowler style metadata (e.g., right-arm offbreak, left-arm fast) is not natively present in raw Cricsheet JSON; when available from supplementary sources, pace vs spin splits will auto-populate via `player_attributes`.
- Full archive reconciliation can be scheduled periodically to fetch newly updated match files from Cricsheet.

## Similarity upgrade (2026-11-07)
- Added a 5-minute process-local cache for format- and threshold-specific bowler/all-rounder feature matrices and fitted cosine models. Cache invalidation is exposed for ingestion/refresh workflows.
- Specialist bowler comparisons now exclude players with qualifying batting usage; all-rounder comparisons require qualifying samples in both disciplines.
- Similarity endpoints return up to 10 results. The profile UI requests 10 and displays pending state across all three similarity modes. Existing batter similarity behavior and model remain unchanged.
- Validation: targeted similarity tests pass (7/7), Python compilation passes, and the frontend production build passes.

## Player profile role insights and year filters (2026-11-07)
- Profile analytics now generates batting insights for batters, bowling insights for specialist bowlers, and separate batting/bowling insight lists for all-rounders. Bowling insights use economy, average, strike rate, wickets, dots, phase performance, and recorded pace/spin style metadata.
- Added detailed bowling phase records (legal overs, wickets, runs, economy, average, strike rate, dots and boundaries), phase economy bars and known-style pace/spin splits. T20/ODI/ODM phases use the stored format-aware labels; Test/MDM groups balls into labelled innings progression thirds using the innings' actual length.
- From/To year controls now apply inclusive database date bounds together, validate reversed ranges in the UI and API, and show the applied range. Reset clears both draft and applied date filters.
- Live PostgreSQL validation covered KL Rahul (batter), Jasprit Bumrah (bowler), Ravindra Jadeja (all-rounder), T20 phase rows, Test innings progression, and reversed-year rejection.

## Format-specific scouting system (2026-11-07)
- Replaced batter-only scouting with separate batter, specialist bowler and all-rounder cohorts across Test, ODI, T20I, T20, MDM and ODM. Cohorts are query-filtered in PostgreSQL and cached in process for five minutes.
- Added configurable percentile weights, analyst presets, sample thresholds, verified age/style/team/competition/year filters, metric bounds, missing-metric handling, confidence labels, explainable component scores, pagination, sorting, CSV export and shortlisted-player comparison.
- All-rounder batting and bowling scores are computed independently before their configured weighted combined score. Specialist bowler scoring does not use batting metrics. Phase objective presets require phase sample availability.
- Validation: 102 unit tests pass, the scouting API integration test passes, production frontend build passes, and live database searches returned separate T20/T20I, ODI bowler and ODI all-rounder cohorts.

## Auction Intelligence foundation (2026-11-07)
- Audited the existing CPI architecture and documented integration boundaries and the phased delivery path in `AUCTION_ARCHITECTURE.md`.
- Added scenario-scoped auction persistence tied to canonical CPI player IDs: scenarios, versioned rules, franchises, pool players, retentions, import reports, sessions, bids, append-only events and purchases.
- Added FastAPI routes for scenario creation/list/detail, franchise creation, JSON player-pool identity preview/import, team summaries, session creation, player calls, validated bids, sold/unsold close and event history.
- Added a CPI Auction Intelligence navigation page for scenario setup, franchise purse entry and player-pool identity preview/import.
- Price and destination predictions remain unavailable until real auction history is imported. CSV/XLSX adapters, retention/squad imports, manual identity resolution, requirements engine, optimiser and AI agents remain future phases; no auction outcomes were fabricated.
- Validation: app imports and exposes 12 auction routes; Alembic migration applied and confirmed at head; 105 backend unit tests pass; frontend production build passes. A live PostgreSQL API smoke flow passed scenario creation, exact canonical player pool import, player call, valid bid, sale, and ordered event retrieval. Only the temporary smoke scenario and its child records were removed; existing cricket data was untouched.

## Auction history CSV import and price-model training (2026-11-07)
- Added historical auction CSV preview/import with bounded file size/row count, flexible source columns, INR/crore/lakh normalization, stable per-source transaction checksums, idempotent duplicate handling, validation reports and import history.
- Bundled the two requested public auction datasets and outside-edge player registry under `data/auction/sources/`. Player names/aliases are resolved to CPI IDs only on an unambiguous match; unresolved and ambiguous rows remain explicitly tagged. Sold, retained and unsold outcomes remain distinct.
- Added a Scikit-learn sold-price regression baseline using an imputed/one-hot feature pipeline, prior-auction-only price/count features, chronological holdout evaluation and a persisted versioned model artifact/training record. No unsold/retained record is treated as a sale, and cross-source repeated transactions are deduplicated for training.
- Added a historical data upload/import/training view to Auction Intelligence. Existing player-pool CSV support remains available.
- Local DB import: 3,597 stored records (2,627 outside-edge and 970 Rixabhh); 2,403 positive sold-auction source rows; 1,562 deduplicated training transactions. Validation holdout: 456 transactions across 2021, 2022, 2023 and 2026; MAE 197.306 lakh vs 222.094 lakh median baseline (R² 0.0606). Import re-run preserved the 3,597 stored row count.
- Validation: auction CSV/model unit tests 3/3 and existing auction rule tests 3/3 pass; FastAPI imports successfully (54 routes); Alembic migration `20261107auc2` applied; frontend production build passes. Detailed source provenance and metrics are in `data/auction/SOURCES.md` and `AUCTION_ARCHITECTURE.md`.

## Auction intake correction: retention list and player pool (2026-11-07)
- Replaced manual franchise/purse setup and pool JSON entry with exactly two scenario CSV upload flows: full retention list and player pool. Franchises are created from retention-list team values; no manual purse input is required.
- Added retention CSV preview/import. It accepts team/franchise + player columns, optional price/category/order, preserves absent retention prices as NULL, and reports missing/ambiguous players. Applied migration `20261107auc3` for nullable retained prices.
- Identity matching now joins Cricsheet `names.csv` spellings through CPI's stable source identifiers, handles safe initial/surname variants, and rejects multi-player ambiguous matches. Added the user-provided Spencer Johnson → Cricsheet ID `83c3e8e3` / CPI `SH Johnson` correction in a separate provenance-labelled alias override file.
- Kept previous-auction repository training available as a button with no additional CSV control; therefore the scenario import UI has only the two requested CSV inputs.
- Validation: 8 focused auction tests pass; frontend production build succeeds; live PostgreSQL preview resolved Spencer Johnson to `SH Johnson` for both retention and player-pool uploads without writing preview data.

## Run Scenario team needs and bid analysis (2026-11-07)
- Added the `POST /auction/scenarios/{id}/run` analysis endpoint and a Run Scenario UI action with per-franchise role gaps, candidate recommendations, estimated bids in INR lakh/crore, historical team-sample confidence and model validation context.
- Team needs are calculated from roles in the retention CSV against configurable scenario role targets (defaults: 6 batters, 6 bowlers, 4 all-rounders, 2 wicketkeepers). Recommendations include only uploaded pool players who match a team's identified role gap.
- Added normalized franchise identity to the historical price-model feature set, retrained the local model, and batch-predict all team/player prices per scenario. Local validation returned results for 10 teams in about 0.1s after model load; sample recommendations show franchise-specific bid differences.
- Bid amounts are explicitly displayed as model estimates, not actual franchise budgets or guaranteed bids. Confidence reflects the number of historical sales for that franchise.
- Validation: Run Scenario service returns team needs and price suggestions for existing DB scenarios; 10 focused auction tests pass; frontend production build and app route import pass.

## Auction rules, predicted XI and player-data fallback (2026-11-07)
- Added editable, scenario-versioned squad and overseas rules with IPL limits, PDF/DOCX/CSV/TXT text extraction, manual confirmation and validation against existing franchise rosters.
- Added explainable Playing XI generation from retained and purchased squad members only. It uses CPI T20 batting/bowling aggregates, role metadata, wicketkeeping, phase evidence and pace/spin style where present; enforces overseas limits and stores the generated XI with its rules version.
- Added Cricket Database API integration through server-side `CRICKET_DATABASE_API_KEY` configuration. Provider IDs, basic stats and source mappings are cached in new tables; unresolved upload names become minimal records, CPI aliases are checked first, and existing attributes are not overwritten.
- Player detail now reports source and availability, and displays the required notice with external basic statistics when CPI delivery analytics are unavailable.
- Added unit coverage for rule parsing, squad/XI restrictions, missing metrics and duplicate-safe minimal-profile fallback.
- Validation: 16 focused auction tests pass; Vite production build passes; Alembic history resolves new migration `20261107auc4` as head. Migration could not be applied against PostgreSQL because the local database connection was unavailable in this environment. PDF extraction dependency `pypdf` is in requirements; it could not be installed here because network access to the package index was unavailable.
- Follow-up XI runtime fix: applied migration `20261107auc4` to local PostgreSQL, corrected phase-wicket tuple mapping, and changed missing nationality handling to generate a provisional XI with explicit overseas-cap validation warnings. Live scenario verification returned HTTP 200 with 11 players; nationality is missing for 10 selected players in that squad, so the overseas cap remains unverified.

## Player nationality coverage backfill (2026-11-07)
- Added `player_nationality_evidence` with nationality, source, verification status, confidence, evidence count, date range and details; applied migration `20261107nat1`.
- Backfill resolves existing profile data first, then Test/ODI/T20I player appearances from the actual represented team. It excludes domestic/franchise matches and composite invitational XIs, preserves affiliation history, marks overlap conflicts for review and stores `Unknown` when evidence is insufficient. It does not derive nationality from IPL overseas status or birthplace.
- Cricket Database fallback makes exact normalized-name requests only, caches provider IDs against existing CPI players and refuses ambiguous or already-mapped provider IDs. Unresolved lookup attempts are cached for 30 days.
- Future Cricsheet imports now write match-scoped international evidence; future unresolved imports are explicitly tagged `Unknown` for review. Auction upload values `Indian`/`Overseas` are no longer stored as country names.
- Live DB audit: 15,133 players; 8,684 known nationalities (57.38%); 6,449 unresolved; 144 conflicting cases after excluding composite XIs and clearing stale conflict flags. The API fallback queried 6,513 initially unresolved records and found one exact nationality; current unresolved lookups are cached to avoid repeated calls. Player, match, innings and delivery counts stayed unchanged at 15,133 / 23,241 / 51,428 / 11,739,488. See `NATIONALITY_AUDIT.md` for IDs and evidence details.
- Validation: nationality, auction regression and Cricsheet parser tests pass (36/36); Python syntax validation passes. Full suite run against the local database reached 43 passing tests and was interrupted after five minutes while a data-heavy player analytics integration test was still running; the restricted run's integration failures were database connection-denied errors.

## Ground-level analytics upgrade (2026-11-07)
- Replaced the all-venue N+1 ball-stat queries with a lightweight format-filtered ground directory and on-demand ground details. Added a five-minute in-process cache keyed by canonical venue and format group.
- Added ODI/ODM, T20/T20I and Test/MDM group filters, innings scoring and wickets, team totals, toss and batting-first/chasing outcomes, stored-format/year comparisons, and pace/spin bowling rates and phase breakdowns. Unknown bowling styles are excluded from pace/spin and counted separately; super overs are excluded from regular innings metrics.
- Phase scoring uses T20 and ODI rules per stored format. Test and MDM are shown as labelled 20-over innings-progression bands, never powerplay/middle/death. Only observed deliveries count, so shortened innings do not receive imputed overs.
- Ground list now loads detail only after selection and displays sample sizes, charts, limitations and thresholded insights in the existing dark UI.
- Live PostgreSQL spot checks matched independent match and innings aggregates: T20 at Shere Bangla National Stadium (341 matches, 271 T20 + 70 T20I); ODI at Harare Sports Club (139 matches, 133 ODI + 6 ODM); Test at Lord’s (113 matches, 43 Test + 70 MDM). Test phase labels were verified as innings progression bands.
- Validation: 112 targeted backend tests pass; frontend Vite production build passes. The full data-heavy backend suite was not completed in the available run.

## Teams & Venues records and recent-form filters (2026-11-07)
- Reworked team records to fetch a filtered set of match-level rows in one indexed query, with first-innings data pre-joined. Added win/loss/tie/no-result/unresolved classification, venue-country and ground splits, opponent records, toss decision/toss-winner splits, batting-first/chasing records, percentages and sample-aware insights.
- Added team format groups (Test/MDM, ODI/ODM, T20/T20I), rolling 1/3/5/10-year and custom inclusive year filters, country and opposition filters. No ball-by-ball table is scanned for team records.
- Extended selected-ground analytics with date filters, last 10/20 match results and innings averages, recent-vs-period scoring comparison, and recent improvement/decline insights when the sample is large enough. Detail cache keys now include date scope and sample size.
- Added team filters and record tables, win/loss breakdowns, home/away evidence disclosure, recent ground results and recent scoring charts in the existing UI. CPI has no verified home-ground metadata for most teams; those records are presented as neutral/unknown rather than guessed.
- Validation: 7 focused team and ground unit tests pass; backend imports 61 routes; frontend production build passes. A live PostgreSQL endpoint smoke call was attempted but the sandbox denied localhost:5432 access, so database-backed endpoint execution could not be verified in this run.

## Team home/away and gender classification correction (2026-11-07)
- Added provenance-aware `teams.country`, `country_source` and `country_confidence` fields with migration `20261107teamcountry`. Backfill uses verified player affiliations from Test/ODI/T20I appearances, with a conservative consistent-tournament-country fallback; it never overwrites an existing country.
- Applied the migration and historical country backfill. 107/404 teams now have high-confidence country mappings; 297 remain unresolved. A composite Africa XI mapping was removed during audit. CPI's existing Cricsheet venue registry has no country column and all 543 `venues.country` values are NULL, so home/away is shown as unknown for matches with unmapped ground country instead of claiming neutral or away. Team records expose this coverage explicitly. Audit: `data/reports/team_country_backfill.json`.
- Team Records now filter by stored match gender (`male`/`female`) across all match outcomes, splits and insights. Default view is Men's; Women's and combined views remain selectable. Live India ODI check returned 529 men's and 135 women's records (664 combined).
- Home/away classification now compares the ground country to both stored team countries; a single matching side is Home and its opponent Away, neither matching with both mappings present is Neutral, and missing mappings stay Unknown. Wins-by-country remains keyed to the ground's country.
- Validation: 14 team unit tests and 3 ground phase tests pass, plus the live team API integration test; frontend production build passes. The country mapping does not populate missing ground countries; a reliable ground-country source must be added before those historical home/away records can be resolved.

## Visualization enhancement (2026-11-07)

- Added reusable responsive SVG bar, line, donut and radar components without introducing a chart package.
- Dashboard now visualizes format coverage and match counts by year from the coverage API.
- Player profiles chart year runs/strike-rate, recent batting runs, format-aware batting phase runs, bowling phase wickets/economy, and available pace/spin splits; server filters still drive the displayed data.
- Player comparison now supports an explicit format and a multi-player radar view over comparable batting/bowling metrics.
- Team records show filtered outcome counts and context win rates. Scouting displays top current-page role-fit scores.
- Auction scenario views chart expected closes, demand scores, remaining franchise purses and historical auction-row coverage. The model section plots actual saved holdout error and sample-size metrics.
- Added `VISUALIZATION_AUDIT.md` documenting the data/API basis and unsupported visualizations that need new sourced or persisted data.
- Verification: frontend production build passed. Read-only backend API integration suite passed (8 tests) against local PostgreSQL. Running that suite inside the restricted sandbox initially failed because localhost PostgreSQL access was denied; the authorized rerun succeeded.

## Ground analytics 500 fix (2026-11-07)

- Reproduced the Ground Analytics 500 against local PostgreSQL: untyped `None` values in `:start_date IS NULL` / `:end_date IS NULL` predicates caused PostgreSQL `AmbiguousParameter` errors on the default All time request.
- Raw analytics SQL now includes date predicates and bind values only when a date filter is actually set.
- Added the selected period to the ground analytics fetch dependencies so changing periods refetches even when the resulting dates are unchanged.
- Live verification passed against Edgbaston: 227 T20/T20I group matches for All time and 79 for 2024–2026. Frontend production build passed.

## Deeper existing-data visualizations (2026-11-08)

- Expanded player profile charts to surface available format splits, batting and bowling phase rates, pace/spin efficiency, opponent/venue runs and strike rates, plus yearly match appearances. Series use existing API aggregates and follow profile filters.
- Expanded Team Records with filtered win-rate charts by venue country, ground and opponent.
- Expanded selected-ground charts for wickets lost by innings, phase/style bowling wickets and economy, toss-decision win rate, recent second-innings scoring, and yearly first-innings scoring trend. Missing values are excluded from mini-bars rather than shown as zero.
- Added a selectable actual performance metric chart to Scouting and demand-versus-price, valuation-versus-close, and model confidence-range visualizations to Auction Scenario.
- Validation: `npm run build` passed. Charts use the existing API payloads; no new dependencies or delivery-table scans were added.

## Advanced player scouting visualizations (2026-11-08)

- Added nationality as a server-side scouting filter and supplied nationality, role, batting-style and bowling-style distributions from the same cached filtered cohort.
- Added a prominent role-colored batting average vs strike-rate scatter with full-cohort reference means, hover details, selected-player highlights and profile navigation. Point rendering is capped at 2,500; distributions and reference means use the full eligible cohort.
- Added side-by-side selected-player metric charts (runs, averages, strike rates, boundary rate, fifties, hundreds, wickets, economy and recent form), recent-match batting lines, and filtered cohort donut charts.
- Added real innings-derived fifties/hundreds and last-five match batting values to the existing cached cohort query path; no player values or names are hardcoded.
- Validation: frontend production build passed; Python route compilation passed. Database-backed API execution was not run in this change.
- Follow-up debug: fixed Scouting's blank-screen `comparePlayers` temporal-dead-zone error by declaring its memoized selection before chart data derivation. Vite production build passes.
- Added a Men’s/Women’s/All genders Scouting filter. Gender is applied to every match-level aggregate and is included in the cohort cache key, keeping table statistics, scatter benchmarks and distribution charts separated. Frontend build and Python route compilation pass.
