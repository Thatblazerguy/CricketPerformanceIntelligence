# Cricket Performance Intelligence (CPI)

<div align="center">

![Python](https://img.shields.io/badge/Python-3.9%2B-blue?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white)
![React](https://img.shields.io/badge/React-18-61DAFB?logo=react&logoColor=black)
![Vite](https://img.shields.io/badge/Vite-5-646CFF?logo=vite&logoColor=white)
![TailwindCSS](https://img.shields.io/badge/Tailwind-3.4-38B2AC?logo=tailwind-css&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-336791?logo=postgresql&logoColor=white)
![scikit-learn](https://img.shields.io/badge/scikit--learn-ML-F7931E?logo=scikit-learn&logoColor=white)

**Cricket analytics, scouting, match simulation and win probability, built on delivery-level Cricsheet data and the Laws of Cricket.**

</div>

---

## Contents

1. [Overview](#overview)
2. [Dataset](#dataset)
3. [Features](#features)
4. [Win Probability Model](#win-probability-model)
5. [Cricket Rules & Statistical Integrity](#cricket-rules--statistical-integrity)
6. [Architecture](#architecture)
7. [Tech Stack](#tech-stack)
8. [Installation & Setup](#installation--setup)
9. [Data Sync & Derived Tables](#data-sync--derived-tables)
10. [Tests](#tests)
11. [Further Documentation](#further-documentation)
12. [License & Acknowledgements](#license--acknowledgements)

---

## Overview

Career aggregates hide the things analysts actually need to know. A batter striking at 135 overall may strike at 155 against pace and 98 against spin. A bowler with an economy of 7.8 may go at 6.1 in the powerplay and 11.4 at the death. Small head-to-head samples get over-read, and franchise T20 cricket gets mixed into international numbers.

CPI ingests raw Cricsheet ball-by-ball records into a normalised PostgreSQL schema and computes every metric from the deliveries, using official scoring rules. Each figure carries its sample size, undefined ratios are shown as `—` rather than zero, and formats and genders are never mixed.

---

## Dataset

| Format | Description | Matches | Deliveries |
|---|---|---:|---:|
| T20 | Franchise and domestic T20 (IPL, BBL, PSL, …) | 8,576 | 1,966,637 |
| T20I | International T20 | 6,169 | 1,391,544 |
| ODI | One-day internationals | 3,237 | 1,713,385 |
| ODM | Domestic one-day | 2,094 | 1,077,804 |
| Test | Test matches | 923 | 1,777,274 |
| MDM | Domestic multi-day | 2,242 | 3,812,844 |
| **Total** | | **23,241** | **11,739,488** |

About 15,100 players, 540 venues and 400 teams, covering men's and women's cricket. Team ids can hold both men's and women's matches, so every team query filters by gender.

---

## Features

The app's navigation is grouped into Overview, Players, Matches, Competitions, Markets and System. A global player quick search opens with `⌘K` / `Ctrl+K` or `/`.

### Dashboard
Dataset state, data freshness and current leaders.

### Players
- **Directory**: search, format pills, sortable columns and pagination.
- **Player profile**: career and filtered batting and bowling, side-by-side format breakdown, and filters for format, year range, season, opponent, venue, bowling style (pace/spin) and phase. Includes opponent and venue breakdowns, year-by-year trajectory, recent matches, strengths and vulnerabilities, and CSV export.
- **Deep analytics**: innings-level batting and bowling dashboards (score distributions, rolling form, dismissal patterns, phase and style splits) from `GET /players/{id}/innings-log`.
- **Comparison**: side-by-side player profiles with metric-level comparison insights.
- **Matchups**: any batter against any bowler, with runs, balls, strike rate, dot and boundary %, bowler-credited dismissals kept apart from run-outs, over-by-over breakdown, match log and trend charts.
- **Player similarity**: batting, bowling and all-rounder analogues from standardised feature vectors and cosine nearest neighbours.

### Scouting
Role-based recruitment rankings: opener, middle order, finisher, wicketkeeper-batter, pace bowler, spin bowler, all-rounder and general batter/bowler.

- Per-innings aggregate tables (`scouting_bat_innings`, `scouting_bat_vs_style`, `scouting_bowl_innings`) make ranking fast for any format, tournament, season or year scope.
- Metrics are shrunk towards the comparison group by empirical Bayes, adjusted for the run-rate environment, and converted to percentiles within the role's comparison group.
- Scores are weighted mean percentiles. Missing metrics are dropped and weights renormalised, never filled with zero. Each player gets a reliability label: Established, Limited evidence or Insufficient data.
- Requirement filters, side-by-side compare, a per-player scouting report, and the original weighted search as the **Cohort explorer** tab.

### Match Centre
Scorecards, ball-by-ball commentary data and the v2 win-probability curve for every match, with in-sample and out-of-sample labelling.

### Match Simulator
- The one place to load Playing XIs: paste, team-sheet OCR, CSV, presets or saved XIs. Both XIs are resolved against CPI players and validated before a run.
- Workflow: teams → XIs → format and conditions (T20/ODI/Test, historical venue, pitch, weather, toss) → validate → one detailed match or a Monte Carlo batch.
- Each delivery is sampled from smoothed CPI rates: format, innings, over and wickets-lost baselines, chase pressure, batter vs pace/spin by phase, bowler by phase, venue history and batting-position priors. Real match rules apply: over limits, free hits, strike rotation, super overs, and Test follow-on and declarations. Scorecards reconcile exactly.
- Calibrations live in `backend/artifacts/simulator/` (rebuild with `scripts/train_match_simulator.py`). `scripts/backtest_match_simulator.py` checks bias against real matches.

### Competitions
- **Tournaments**: season standings with net run rate, batting and bowling leaders, head-to-head, venues and season-on-season scoring trends.
- **Team analytics**: team directory, profiles and team-vs-team compare. Covers overall record, home/away/neutral splits, batting and bowling by phase and bowling style, match situations (batting first vs chasing, targets defended) and trends.
- **Venue analytics**: venue directory, profiles and compare. Covers toss impact, batting first vs chasing, first- and second-innings score distributions, pace vs spin returns and seasonal trends. Conditions are reported as measured figures; anything inferred from scoring outcomes is labelled as an inference, not a pitch report.

All competition endpoints share the same scope filters (format, gender, competition, season, year range) and attach sample sizes and significance tests where a comparison is drawn.

### Auction Intelligence
Versioned auction scenarios with rules, franchises, retentions and player pools imported from CSV, identity resolution against CPI players, live auction sessions (call, bid, sell/unsell, event log) and an experimental historical price model. See [AUCTION_ARCHITECTURE.md](AUCTION_ARCHITECTURE.md).

### Settings
Data management: Cricsheet sync status, schedule, manual sync and import history.

---

## Win Probability Model

CPI's v2 engine (`backend/app/ml/wp/`) estimates, before every delivery, the chance that each side wins. It is trained only on CPI's own ball-by-ball tables and evaluated on later matches it has never seen. The full evaluation, including every segment table and reliability diagram, is in [`backend/artifacts/win_probability/v2/REPORT.md`](backend/artifacts/win_probability/v2/REPORT.md); `evaluation.json` is the machine-readable version.

### Models

| Format group | Source formats | Outcome | Innings handling |
|---|---|---|---|
| T20 | T20 + T20I (`international` is a feature) | binary: batting side wins | separate first- and second-innings models |
| ODI | ODI | binary | separate first- and second-innings models |
| ODM | domestic one-day | binary | separate first- and second-innings models |
| Test | Test | batting win / bowling win / draw | one model, innings number as a feature |
| MDM | domestic multi-day | batting win / bowling win / draw | one model, innings number as a feature |

For each group and innings, a validation search compares logistic regression with `HistGradientBoostingClassifier`, picks the lowest validation log loss, and refits on train + validation. A calibrator (none, sigmoid or isotonic) is then chosen by match-grouped cross-validation on a separate calibration partition.

Key features: pre-delivery runs, wickets and balls; required run rate and runs required per ball and per wicket; a resource table (expected runs remaining for balls and wickets left, similar to the DLS resource idea); venue par shrunk towards era par; a 730-day rolling era par; lagged chronological Elo; toss, gender and international flags. Context features use only matches dated before the one being predicted.

Decided states (target reached, all out, out of balls, innings defeat) are resolved by the Laws of Cricket, never by the model. Impossible states return HTTP 422.

### Partitions

Splits are by whole match and by date: 60% train, 15% validation, 10% calibration, 15% test. The test partition was used once, for the results below.

### Held-out test results

Match-weighted log loss with 95% match-level bootstrap intervals. Skill is `1 − model log loss / prior log loss`.

| Group | Test matches | v2 log loss | Legacy v1 | Elo only | Venue par | Constant prior | Skill vs prior |
|---|---:|---:|---:|---:|---:|---:|---:|
| T20 | 2,145 | **0.429** [0.416, 0.442] | 0.630 | 0.640 | 0.575 | 0.692 | +0.381 |
| ODI | 462 | **0.462** [0.425, 0.498] | 0.695 | 0.646 | 0.603 | 0.694 | +0.335 |
| ODM | 291 | **0.528** [0.486, 0.569] | 0.684 | 0.656 | 0.628 | 0.690 | +0.235 |
| Test | 138 | **0.727** [0.636, 0.820] | 0.985 | 0.924 | 0.883 | 0.992 | +0.267 |
| MDM | 336 | **0.885** [0.827, 0.936] | 1.076 | 1.098 | 1.050 | 1.089 | +0.187 |

The v1 model was close to a coin flip in limited-overs cricket. The main causes were team1/team2 labels paired with batting-side features, extreme regularisation (`C=1e-4`), missing chase targets and pooled formats. `scripts/audit_win_probability_v1.py` reproduces the ablation.

### Where it is used

- `GET /api/v1/matches/{id}/win-probability` serves precomputed curves with per-point `confidence` (`normal`, `low`, `decided`) and the match's evaluation partition.
- `POST /api/v1/simulator/win-probability` evaluates a live state and returns `confidence`, `support_states` and explanatory notes.
- Simulated Tests use the multi-day model. Limited-overs simulations use the simulator's own Monte Carlo curve.
- After each Cricsheet sync, curves and player win-probability-added are recomputed for the affected matches.

### Known limitations

- CPI stores no declarations, sessions or time lost, so multi-day draw probability is driven by overs bowled. Multi-day models are the weakest.
- Only the final DLS target is stored, so rain-reduced first innings are modelled as full length.
- Tied matches have no recorded super-over winner and are excluded from training and evaluation.
- The models do not know the line-ups.
- Test and ODM samples are small and their intervals are wide.

### Rebuild

```bash
cd backend
.venv/bin/python scripts/train_win_probability_v2.py        # train + evaluate (~12 min)
.venv/bin/python scripts/report_win_probability_v2.py       # writes REPORT.md
.venv/bin/python scripts/precompute_win_probability_v2.py   # historical curves + player WPA (~4 min)
```

---

## Cricket Rules & Statistical Integrity

Every calculation follows the Laws of Cricket and standard scoring conventions. Full reference: [docs/cricket-rules.md](docs/cricket-rules.md).

1. **Legal deliveries.** Wides and no-balls are not legal and do not count towards the over. Byes, leg-byes and penalty runs on legal deliveries do.
2. **Balls faced.** Include no-balls, byes and leg-byes; exclude wides.
3. **Runs.** Batter runs are runs off the bat. Bowler runs conceded include batter runs, wides and no-balls, and exclude byes and leg-byes.
4. **Wicket credit.** Bowled, caught, caught and bowled, lbw, stumped and hit wicket credit the bowler. Run out, obstructing the field, retired hurt and retired out do not. Dismissals are charged to the player who was out, so a run-out non-striker is not charged to the striker.
5. **Rates.**
   - Strike rate = batter runs × 100 / balls faced
   - Economy = runs conceded × 6 / legal balls
   - Bowling average = runs conceded / bowler wickets
   - Bowling strike rate = legal balls / bowler wickets
   - A zero denominator returns `null` (shown as `—`).
6. **Phases** are format-aware: T20/T20I 1–6 / 7–15 / 16–20, ODI/ODM 1–10 / 11–40 / 41–50, and none for Test and multi-day. See [PHASE_RULES.md](PHASE_RULES.md).
7. **Super overs** are kept out of standard innings statistics.

---

## Architecture

```
┌────────────────────────────────────────────────────────────┐
│ React 18 + Vite + Tailwind                                 │
│ Dashboard · Players · Scouting · Match Centre · Simulator  │
│ Tournaments · Teams · Venues · Auction · Settings          │
└──────────────────────────────┬─────────────────────────────┘
                               │ REST JSON (/api/v1)
                               ▼
┌────────────────────────────────────────────────────────────┐
│ FastAPI                                                    │
│ • SQL aggregation over deliveries                          │
│ • Pure analytics modules (rules, insights, teams, venues)  │
│ • Scouting engine (shrinkage, percentiles, reliability)    │
│ • Match simulator and Monte Carlo                          │
│ • Win probability v2, similarity, auction price model      │
└──────────────────────────────┬─────────────────────────────┘
                               │ SQLAlchemy 2 / Psycopg 3
                               ▼
┌──────────────────────────┐   ┌──────────────────────────────┐
│ Cricsheet (JSON + CSVs)  │   │ PostgreSQL 16                │
└────────────┬─────────────┘   │ • matches, innings,          │
             ▼                 │   deliveries, wickets        │
┌──────────────────────────┐   │ • players, aliases,          │
│ Sync worker + idempotent │──▶│   attributes, teams, venues  │
│ ingestion (checksums)    │   │ • scouting + team-innings    │
│ → dependent refresh      │   │   aggregates, WP curves      │
└──────────────────────────┘   │ • auction scenarios/history  │
                               └──────────────────────────────┘
```

---

## Tech Stack

- **Backend**: Python 3.9+, FastAPI, SQLAlchemy 2, Psycopg 3, Pydantic 2, Alembic
- **Database**: PostgreSQL 16
- **ML / data**: scikit-learn, pandas, NumPy, joblib
- **Frontend**: React 18, Vite 5, Tailwind CSS 3, React Router 6
- **Testing**: pytest, pytest-cov, FastAPI TestClient

---

## Installation & Setup

### 1. Prerequisites
- Python 3.9+
- Node.js 18+ and npm
- PostgreSQL 14+

### 2. Database
```bash
createuser -s cpi
createdb -O cpi cpi_db
psql -d cpi_db -c "ALTER USER cpi WITH PASSWORD 'cpi';"
```

### 3. Backend
```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp ../.env.example .env
alembic upgrade head
```

### 4. Load match data
```bash
python scripts/ingest.py --limit 100     # quick sample
python scripts/ingest.py --ipl-only      # IPL only
python scripts/ingest.py                 # everything configured
```

Then build the derived tables (see [Data Sync & Derived Tables](#data-sync--derived-tables)).

### 5. Run

Everything at once (API, Cricsheet sync worker and frontend):
```bash
./start.sh
```

Or separately:
```bash
cd backend && source .venv/bin/activate
uvicorn app.main:app --reload --port 8000
```
```bash
cd frontend
npm install
npm run dev
```

- App: `http://localhost:5173`
- API docs: `http://localhost:8000/api/docs`

`start.sh` warns if the database schema is behind the code. Apply migrations with `alembic upgrade head`.

---

## Data Sync & Derived Tables

A background worker checks Cricsheet every 6 hours (configurable in **Settings → Data Management**) and imports only new or corrected matches. It runs without the browser open.

```bash
backend/scripts/sync_worker.sh start|stop|status|logs   # manual control
backend/scripts/install_launchd.sh install              # optional: start at macOS login
```

After each import, `dependent_refresh` updates the derived data for the affected matches only: scouting aggregates, team-innings summaries, win-probability curves and player WPA. Caches are cleared at the same time.

To build the derived tables from scratch:
```bash
cd backend
.venv/bin/python scripts/build_scouting_aggregates.py      # ~3 min, all formats
.venv/bin/python scripts/build_team_innings_summary.py
.venv/bin/python scripts/precompute_win_probability_v2.py
```

Design, API and recovery behaviour: [docs/DATA_SYNC.md](docs/DATA_SYNC.md).

---

## Tests

```bash
cd backend
source .venv/bin/activate
pytest -v
```

The suite (about 340 tests across `tests/unit` and `tests/integration`) covers:

- Cricket rules: legal deliveries, balls faced, runs conceded, dismissal credit, zero-division handling
- Cricsheet parsing, idempotent ingestion and sync
- Scorecards, team records and ground analytics
- Player performance filters, matchups, format isolation and similarity
- Scouting statistics, engine and v2 API
- Team, venue and tournament analytics
- Match simulator, regression checks and simulator win probability
- Win probability v2: feature construction, orientation, decided and impossible states
- Auction rules, CSV import and price model
- Playing XI upload

---

## Further Documentation

| Document | Contents |
|---|---|
| [docs/cricket-rules.md](docs/cricket-rules.md) | Scoring rules reference |
| [docs/data-dictionary.md](docs/data-dictionary.md) | Schema and field definitions |
| [docs/DATA_SYNC.md](docs/DATA_SYNC.md) | Cricsheet sync worker & background updates |
| [backend/artifacts/win_probability/v2/REPORT.md](backend/artifacts/win_probability/v2/REPORT.md) | Win-probability model evaluation & metrics |

---

## License & Acknowledgements

Match data from [Cricsheet](https://cricsheet.org/), under the Open Database License (ODbL).
