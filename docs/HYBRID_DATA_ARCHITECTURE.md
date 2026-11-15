# Hybrid data engine: audit, architecture and coverage report

Status as of 2026-11-15 on the local CPI database (23,241 Cricsheet matches,
11.7M deliveries).

## 1. Audit: why career totals were incomplete

**The cause is source coverage. Ingestion did not fail.**

| Check | Finding |
|---|---|
| Failed imports | None. The Cricsheet archive lists 23,241 matches and all 23,241 are in CPI (`source_inventory`: 0 missing, 0 failed). |
| Withheld by source | Cricsheet withholds 386 matches (Afghanistan men, Afghanistan Premier League) by policy. They cannot be obtained from Cricsheet. |
| Earliest data | Tests from 2001-12-19, ODIs from 2002-06-27, T20Is from 2005, MDM from 2006, ODM from 2010. Cricsheet publishes nothing earlier. |
| Early-era density | Cricsheet has only 1–24 men's Tests a year for 2001–2005, against roughly 40–50 played. Coverage ramps up around 2006 (ODIs around 2003). |
| Incomplete innings | 14 innings had no deliveries. All are **forfeited** innings in multi-day matches, so they are complete by definition. 2 T20Is have one innings because the result was **awarded**. No match has gaps in its over sequence. |
| Duplicate matches | 298 groups share date, teams and venue. On inspection these are men's and women's double-headers (team ids span genders) or same-day associate fixtures. After the identity rules in §3, 0 true duplicates remain and 137 same-day pairs are correctly kept apart. |
| Player identity | Correct. Tendulkar is one player (`d2c2b2d5`). Name-based lookups do fail ("MS Dhoni" is stored as "Mahendra Singh Dhoni"), so identity resolution now uses Cricsheet register IDs. |
| Aggregation across formats | Correct per format. Every analytic is computed from delivery rows of the format requested. |
| Match counts | Deliveries only show players who batted, bowled or took a dismissal, so appearances were under-counted (Tendulkar ODIs: 144 → 146 with playing XIs). XIs are now stored. |
| Domestic cricket | Indian domestic first-class and List A cricket (Ranji, Duleep, Vijay Hazare) is not in Cricsheet at all. Syed Mushtaq Ali Trophy appears only from recent seasons. |

**Example: Sachin Tendulkar.** CPI held 82 of 200 Tests and 146 of 463 ODIs,
all from Dec 2001 onward. His 1989–2001 career is not in any integrated source.

## 2. Architecture

```
               canonical_matches  (one CPI identity per real match + coverage class)
                 │ match_id (nullable)            │
     ┌───────────┴────────────┐       ┌───────────┴─────────────────────────┐
     │ BALL-BY-BALL LAYER      │       │ SCORECARD LAYER                     │
     │ matches / match_innings │       │ scorecard_innings / _batting /      │
     │ deliveries / wickets    │       │ _bowling   (NULL = not in source)   │
     │ (unchanged)             │       │                                     │
     └───────────┬────────────┘       └───────────┬─────────────────────────┘
                 └──── match_source_refs (every source's own id + match evidence)
                       match_appearances (playing XIs, any source)
                       reconciliation_flags (disagreements, both values kept)
                       source_inventory (what a source lists vs what CPI holds)
```

* **Existing tables are untouched.** The migration (`20261119hyb1`) only adds
  tables and is reversible (`alembic downgrade -1`). Every existing analytics
  module still reads only `matches`/`deliveries`, so scorecard data cannot
  reach matchups, phases, boundary or dismissal patterns, or predictive
  features. An integration test asserts that scorecard imports leave the
  ball-by-ball tables unchanged.
* **Incremental.** `MatchImporter` registers each imported match (in a
  savepoint that never blocks the import). `scripts/backfill_hybrid_registry.py`
  covers an existing database in about 5 minutes and is idempotent.
* Code lives in `backend/app/hybrid/`: `coverage`, `identity`, `reconcile`,
  `eligibility`, `career`, `reconstruction`, `health`, `registry`, `people`, and
  `sources/` (independent adapters plus `catalog.py`).

### Coverage classes

`FULL_BALL_BY_BALL`, `PARTIAL_BALL_BY_BALL`, `SCORECARD_ONLY`,
`METADATA_ONLY`, `UNKNOWN`. A match with only a scorecard can never be FULL.
A match is PARTIAL when an innings has no deliveries (unless it was
forfeited), when its over sequence has gaps, or when a limited-overs result
needs both innings and one is missing (unless the result was awarded).
Each match also stores innings available and expected, deliveries, source
count, Cricsheet `info.missing` markers, validation status and last ingestion.

## 3. Cross-source match identity

Hard constraints: same gender, compatible format (FIRST_CLASS↔MULTI_DAY and
LIST_A↔ONE_DAY are compatible), the same two teams, and start dates no more
than 1 day apart (2 days for multi-day). Candidates are then scored on venue
similarity, competition, result and innings totals. If every shared innings
total differs, the records are different fixtures. If two candidates score
within 2 points of each other, nothing is merged and the record is held as
*ambiguous* for review.

## 4. Unified statistics

The unit of aggregation is one (canonical match, innings, player), counted once.
Precedence when sources disagree is documented in `reconcile.py`:

1. Complete ball-by-ball data wins.
2. If delivery data is partial, a validated scorecard is used.
3. If two scorecards disagree, the value is left unresolved.

Every disagreement is written to `reconciliation_flags` with all source values.
Each metric is reported with a status (`verified`, `derived`, `incomplete` or
`unavailable`) and its basis (*n of m innings*). Strike rate is never estimated
without balls faced, and economy never without legal balls. Wagon-wheel
analysis is unavailable because no source has shot locations.

## 5. Sources investigated

| Source | Data | Access | Integrated |
|---|---|---|---|
| Cricsheet | Ball-by-ball, 2001→ | Open, ODbL | Yes (primary; inventory adapter added) |
| Verified scorecard import | Scorecards | Each bundle must state its source and licence | Yes (adapter); **no data supplied yet** |
| ESPNcricinfo / Statsguru | Scorecards 1877→, Indian domestic | No public API. Automated requests refused (403). | No: needs a data licence |
| Howstat | Test and ODI scorecards | All rights reserved; 403 | No: needs permission |
| BCCI (bcci.tv) | Recent domestic seasons | No bulk export or licence | No: needs a BCCI data agreement |
| CricketArchive | Deepest first-class, List A and domestic archive | Paid; reuse needs a licence | No: best candidate for a licence |
| Cricket Database API (already configured) | Player lookup and basic stats | API key | Unchanged. Scorecard capability not verified. |

Cricsheet's people register (now stored in `player_external_ids`: 23,041 IDs
for 15,077 players) maps CPI players to Cricinfo, CricketArchive and BCCI IDs.
Any licensed scorecards from those providers will therefore resolve players by
ID, not by name.

## 6. Results

* **Matches recovered: 0.** Nothing was missing from what Cricsheet publishes.
  Recovering pre-2001 and domestic history requires a licensed scorecard source.
* **Corrected:** match appearance counts (playing XIs), coverage labels, and
  2 awarded T20Is that would otherwise have been mislabelled partial.
* **Benchmark validation** (`scripts/validate_career_benchmarks.py`). In every
  row, the engine total equals an independent SQL sum of deliveries.

| Player | Format | CPI | Published | Coverage | Gap flagged |
|---|---|---:|---:|---:|---|
| SR Tendulkar | Test | 6,416 | 15,921 | 40.3% | yes |
| SR Tendulkar | ODI | 6,433 | 18,426 | 34.9% | yes |
| R Dravid | Test / ODI | 5,925 / 3,723 | 13,288 / 10,889 | 44.6% / 34.2% | yes |
| RT Ponting | Test / ODI | 6,733 / 6,979 | 13,378 / 13,704 | 50.3% / 50.9% | yes |
| JH Kallis | Test / ODI | 7,405 / 4,929 | 13,289 / 11,579 | 55.7% / 42.6% | yes |
| KC Sangakkara | Test / ODI | 8,489 / 11,640 | 12,400 / 14,234 | 68.5% / 81.8% | yes |
| BC Lara | Test / ODI | 2,036 / 1,878 | 11,953 / 10,405 | 17.0% / 18.0% | yes |
| AN Cook | Test / ODI | **12,472 / 3,204** | 12,472 / 3,204 | **100% / 100%** | — |
| MS Dhoni | Test / ODI / T20I | 4,721 / 10,274 / 1,584 | 4,876 / 10,773 / 1,617 | 96.8% / 95.4% / 98.0% | T20I only |
| AB de Villiers | Test / ODI / T20I | 8,182 / 9,435 / 1,591 | 8,765 / 9,577 / 1,672 | 93.3% / 98.5% / 95.2% | T20I only |

Cook's career falls entirely inside the covered era and reconstructs exactly.
That confirms the aggregation is right where data exists. Benchmarks are
used only to measure the gap. They are never stored or used in any statistic.

## 7. Remaining gaps (not closed)

1. All international cricket before Dec 2001 (Tests) and Jun 2002 (ODIs).
2. Sparse early Cricsheet years: most 2001–2005 Tests are absent.
3. Small numbers of missing matches inside the covered era (for example, Dhoni's
   ODI gap of 499 runs and de Villiers's Test gap of 583 runs). The CPI data
   cannot locate these without an external fixture list, so they are not flagged per player.
4. Indian domestic first-class and List A cricket (Ranji, Duleep, Vijay Hazare)
   in every era.
5. The 386 matches Cricsheet withholds.

Closing items 1–4 needs a licensed scorecard source (CricketArchive,
ESPNcricinfo or BCCI) imported through the scorecard adapter.
