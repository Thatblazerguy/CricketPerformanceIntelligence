# CPI Design Notes

> Drafted with AI assistance from the code; reviewed by the author.

This document describes the non-obvious design decisions embedded in the Cricket Performance Intelligence codebase. It is intended for contributors who want to understand *why* things are done the way they are, not just *what* they do.

---

## 1. Elo Rating Lag

**Location:** `backend/app/ml/wp/constants.py` (`ELO_RESULT_LAG_DAYS`), `backend/tests/unit/test_win_probability_v2.py` (`test_elo_uses_only_results_available_before_the_match`)

Elo ratings are used as a pre-match strength signal — they must reflect only information that was knowable *before* a given match started. The naive approach (sort by date, update ratings, read them back) fails for two cases:

1. **Same-day matches.** Two T20s on the same day cannot "know" each other's results. The lag for limited-overs formats is set to 1 day, so the result of match A on date D is not applied to Elo until computing ratings for matches on date D+1 or later.
2. **Multi-day matches.** A Test match starting on day 1 may not finish until day 5. Its result cannot update Elo until day 6 (lag = 5 for Test, 4 for MDM), preventing look-ahead leakage across overlapping or closely-spaced multi-day matches.

The unit test verifies both guarantees:
- Matches on the same date see identical Elo ratings (1500, the starting value).
- A Test match still in progress does not update Elo for another match starting 2 days later.

Elo pools are format-grouped: T20 and T20I share one pool (`t20`); ODI and ODM share another (`one_day`); Test and MDM share a third (`multi_day`). This reflects the different competitive contexts without attempting to merge across formats.

---

## 2. Resource Table (Training-Only)

**Location:** `backend/app/ml/wp/features.py` (`fit_resource_table`), `backend/tests/unit/test_win_probability_v2.py` (`test_resource_table_is_monotone`)

The resource table encodes how many runs a team is *expected* to score from a given (balls remaining, wickets lost) state. It is a 2-D lookup table fit from first-innings training data only and constrained to be monotone in both dimensions (more balls = more runs; fewer wickets remaining = fewer runs).

This table serves as a compressed representation of scoring-rate potential and is used as a feature input to the main logistic regression model. It is *not* recalculated at prediction time — the table from training is serialised with the model artifacts and applied unchanged at inference.

The training-only constraint is essential: fitting the table on all data, then using it in model training, would leak second-innings information into first-innings feature construction.

---

## 3. Par Values (Venue and Era)

**Location:** `backend/app/ml/wp/constants.py` (`VENUE_SHRINK`, `ERA_WINDOW_DAYS`, `ERA_MIN_INNINGS`), `backend/tests/unit/test_win_probability_v2.py` (`test_venue_and_era_par_only_use_earlier_matches`)

Par scores capture what a typical team scores at a particular venue in a particular era. They are computed with a strict causal ordering: the par for match M is derived from matches that *finished before* M started, never including M itself.

Venue par uses a shrinkage estimator (`VENUE_SHRINK = 8` pseudo-innings) towards the era par to regularise sparse venues. Era par is computed from a 730-day rolling window requiring at least 20 innings.

The unit test verifies that the first match at a venue has NaN venue par (no prior data), and that neither the match's own innings nor any later match contaminates the estimate.

---

## 4. Chronological 60/15/10/15 Partitions

**Location:** `backend/app/ml/wp/constants.py` (`PARTITIONS`), `backend/tests/unit/test_win_probability_v2.py` (`test_partitions_are_chronological_and_never_split_a_date`)

Labelled matches (those with a decided result) are split into four non-overlapping, strictly chronological partitions:

| Partition    | Fraction | Purpose                                           |
|--------------|----------|---------------------------------------------------|
| `train`      | 60%      | Feature construction, model fitting               |
| `validation` | 15%      | Hyperparameter selection, early stopping          |
| `calibration`| 10%      | Post-hoc probability calibration                  |
| `test`       | 15%      | Final held-out evaluation (never touched in training) |

A key invariant: **no calendar date is split across partitions.** All matches on a given date belong to the same partition. This prevents the pathological case where knowledge from later-on-the-same-day matches bleeds into earlier ones through shared date-level features.

The model evaluation report (`backend/artifacts/win_probability/v2/REPORT.md`) shows test-partition date ranges per format family (e.g. T20 test partition: 2025-08-30 to 2026-11-03).

---

## 5. Why v1 Failed

**Location:** `backend/app/ml/win_probability.py` (legacy), `backend/artifacts/win_probability/v2/REPORT.md` (ablation comparison)

The legacy v1 model (`cpi-wp-v1`) used highly regularised logistic regression (`C=1e-4`) with features anchored to `team1` as a fixed reference frame (e.g. `team1_batting`, `team1_runs`, `lead_from_team1`). This produced two problems:

1. **Poor calibration.** The v1 T20 ECE on the test partition is 0.1632 — far above the v2 value of 0.0127. The heavy regularisation compressed predicted probabilities toward 0.5, making v1 systematically overconfident at match start and underconfident during blowouts.
2. **No strength signal.** v1 did not incorporate Elo ratings, venue par, or era par. The ablation table in REPORT.md shows that even the Elo-only baseline outperforms legacy v1 on T20 skill vs prior (+0.075 vs +0.090), and venue-par alone beats v1 on most formats.

The v2 rewrite addressed both issues by: (a) switching from team1/team2 frame to batting/bowling frame (invariant to team labelling order), (b) adding Elo, venue-par, and era-par signals, (c) using the full 60/15/10/15 chronological split with a separate calibration partition, and (d) relaxing regularisation.

---

## 6. Idempotent Ingestion

**Location:** `backend/app/ingestion/importer.py`

The ingestion pipeline is designed to be safe to re-run against the same data:

- Each match JSON is hashed (SHA-256 or similar checksum) on import.
- On re-run, if the stored checksum matches the incoming file, the match is **skipped** immediately with no database writes.
- If the checksum has changed (a Cricsheet correction), the match is **replaced**: its innings and delivery records are deleted and re-inserted within a transaction, then dependent statistics are recalculated.
- A `--force` flag bypasses checksum comparison to reprocess all files (used after parser rule changes).

This means the ingestion scripts (`backend/scripts/ingest_gamedata.py`) can be run repeatedly in a development or Docker environment without accumulating duplicate rows or corrupting aggregates.

---

## 7. Limitations

- **No live data.** CPI ingests from Cricsheet, which publishes ball-by-ball data with a lag of hours to days after a match. There is no real-time data source.
- **Win probability for Test / MDM is weaker.** The Test Brier score (0.434) reflects the genuine difficulty of multi-day match prediction from score-state alone — declarations, follow-on, session context, and remaining time are not available in the Cricsheet schema.
- **No LightGBM or XGBoost.** The win probability model uses logistic regression because gradient-boosted tree libraries are not installed in the default CPI environment. The evaluation report notes both as "not installed." The logistic model is competitive but leaves accuracy on the table, especially in innings 1 power-play.
- **Player similarity uses cosine distance on counting stats.** This is a reasonable baseline but does not adjust for era, opposition quality, or conditions.
- **Auction price model uses IPL salary data only.** Estimates for players who have never been in an IPL auction are extrapolated; treat them as rough order-of-magnitude signals.
- **Historical Elo ratings are retrospective.** They are computed from the full CPI dataset and reflect the entire match history, not ratings that were published in real time by any organisation.

