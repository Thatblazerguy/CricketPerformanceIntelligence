# Cricket Performance Intelligence (CPI)

## Technical Implementation Plan

**Document:** `implementation.md`\
**Version:** 1.0\
**Status:** Proposed implementation blueprint\
**Companion document:** `PRD.md`

------------------------------------------------------------------------

## 1. Purpose

This document converts the CPI product requirements into an actionable
engineering plan.

It defines: - The implementation sequence. - Repository structure. -
Data ingestion design. - Canonical data model. - Cricket calculation
rules. - Analytics and ML implementation. - API contracts. - Testing and
validation. - Deployment considerations. - Definition of done for each
milestone.

This is an implementation guide, not a request to build every feature at
once. Complete each milestone, validate it and then proceed.

## 2. Architecture Decisions

### 2.1 Use a Modular Monolith

Build one backend application with clearly separated modules: -
`ingestion`: source retrieval and parsing. - `domain`: canonical cricket
entities and rules. - `analytics`: deterministic statistical
calculations. - `ml`: feature generation, training and inference. -
`api`: FastAPI routes and request/response schemas. - `repositories`:
database access. - `reports`: exports.

Do not create separate deployable services for these modules in v1.

### 2.2 Separate Source Data from Canonical Data

Provider-specific JSON must not leak into analytics code.

Each provider adapter converts its source format into a canonical
internal representation. The same analytics functions should work
regardless of which provider supplied a match.

### 2.3 Separate Statistics from ML

A statistic such as batting average is calculated deterministically. It
is not an ML prediction.

A weighted recruitment score is a configurable scoring system unless its
weights are learned and validated from data.

A similarity model or performance predictor is an ML component and must
have a training/evaluation process.

### 2.4 Training Must Be Offline

Do not train models during a user-facing API request.

Train models through a script or scheduled job, evaluate them, save
versioned artefacts and load approved models for inference.

------------------------------------------------------------------------

## 3. Repository Structure

Start with a single repository:

``` text
cricket-performance-intelligence/
│
├── frontend/
│   ├── public/
│   ├── src/
│   │   ├── app/
│   │   ├── components/
│   │   ├── features/
│   │   │   ├── dashboard/
│   │   │   ├── players/
│   │   │   ├── comparisons/
│   │   │   ├── matchups/
│   │   │   └── scouting/
│   │   ├── charts/
│   │   ├── services/
│   │   ├── hooks/
│   │   └── styles/
│   └── package.json
│
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── core/
│   │   │   ├── config.py
│   │   │   └── logging.py
│   │   ├── db/
│   │   │   ├── session.py
│   │   │   └── base.py
│   │   ├── domain/
│   │   │   ├── entities.py
│   │   │   ├── cricket_rules.py
│   │   │   └── enums.py
│   │   ├── models/
│   │   ├── schemas/
│   │   ├── repositories/
│   │   ├── services/
│   │   ├── api/
│   │   │   └── routes/
│   │   ├── ingestion/
│   │   │   ├── providers/
│   │   │   │   ├── base.py
│   │   │   │   ├── cricsheet.py
│   │   │   │   └── opencricket.py
│   │   │   ├── discovery.py
│   │   │   ├── downloader.py
│   │   │   ├── parser.py
│   │   │   ├── normalizer.py
│   │   │   ├── validator.py
│   │   │   ├── importer.py
│   │   │   └── sync.py
│   │   ├── analytics/
│   │   │   ├── batting.py
│   │   │   ├── bowling.py
│   │   │   ├── phases.py
│   │   │   ├── matchups.py
│   │   │   ├── consistency.py
│   │   │   └── scouting_score.py
│   │   ├── ml/
│   │   │   ├── features/
│   │   │   │   ├── player_features.py
│   │   │   │   └── matchup_features.py
│   │   │   ├── similarity/
│   │   │   │   ├── train.py
│   │   │   │   └── predict.py
│   │   │   ├── prediction/
│   │   │   │   ├── train.py
│   │   │   │   └── predict.py
│   │   │   ├── evaluation/
│   │   │   └── registry.py
│   │   └── reports/
│   │
│   ├── tests/
│   │   ├── fixtures/
│   │   ├── unit/
│   │   ├── integration/
│   │   └── validation/
│   ├── migrations/
│   ├── scripts/
│   ├── requirements.txt
│   └── alembic.ini
│
├── data/
│   ├── raw/
│   ├── staging/
│   ├── processed/
│   └── reports/
│
├── docs/
│   ├── data-dictionary.md
│   ├── cricket-rules.md
│   ├── architecture.md
│   └── model-cards/
│
├── .env.example
├── .gitignore
└── README.md
```

Do not commit downloaded datasets, secrets, database dumps or trained
model files unless there is a deliberate reason and licensing/storage
constraints have been checked.

------------------------------------------------------------------------

## 4. Development Environment

### 4.1 Prerequisites

-   Python version supported by the selected FastAPI, Pandas and
    Scikit-learn releases.
-   Node.js LTS.
-   PostgreSQL.
-   Git.
-   A code editor.
-   Cricsheet sample JSON files.

Pin dependencies after confirming compatibility. Avoid installing
unbounded latest versions in a reproducible project.

### 4.2 Backend Environment

Create and activate a virtual environment:

``` bash
cd backend
python -m venv .venv

# macOS / Linux
source .venv/bin/activate

# Windows PowerShell
# .venv\Scripts\Activate.ps1
```

Initial dependency set:

``` text
fastapi
uvicorn[standard]
sqlalchemy
psycopg[binary]
alembic
pydantic
pydantic-settings
pandas
numpy
scikit-learn
joblib
httpx
pytest
pytest-cov
```

Add packages only when required. For example, PDF generation can be
added when report export is implemented.

Install:

``` bash
pip install -r requirements.txt
```

### 4.3 Frontend Environment

``` bash
npm create vite@latest frontend -- --template react
cd frontend
npm install
```

Add Tailwind CSS and D3.js using their current installation
instructions. Keep API communication in a shared service layer rather
than scattering fetch calls throughout components.

### 4.4 Environment Variables

Create `.env` locally and commit only `.env.example`.

Example variable names:

``` env
DATABASE_URL=
OPENCRICKET_API_KEY=
OPENCRICKET_BASE_URL=
ENVIRONMENT=development
```

Do not assume an OpenCricket key is required for every endpoint. Keep
provider configuration optional and verify current documentation before
implementing calls.

------------------------------------------------------------------------

## 5. Milestone 1: Inspect Cricsheet Data

**Objective:** Understand actual source files before finalising the
schema.

### Tasks

1.  Download a small IPL JSON archive.
2.  Download a small Men's T20I JSON archive.
3.  Select several representative match files.
4.  Inspect metadata, registry, innings, overs and deliveries.
5.  Inspect extras, wickets, replacements and unusual cases.
6.  Record which fields are consistently available.
7.  Produce a data dictionary and coverage report.

### Required output

Create: - `docs/data-dictionary.md` - `docs/cricket-rules.md` - A sample
parser output. - A list of unsupported or missing attributes. - A report
of match counts by competition and season.

### Important instruction

Do not design the complete database from an imagined JSON structure.
Inspect the downloaded files and map the fields actually present.

Cricsheet source formats can evolve. Keep parsers tolerant of optional
fields while validating required fields.

### Milestone acceptance criteria

-   At least several real match files parse successfully.
-   Match identifiers and player registry identifiers are retained.
-   Innings and delivery counts can be reported.
-   Extras and wicket structures are understood.
-   Unknown or unsupported fields are documented rather than silently
    discarded.

------------------------------------------------------------------------

## 6. Milestone 2: Canonical Data Model and PostgreSQL

### 6.1 Proposed Tables

#### `providers`

-   `id`
-   `name`
-   `base_url`
-   `created_at`

#### `tournaments`

-   `id`
-   `provider_id`
-   `source_tournament_id`
-   `name`
-   `format`
-   `gender`
-   `country` (nullable)
-   Unique constraint on provider and source identifier where available.

#### `teams`

-   `id`
-   `name`
-   `canonical_name`
-   `created_at`

#### `team_aliases`

-   `id`
-   `team_id`
-   `provider_id`
-   `source_name`

#### `players`

-   `id`
-   `canonical_name`
-   `created_at`

#### `player_aliases`

-   `id`
-   `player_id`
-   `provider_id`
-   `source_player_id`
-   `source_name`
-   Unique constraint on provider and source player identifier where
    available.

#### `player_attributes`

-   `id`
-   `player_id`
-   `attribute_type`
-   `attribute_value`
-   `source`
-   `valid_from`
-   `valid_to`
-   `confidence`
-   `updated_at`

Store uncertain or time-varying player attributes with provenance. Do
not assume nationality, age or bowling style is complete.

#### `venues`

-   `id`
-   `name`
-   `canonical_name`
-   `city` (nullable)
-   `country` (nullable)

#### `matches`

-   `id`
-   `provider_id`
-   `source_match_id`
-   `tournament_id`
-   `venue_id`
-   `start_date`
-   `gender`
-   `format`
-   `match_type`
-   `season`
-   `team1_id`
-   `team2_id`
-   `toss_winner_id`
-   `toss_decision`
-   `winner_id`
-   `result_type`
-   `raw_source_checksum`
-   `source_revision`
-   Unique constraint on provider and source match identifier.

#### `match_innings`

-   `id`
-   `match_id`
-   `innings_number`
-   `batting_team_id`
-   `target_runs` (nullable)
-   `target_overs` (nullable)
-   `is_super_over`
-   Unique constraint on match and innings number, adjusted if the
    source represents super overs differently.

#### `deliveries`

-   `id`
-   `innings_id`
-   `over_number`
-   `delivery_sequence`
-   `source_delivery_order`
-   `batter_id`
-   `bowler_id`
-   `non_striker_id`
-   `batter_runs`
-   `total_runs`
-   `is_legal_ball`
-   `source_delivery_id` (nullable)
-   Unique constraint based on innings and stable delivery ordering.

#### `delivery_extras`

-   `id`
-   `delivery_id`
-   `extra_type`
-   `runs`

#### `wickets`

-   `id`
-   `delivery_id`
-   `player_out_id`
-   `dismissal_type`
-   `credited_to_bowler`
-   `fielder_id` (nullable)

Support multiple wicket events if the source format permits them.

#### `raw_matches`

-   `id`
-   `provider_id`
-   `source_match_id`
-   `source_file_name`
-   `checksum`
-   `raw_json` or a reference to a retained source file
-   `retrieved_at`
-   `revision`

#### `ingestion_runs`

-   `id`
-   `provider_id`
-   `started_at`
-   `finished_at`
-   `status`
-   `matches_discovered`
-   `matches_inserted`
-   `matches_updated`
-   `matches_skipped`
-   `error_summary`

#### `player_match_stats` and `team_match_stats`

Store derived statistics only when useful for query performance. They
must be reproducible from granular records.

### 6.2 Schema Rules

-   Use internal UUIDs or another stable internal primary key.
-   Retain provider identifiers separately.
-   Do not identify players by name alone.
-   Use database constraints to prevent duplicate source records.
-   Use numeric types with adequate precision for rates.
-   Store legal-ball counts as integers.
-   Store over number and delivery order separately. Never use decimal
    overs as a calculation input.
-   Index foreign keys and common filter columns.
-   Use Alembic migrations for schema changes.

### 6.3 Raw Data Retention

Retain the original source JSON or a durable reference to it. This
allows: - Parser bug fixes. - Reprocessing after schema changes. -
Auditing differences between source and canonical data. - Detection of
source revisions.

For larger imports, store raw files on disk during development and in
suitable object storage in production. Store checksum and location in
PostgreSQL.

------------------------------------------------------------------------

## 7. Milestone 3: Ingestion Pipeline

### 7.1 Provider Interface

Define a provider adapter with operations conceptually equivalent to:

``` python
class CricketDataProvider:
    def discover_matches(self):
        raise NotImplementedError

    def download_match(self, source_match_id):
        raise NotImplementedError

    def parse_match(self, source_payload):
        raise NotImplementedError
```

Cricsheet and OpenCricket adapters implement only the operations
supported by their respective sources.

Do not invent a delivery endpoint for a provider plan that does not
offer one.

### 7.2 Ingestion Flow

``` text
Scheduled trigger / Manual command
              |
              v
      Discover source files
              |
              v
      Download and checksum
              |
              v
       Compare source IDs
              |
              v
       Parse into canonical
              |
              v
       Validate match records
              |
              v
     Database transaction
              |
              v
    Recompute affected stats
              |
              v
       Record run status
```

### 7.3 Idempotency

The same source file must be safe to process more than once.

Use: - Unique source match identifiers. - Unique delivery ordering
within innings. - Source checksums. - Database upserts where
appropriate. - Transaction boundaries. - A revision-aware replacement or
reconciliation strategy.

Do not update a completed match by blindly appending all its deliveries
again.

If a source checksum changes, reprocess the match in a controlled
transaction. Replace or reconcile the affected innings and derived
records.

### 7.4 Validation Before Insert

Check: - Match metadata is present. - Teams and player references
resolve. - Innings and delivery ordering are valid. - Total runs equal
batter runs plus extras. - Extras are internally consistent. - Wicket
records refer to valid players and deliveries. - Innings totals
reconcile with the source scorecard when available. - Duplicate delivery
keys are absent.

Validation errors should be stored with enough detail to diagnose the
source file and record.

### 7.5 Scheduling

Start with: - A local manual sync command. - A GitHub Actions scheduled
workflow for a simple hosted project, if runtime and source terms
permit. - Periodic full reconciliation.

Do not depend on a scheduled workflow as the only recovery mechanism.
Provide manual re-sync and logs.

------------------------------------------------------------------------

## 8. Milestone 4: Cricket Analytics Engine

Implement pure functions where possible. A function should accept
structured records and return deterministic results without depending on
FastAPI request state.

### 8.1 Batting Statistics

Core definitions:

**Batting average**

`runs scored / times dismissed`

**Strike rate**

`runs scored / balls faced * 100`

**Boundary percentage**

`boundary deliveries / balls faced * 100`

**Dot-ball percentage**

`dot deliveries / balls faced * 100`

The precise denominator conventions must be documented. For common
scorecard conventions: - Wides are not balls faced by the batter. -
No-balls count as balls faced. - Batter runs are distinct from total
team runs. - A delivery can contain runs that are not credited to the
batter.

Do not divide by zero. Return null or a clearly defined not-applicable
result when a denominator is zero.

### 8.2 Bowling Statistics

**Economy rate**

`bowling runs conceded / legal balls * 6`

**Bowling average**

`bowling runs conceded / wickets credited to bowler`

**Bowling strike rate**

`legal balls / wickets credited to bowler`

Bowling runs conceded generally include batter runs and relevant
wides/no-balls, but exclude byes and leg-byes. Wicket credit depends on
dismissal type.

Do not derive overs as a decimal. Display legal balls as overs and
remaining balls, for example 4 overs and 2 balls.

### 8.3 Legal Ball Classification

Create one central function:

``` python
def is_legal_delivery(extras: dict) -> bool:
    # Implement from documented source and scorekeeping rules.
    ...
```

Do not duplicate legal-ball logic across batting, bowling and phase
modules.

The exact Cricsheet extras representation must be inspected before
implementation. Cover wides, no-balls and any source-specific edge cases
in tests.

### 8.4 Dismissal Classification

Create a central mapping that determines: - Whether the batter is
dismissed for batting-average purposes. - Whether the bowler receives
credit. - Which player was dismissed. - Whether the event needs special
handling.

Do not assume all wicket events count as bowler wickets.

### 8.5 Phase Assignment

For a standard 20-over T20 innings: - Powerplay: zero-based over indexes
0-5. - Middle: indexes 6-14. - Death: indexes 15-19.

Use source over indexing only after confirming the actual JSON
representation. Handle shortened innings and super overs explicitly.

### 8.6 Pace and Spin

Only calculate pace/spin metrics when the bowler-style mapping is
sufficiently complete and trustworthy.

Store: - Attribute source. - Last updated time. - Confidence or
verification status.

For unknown styles, use `unknown`, not a guessed category.

### 8.7 Statistical Validation

Build a small gold-standard test set using real matches with
independently verified scorecards.

For each case, verify: - Innings runs. - Batter runs and balls faced. -
Bowling runs conceded and legal balls. - Wickets credited. - Phase
totals. - Extras.

Include edge cases for wides, no-balls, byes, leg-byes, run-outs,
multiple wicket events, super overs and unusual dismissals.

------------------------------------------------------------------------

## 9. Milestone 5: Analytics API

Use Pydantic response schemas. API routes should call service functions;
they should not contain cricket formulas.

Suggested endpoints:

``` text
GET  /api/v1/health
GET  /api/v1/dataset/coverage

GET  /api/v1/players
GET  /api/v1/players/{player_id}
GET  /api/v1/players/{player_id}/batting
GET  /api/v1/players/{player_id}/bowling
GET  /api/v1/players/{player_id}/phases
GET  /api/v1/players/{player_id}/similar

GET  /api/v1/matches
GET  /api/v1/matches/{match_id}

GET  /api/v1/matchups/{batter_id}/{bowler_id}

POST /api/v1/scouting/search
POST /api/v1/players/compare
```

Example scouting request:

``` json
{
  "format": "T20",
  "competition": "IPL",
  "seasons": [2022, 2023, 2024, 2025],
  "nationality": "India",
  "role": "middle_order_batter",
  "minimum_innings": 20,
  "priorities": {
    "spin_performance": 0.30,
    "middle_over_scoring": 0.25,
    "batting_average": 0.20,
    "consistency": 0.15,
    "experience": 0.10
  }
}
```

The API must validate that weights are non-negative and sum to a valid
total, or normalise them explicitly. Hard eligibility filters must not
be hidden inside the scoring formula.

Example response fields:

``` json
{
  "player_id": "internal-player-id",
  "rank": 1,
  "suitability_score": 82.4,
  "score_version": "scouting-v1",
  "sample": {
    "innings": 34,
    "balls_faced": 510
  },
  "strengths": [
    "Strong middle-over scoring",
    "Above-cohort spin strike rate"
  ],
  "limitations": [
    "Limited data against some bowling styles"
  ]
}
```

These values are illustrative response shapes, not real player results.

------------------------------------------------------------------------

## 10. Milestone 6: Feature Engineering

Create a documented feature table for each model. Every feature needs: -
Name. - Definition. - Data source. - Calculation window. - Required
sample. - Missing-value behaviour. - Whether it is available at
prediction time.

### 10.1 Initial Player Feature Set

Potential features: 1. Batting average. 2. Batting strike rate. 3. Balls
faced. 4. Innings. 5. Not-outs. 6. Dot-ball percentage. 7. Boundary
percentage. 8. Four percentage. 9. Six percentage. 10. Powerplay strike
rate. 11. Middle-over strike rate. 12. Death-over strike rate. 13.
Powerplay average. 14. Middle-over average. 15. Death-over average. 16.
Pace strike rate, if metadata permits. 17. Spin strike rate, if metadata
permits. 18. Pace average, if metadata permits. 19. Spin average, if
metadata permits. 20. Recent-form strike rate. 21. Recent-form average.
22. Innings-to-innings consistency. 23. Batting-position distribution.
24. Competition/season experience. 25. Sample-size reliability
indicator.

This is a candidate list, not a requirement to use every feature in
every model. Some features are correlated. Test feature behaviour before
selecting a final set.

### 10.2 Normalisation

For player similarity: - Scale numerical features using a fitted
scaler. - Fit the scaler only on the training/reference population. -
Persist the scaler with the model. - Avoid fitting separately during
each inference request. - Handle missing values with explicit indicators
or carefully chosen imputation. - Consider role-specific cohorts so
openers are not compared indiscriminately with finishers.

For role-adjusted scores, define comparison cohorts and minimum samples.

### 10.3 Avoid Leakage

For a prediction made before a match, features may only use matches
completed before that match.

Do not calculate a player's historical average using the match being
predicted or any future match.

Use time-aware feature generation and chronological validation.

------------------------------------------------------------------------

## 11. Milestone 7: ML Models

### 11.1 Player Similarity

**First ML feature to implement.**

Inputs: - Role-appropriate batting features. - Phase features. -
Bowling-style performance only where metadata is reliable. - Sample-size
and experience information, with care not to let volume dominate
similarity.

Implementation: 1. Query eligible player aggregates. 2. Apply role and
minimum-sample filters. 3. Select a versioned feature set. 4. Impute
missing values. 5. Scale features. 6. Fit KNN with cosine distance or
calculate cosine similarity. 7. Return nearest candidates. 8. Generate
feature-level explanations. 9. Store model and feature-set version.

Evaluate manually using cricket-domain examples. Check whether known
role peers appear near one another. Compare cosine distance and
alternative distance metrics.

Do not label `1 - cosine_distance` as a calibrated probability. Call it
a similarity score or similarity percentage and document its
interpretation.

### 11.2 Statistical Scouting Score

Implement this before a learned recruitment model.

Steps: 1. Apply hard filters. 2. Calculate peer-relative features. 3.
Apply analyst-configured weights. 4. Include sample reliability. 5.
Produce a ranked shortlist. 6. Explain contributions to each score.

Persist a scoring configuration version so a shortlist can be
reproduced.

### 11.3 Matchup Model

Start with descriptive statistics.

For a later model: - Define a prediction unit, such as a delivery. -
Define the target, such as dismissal on the delivery or batter runs. -
Build features from information available before that delivery. - Use
chronological splits grouped by match/time. - Compare against simple
baseline rates. - Evaluate calibration and error. - Display uncertainty
and sample size.

A raw batter-versus-bowler history is not enough by itself to make a
reliable prediction.

### 11.4 Performance Prediction

Start with a baseline such as historical role/phase averages.

Then compare: - Linear or logistic regression. - Random Forest. -
HistGradientBoosting or another gradient-boosting approach available in
the pinned library version.

For runs prediction: - MAE. - RMSE. - Error by role and batting
position.

For probability: - Log loss. - Brier score. - Calibration curve.

Use chronological training, validation and test periods. Keep the final
test period untouched until model selection is complete.

### 11.5 Model Artefacts and Registry

Persist: - Model object. - Preprocessing pipeline. - Feature names and
order. - Training data date range. - Training code version or Git
commit. - Hyperparameters. - Evaluation metrics. - Model version. -
Creation timestamp.

Never load an artefact whose expected feature schema does not match the
current feature builder.

Use `joblib` for suitable Scikit-learn artefacts and treat saved model
files as trusted internal artefacts only.

------------------------------------------------------------------------

## 12. Milestone 8: Frontend

### 12.1 Design Direction

-   Dark navy/charcoal foundation.
-   Subtle cricket-green accent.
-   Clean typography and strong hierarchy.
-   Minimal decorative elements.
-   Dense but readable data tables.
-   Clear filters and comparison controls.
-   Charts only where they improve interpretation.

### 12.2 Initial Pages

1.  Overview.
2.  Players.
3.  Player profile.
4.  Player comparison.
5.  Matchup analysis.
6.  Scouting workspace.
7.  Data coverage and ingestion status.

### 12.3 Visualisation Guidance

Use D3.js for meaningful visualisations: - Phase-wise performance. -
Player comparison radar chart. - Scoring distribution. - Player trend
lines. - Bowling analysis.

Do not build a genuine wagon wheel until reliable shot-location data is
available.

Every chart should expose its filters, sample size and metric
definition.

### 12.4 API Integration

-   Keep a central API client.
-   Handle loading, empty and error states.
-   Use server-returned statistics as the source of truth.
-   Avoid recalculating cricket metrics in React.
-   Make active filters visible and reproducible.

------------------------------------------------------------------------

## 13. Milestone 9: Testing Strategy

### Unit Tests

Test: - Legal-ball classification. - Batter balls faced. - Bowling runs
conceded. - Wicket credit. - Batting average. - Strike rate. -
Economy. - Bowling average and strike rate. - Phase assignment. -
Boundary and dot-ball calculations. - Similarity feature
preprocessing. - Scouting weight validation.

### Integration Tests

Test: - Source JSON parsing. - Database import. - Duplicate ingestion. -
Revised source ingestion. - Player identity mapping. - API response
schemas. - Aggregate recalculation.

### Data Validation Tests

For a selected set of matches: - Compare calculated totals with trusted
scorecards. - Check innings totals. - Check batter and bowler figures. -
Check phase sums reconcile with innings totals where definitions
permit. - Report unresolved identities and missing attributes.

### ML Tests

-   Training and inference feature columns match.
-   Preprocessing is persisted.
-   No future records enter historical features.
-   Baselines are measured.
-   Model evaluation is reproducible.
-   Low-sample players are handled appropriately.
-   Prediction outputs are within valid ranges where applicable.

Run tests with:

``` bash
pytest
```

Coverage can be measured with:

``` bash
pytest --cov=app
```

------------------------------------------------------------------------

## 14. Deployment Plan

A simple initial deployment can use: - Frontend: Vercel. - Backend:
Render or a comparable Python hosting provider. - Database: Managed
PostgreSQL. - Scheduled ingestion: GitHub Actions or a suitable
scheduler.

Before selecting a provider, verify: - Current free-tier availability. -
Database storage and connection limits. - Backend sleep behaviour. -
Scheduled-job limits. - Persistent storage availability. -
Environment-variable support. - Network access between services.

Do not store important raw data only on an ephemeral application
filesystem.

Keep development, test and production databases separate. Use Alembic
migrations for deployment.

------------------------------------------------------------------------

## 15. Milestone Definition of Done

### Milestone 1: Dataset inspection

-   [ ] Sample IPL and Men's T20I files downloaded.
-   [ ] JSON structure documented.
-   [ ] Player and match identifiers understood.
-   [ ] Extras and wickets mapped.
-   [ ] Coverage report produced.

### Milestone 2: Database

-   [ ] Schema reviewed against actual data.
-   [ ] SQLAlchemy models created.
-   [ ] Alembic initial migration applied.
-   [ ] Constraints and indexes added.
-   [ ] Raw source retention implemented.

### Milestone 3: Ingestion

-   [ ] Cricsheet adapter works.
-   [ ] Parser produces canonical records.
-   [ ] Validation report generated.
-   [ ] Idempotent import works.
-   [ ] Revised source files can be reprocessed.
-   [ ] Sync logs are recorded.

### Milestone 4: Analytics

-   [ ] Batting metrics tested.
-   [ ] Bowling metrics tested.
-   [ ] Extras and dismissal rules tested.
-   [ ] Phase metrics tested.
-   [ ] Results reconciled against independent scorecards.

### Milestone 5: API

-   [ ] Player endpoints work.
-   [ ] Match endpoints work.
-   [ ] Analytics endpoints work.
-   [ ] Response schemas documented.
-   [ ] Error handling implemented.

### Milestone 6: ML

-   [ ] Feature definitions documented.
-   [ ] Similarity model trained.
-   [ ] Preprocessing saved with model.
-   [ ] Similarity results reviewed for cricket relevance.
-   [ ] Scouting scoring is explainable.
-   [ ] Baseline and evaluation results documented.

### Milestone 7: Frontend

-   [ ] Dashboard works.
-   [ ] Player profile works.
-   [ ] Comparison works.
-   [ ] Matchup view works.
-   [ ] Scouting workflow works.
-   [ ] Empty, loading and error states work.

### Milestone 8: Release

-   [ ] Integration tests pass.
-   [ ] Secrets are not committed.
-   [ ] Deployment migrations work.
-   [ ] Ingestion schedule and manual recovery work.
-   [ ] README and product documentation are complete.

------------------------------------------------------------------------

## 16. Recommended Build Order for the First Working Version

Do the following in order. Do not skip ahead to ML or UI before the data
foundation is reliable.

**Step 1:** Download a small Cricsheet IPL JSON archive and inspect
actual files.

**Step 2:** Write a parser for one match and print: - Match metadata. -
Teams. - Players. - Innings. - Delivery count. - Runs. - Extras. -
Wickets.

**Step 3:** Build a validator and compare the result with the source
scorecard.

**Step 4:** Expand parsing to a small batch of matches.

**Step 5:** Finalise the schema based on observed source structures.

**Step 6:** Implement database import with duplicate protection.

**Step 7:** Calculate batting and bowling statistics and validate them.

**Step 8:** Expose player profiles through FastAPI.

**Step 9:** Build the first React player profile.

**Step 10:** Add phase-wise analysis, comparisons and matchups.

**Step 11:** Build the player feature table and similarity model.

**Step 12:** Add configurable scouting rankings and explanations.

**Step 13:** Add advanced prediction models only after establishing
trustworthy baselines and chronological evaluation.

------------------------------------------------------------------------

## 17. Engineering Rules for AI-Assisted Development

When using an AI coding assistant to implement CPI:

1.  Read both `PRD.md` and `implementation.md` before making
    architectural changes.
2.  Work on one milestone at a time.
3.  Inspect existing files before modifying them.
4.  Do not generate the entire application in one response.
5.  Do not invent Cricsheet fields or API endpoints.
6.  Ask for actual sample JSON or documentation when a field is
    uncertain.
7.  Write tests alongside cricket calculations.
8.  Explain any schema change and its migration impact.
9.  Preserve provider independence.
10. Do not call a weighted formula an ML model.
11. Never use future information in historical prediction features.
12. Do not display unsupported shot locations, bowling styles or player
    attributes.
13. Keep dependencies free/open-source where practical.
14. Update documentation when behaviour changes.
15. Report what was implemented, what was tested and what remains
    incomplete.

## 18. Immediate Next Action

Start with **Milestone 1: Dataset Inspection**.

Do not create the complete database or frontend yet.

The first deliverable should be a small Python script that: - Opens a
real Cricsheet JSON file. - Extracts match metadata. - Iterates through
innings, overs and deliveries. - Counts deliveries, runs, extras and
wicket events. - Prints a readable summary. - Reports fields it does not
recognise.

Once this works against several representative files, use the observed
structures to finalise the canonical schema.

------------------------------------------------------------------------

**End of implementation plan**
