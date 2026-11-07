# Cricket Performance Intelligence (CPI)

<div align="center">

![Python](https://img.shields.io/badge/Python-3.9%2B-blue?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.109%2B-009688?logo=fastapi&logoColor=white)
![React](https://img.shields.io/badge/React-18-61DAFB?logo=react&logoColor=black)
![Vite](https://img.shields.io/badge/Vite-5.4-646CFF?logo=vite&logoColor=white)
![TailwindCSS](https://img.shields.io/badge/Tailwind-3.4-38B2AC?logo=tailwind-css&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-336791?logo=postgresql&logoColor=white)
![Scikit--Learn](https://img.shields.io/badge/Scikit--Learn-1.4-F7931E?logo=scikit-learn&logoColor=white)
![Pytest](https://img.shields.io/badge/Tests-121%20Passed-brightgreen?logo=pytest&logoColor=white)

**An enterprise-grade cricket analytics, scouting, and tactical intelligence platform powered by delivery-level match data, authoritative scoring rules, and machine learning.**

</div>

---

## Table of Contents
1. [Overview & Motivation](#overview--motivation)
2. [Target Audience & Key Use Cases](#target-audience--key-use-cases)
3. [Key Capabilities](#key-capabilities)
   - [Players Directory & Individual Profile Workspace](#1-players-directory--individual-profile-workspace)
   - [Matchup Intelligence Engine](#2-matchup-intelligence-engine)
   - [Pace vs Spin & Phase-Wise Analytics](#3-pace-vs-spin--phase-wise-analytics)
   - [Multi-Format Independence (T20 vs T20I vs ODI vs Test)](#4-multi-format-independence)
   - [Explainable Scouting & Recruitment](#5-explainable-scouting--recruitment)
   - [Machine Learning Player Similarity](#6-machine-learning-player-similarity)
   - [Venues & Ground Scoring Benchmarks](#7-venues--ground-scoring-benchmarks)
4. [Authoritative Cricket Rules & Statistical Integrity](#authoritative-cricket-rules--statistical-integrity)
5. [System Architecture](#system-architecture)
6. [Tech Stack](#tech-stack)
7. [Installation & Setup](#installation--setup)
8. [Automated Verification & Test Suite](#automated-verification--test-suite)
9. [License & Acknowledgements](#license--acknowledgements)

---

## Overview & Motivation

In modern professional cricket, traditional aggregate statistics (e.g. career batting average, overall strike rate, economy rate) often disguise critical tactical truths:
- A batter with an overall strike rate of 135 may strike at 155 against pace bowling but collapse to 98 against spin.
- A bowler with an economy of 7.8 may concede only 6.1 in the Powerplay while struggling in death overs (11.4).
- Small-sample head-to-head records are frequently over-indexed without confidence warnings or dismissal attribution.
- Domestic franchise tournaments (IPL, BBL, PSL) are often blended into international T20I statistics, corrupting scouting models.

**Cricket Performance Intelligence (CPI)** resolves these challenges. By ingesting raw ball-by-ball delivery records (7,940+ matches, 2.23M+ deliveries, and 9,900+ players) into a normalized PostgreSQL schema, CPI calculates every metric on demand using authoritative cricket rules and exposes it through a dark navy analytics workspace built for high-performance decision making.

---

## Target Audience & Key Use Cases

| Persona | Practical Use Cases & Benefits |
| :--- | :--- |
| **Franchise & National Team Analysts** | • Construct evidence-backed pre-match tactical matchup boards for opposition batters vs bowling attack.<br>• Identify entry-point windows based on phase scoring rates and pace vs spin differentials.<br>• Evaluate venue-specific first vs second innings scoring trends to optimize toss decisions. |
| **Talent Scouts & Recruitment Committees** | • Screen thousands of global players using multi-criteria weighted scouting engines.<br>• Filter candidates by boundary percentage, death-over economy discipline, and minimum sample thresholds.<br>• Uncover statistically analogous player clones using the ML Cosine Similarity engine for injury replacements or auction bidding. |
| **High-Performance Coaches & Directors** | • Inspect automated, data-driven strengths and vulnerabilities extracted from ball-by-ball records.<br>• Track multi-year career trajectory, workload management, and recent form across formats.<br>• Benchmark squad players side-by-side across phases and opposition teams. |
| **Broadcasters, Analysts & Journalists** | • Verify head-to-head matchup records, dismissal categorizations, and historical performance trends in seconds.<br>• Export clean, publication-ready datasets to CSV for external models or editorial graphics. |

---

## Key Capabilities

### 1. Players Directory & Individual Profile Workspace
- **Clean Player Directory**: Fast player discovery displaying essential metrics: Player Name, Role badge (`Batter`, `Bowler`, `All-Rounder`), Matches, Runs, Batting Average, Strike Rate, and Wickets. Includes format pills (`All`, `T20I`, `T20`, `ODI`, `Test`), instant search, sortable headers, and pagination.
- **Dedicated Player Profile Workspace**: Moving beyond basic summary cards, each individual profile provides:
  - Career & filtered batting and bowling benchmarks.
  - Multi-format breakdown comparing `Test`, `ODI`, `T20`, and `T20I` side-by-side.
  - Dynamic profile-level filters: **Format**, **Start & End Year**, **Season**, **Opponent Team**, **Venue**, **Bowler Style (Pace vs Spin)**, and **Match Phase**.
  - Opponent team breakdown (top 15 teams faced).
  - Venue breakdown (top grounds played at).
  - Year-by-year performance trajectory and recent match logs (last 10 matches).
  - Automated tactical strengths and vulnerabilities.
  - One-click **Export Profile CSV**.

### 2. Matchup Intelligence Engine
- Select any batter against any bowler across the entire database.
- Complete delivery-level metrics: runs scored, balls faced, strike rate, dismissals, dot-ball %, boundary %, 4s, and 6s.
- **Dismissal Categorization**: Explicitly isolates bowler-credited wickets (bowled, caught, lbw, stumped, hit wicket) from fielding-only events (run outs, retired hurt).
- **Over-by-Over Breakdown**: Performance across specific overs (e.g. over 1 through 20).
- **Match-by-Match Log**: Date, tournament, venue, innings, runs, balls, strike rate, and dismissals for every encounter.
- **Visual Trends**: Performance trajectory over time with interactive charts.

### 3. Pace vs Spin & Phase-Wise Analytics
- **Pace vs Spin Intelligence**: Backed by a curated registry of 160+ top bowlers categorized into pace and spin styles, providing exact runs, balls, strike rate, boundary %, and dot-ball % against each bowling style.
- **Phase Segmentation**: Automatic partitioning of matches into:
  - **Powerplay** (Overs 1–6): Initial field restriction phase.
  - **Middle Overs** (Overs 7–15): Spin control and strike rotation.
  - **Death Overs** (Overs 16–20): High-leverage boundary hitting and yorker execution.

### 4. Multi-Format Independence
- **T20 (Franchise / Domestic)**: 1,618 matches (IPL, BBL, PSL, etc.).
- **T20I (International)**: 5,783 international matches.
- **ODI**: 184 international matches.
- **Test**: 65 test matches.
- Strict database-level isolation guarantees domestic franchise cricket and international cricket are never mixed together.

### 5. Explainable Scouting & Recruitment
- Multi-criteria weighted ranking engine allowing scouts to set custom weights for:
  - Batting Volume & Average
  - Strike Rate & Boundary Percentage
  - Dot-Ball Minimization
  - Phase-Specific Strike Rates (Powerplay / Middle / Death)
  - Bowling Economy & Strike Rate
  - Death Overs Economy Control
- Enforces sample size gates (min innings, min balls faced, min overs).
- Generates human-readable explanations detailing why a candidate ranked highly and where their tactical limitations lie.

### 6. Machine Learning Player Similarity
- Feature extraction across 8 normalized dimensions: Batting Average, Strike Rate, Boundary %, Dot-Ball %, Powerplay SR, Middle SR, Death SR, and Match Volume.
- Scikit-learn `StandardScaler` normalizer combined with `NearestNeighbors` (Cosine distance).
- Outputs top statistical analogs with percentage match scores and explanations of alignment.

### 7. Venues & Ground Scoring Benchmarks
- Profiles 380+ grounds worldwide.
- Benchmarks 1st innings vs 2nd innings average scores.
- Classifies grounds into high-scoring, balanced, or bowling-friendly venues.
- Team chasing vs batting-first win percentages to inform toss strategy.

---

## Authoritative Cricket Rules & Statistical Integrity

All statistical calculations strictly adhere to international cricket laws and official scoring conventions:

1. **Legal Deliveries**:
   - A wide ball is **not** a legal delivery and does **not** count towards the over ball count.
   - A no-ball is **not** a legal delivery and does **not** count towards the over ball count.
   - Byes, leg-byes, and penalty runs on legal deliveries **are** counted as legal balls.
2. **Balls Faced by Batter**:
   - Deliveries where the batter faced the ball (including normal deliveries, no-balls, byes, and leg-byes) count as balls faced.
   - Wides do **not** count as balls faced by the batter.
3. **Batter Runs vs Bowling Runs Conceded**:
   - Batter runs include only runs off the bat (plus boundary 4s and 6s).
   - Bowling runs conceded include batter runs, wides, and no-ball extras.
   - Byes and leg-byes are **excluded** from bowler runs conceded and do not penalize bowler economy.
4. **Wicket Credit Separation**:
   - Bowler wickets include: `bowled`, `caught`, `caught and bowled`, `lbw`, `stumped`, and `hit wicket`.
   - Non-bowler dismissals include: `run out`, `obstructing the field`, `retired hurt`, and `retired out`. These do **not** credit the bowler.
5. **Rate Statistics**:
   - Batting Strike Rate = $(\text{Batter Runs} \times 100) / \text{Balls Faced}$.
   - Bowling Economy Rate = $(\text{Runs Conceded} \times 6) / \text{Legal Balls}$.
   - Bowling Average = $\text{Runs Conceded} / \text{Bowler Wickets}$.
   - Bowling Strike Rate = $\text{Legal Balls} / \text{Bowler Wickets}$.
   - All rate statistics safely handle division by zero and return `null` (`—`) when sample is zero.
6. **Super Overs**:
   - Super overs are partitioned from standard innings calculations to prevent distorting career statistics.

---

## System Architecture

```
                               ┌──────────────────────────────────────────────┐
                               │       React 18 + Vite Analytics UI           │
                               │  (Tailwind CSS, Sports Analytics Aesthetic)  │
                               └──────────────────────┬───────────────────────┘
                                                      │ REST JSON API
                                                      ▼
                               ┌──────────────────────────────────────────────┐
                               │           FastAPI Application Server         │
                               ├──────────────────────────────────────────────┤
                               │ • Routing & Query Serialization              │
                               │ • Unified SQL CTE Engine (Fast In-DB Agg)    │
                               │ • Pure Domain Analytics (Batting & Bowling)  │
                               │ • ML Player Similarity Engine (Cosine KNN)   │
                               │ • Weighted Scouting Ranker                   │
                               └──────────────────────┬───────────────────────┘
                                                      │ SQLAlchemy / Psycopg3
                                                      ▼
┌──────────────────────────────────────┐       ┌──────────────────────────────┐
│       Raw Cricsheet Match Data       │       │    PostgreSQL 16 Database    │
│  (JSON Schemas, SHA-256 Checksums)   │       ├──────────────────────────────┤
└──────────────────┬───────────────────┘       │ • matches & match_innings    │
                   │                           │ • deliveries & wickets       │
                   ▼                           │ • players & player_aliases   │
┌──────────────────────────────────────┐       │ • player_attributes (styles) │
│       Idempotent Ingestion Engine    │──────▶│ • teams & venues             │
│ (Change Detection, Audit Run Logs)   │       │ • Composite Performance Idxs │
└──────────────────────────────────────┘       └──────────────────────────────┘
```

---

## Tech Stack

- **Backend**: Python 3.9+, FastAPI, SQLAlchemy 2.0, Psycopg 3, Pydantic v2
- **Database**: PostgreSQL 16
- **Machine Learning**: Scikit-Learn (NearestNeighbors, StandardScaler), Pandas, NumPy
- **Frontend**: React 18, Vite 5, Tailwind CSS 3, React Router v6
- **Testing**: Pytest, Pytest-Cov, FastAPI TestClient

---

## Installation & Setup

### 1. Prerequisites
- Python 3.9 or higher
- Node.js 18+ & npm
- PostgreSQL 14+ running locally or remotely

### 2. Database Initialization
Create the user and database in PostgreSQL:
```bash
createuser -s cpi
createdb -O cpi cpi_db
psql -d cpi_db -c "ALTER USER cpi WITH PASSWORD 'cpi';"
```

### 3. Backend Setup
```bash
cd backend

# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp ../.env.example .env

# Run database schema migrations
alembic upgrade head
```

### 4. Ingesting Match Data
Run the idempotent ingestion pipeline to populate the database:
```bash
# Ingest 100 sample matches
python scripts/ingest.py --limit 100

# Or ingest full IPL / T20 archive
python scripts/ingest.py --ipl-only
```

### 5. Launch the Servers

**Backend API:**
```bash
cd backend
source .venv/bin/activate
uvicorn app.main:app --reload --port 8000
```
Interactive API docs: `http://localhost:8000/api/docs`

**Frontend Analytics UI:**
```bash
cd frontend
npm install
npm run dev
```
Open `http://localhost:5173` in your browser.

---

## Automated Verification & Test Suite

The repository contains an automated test suite comprising **121 tests** covering legal cricket rules, data parsing, machine learning, and API endpoints:

```bash
cd backend
source .venv/bin/activate
pytest -v
```

### Validated Areas:
- **Cricket Rules**: Legal delivery classification (wides, no-balls, byes, leg-byes), batter balls faced, bowler runs conceded, dismissal attribution, and zero-division safety.
- **Cricsheet Ingestion**: SHA-256 checksum idempotency, entity reconciliation, and run total consistency.
- **Matchup Intelligence**: Summary calculations, dismissal breakdowns, over-by-over queries, trends, and no-data pairs.
- **Format Isolation**: Verifies that `T20` (franchise) and `T20I` (international) remain completely separated.
- **Player Performance & Profile**: Comprehensive filtering (format, year range, pace/spin, phases, opponents, venues) and ML similarity.

---

## License & Acknowledgements

- Match data supplied by [Cricsheet](https://cricsheet.org/) under the Open Database License (ODbL).
- Built with Google Antigravity.
