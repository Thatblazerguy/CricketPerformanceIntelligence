# Cricket Performance Intelligence (CPI)

## Product Requirements Document (PRD)

**Document:** `PRD.md`\
**Version:** 1.0\
**Status:** Proposed\
**Product:** Cricket Performance Intelligence\
**Primary market/use case:** IPL franchise scouting and match
preparation\
**Initial formats:** IPL and Men's T20 Internationals\
**Primary data source:** Cricsheet JSON\
**Secondary data source:** OpenCricket API, subject to verified endpoint
and plan access

------------------------------------------------------------------------

## 1. Product Summary

Cricket Performance Intelligence (CPI) is a cricket analytics and
recruitment intelligence platform that converts historical ball-by-ball
data into evidence-based insights for player evaluation, recruitment,
comparison and match preparation.

CPI is not intended to be a generic scorecard website or a dashboard
that simply displays career totals. Its central purpose is to help
analysts answer practical cricketing questions and understand the
evidence behind each answer.

The first major use case is IPL franchise player scouting. An analyst
should be able to describe a recruitment requirement, filter eligible
players, compare candidates and receive an explainable shortlist
supported by measurable statistics.

CPI will initially focus on reliable descriptive analytics and
explainable statistical scoring. Machine learning will be introduced
where it provides a measurable benefit, rather than being added only for
appearance.

## 2. Product Vision

Build a credible sports technology product that helps cricket analysts,
scouts and team staff turn historical cricket data into actionable
decisions.

CPI should eventually answer questions such as:

-   Which batters perform best against spin?
-   Which players score effectively during overs 7-15?
-   Which players have similar statistical profiles?
-   Who could replace a particular player in a defined role?
-   Which players appear undervalued relative to a team's requirements?
-   What are an opposition team's batting or bowling weaknesses?
-   How reliable is the evidence behind a particular recommendation?
-   What performance might be expected in a future match, and how
    uncertain is that estimate?

## 3. Goals and Non-Goals

### 3.1 Goals

1.  Import historical IPL and Men's T20I ball-by-ball data reliably.
2.  Preserve source data and provenance so records can be audited and
    reprocessed.
3.  Calculate batting, bowling, phase-wise and matchup statistics
    correctly.
4.  Provide player profiles and multi-player comparisons.
5.  Support role-specific scouting filters and explainable recruitment
    rankings.
6.  Implement a player similarity model using well-defined statistical
    features.
7.  Establish a reproducible ML training and evaluation pipeline.
8.  Clearly communicate sample sizes, data coverage, limitations and
    uncertainty.
9.  Support automated discovery and ingestion of newly available
    matches.
10. Deliver a professional, data-focused interface.

### 3.2 Non-Goals for v1

-   Real-time ball-by-ball live match tracking.
-   Guaranteed coverage of every domestic or franchise competition.
-   Automated auction-price or market-value prediction.
-   Computer vision, video analysis or shot-location reconstruction.
-   Deep learning or large language models as a core analytics
    dependency.
-   Claims that similarity equals ability or that a prediction is
    certain.
-   Microservices, distributed streaming infrastructure or Kubernetes.
-   Paid API dependencies before the free-data workflow is validated.

## 4. Target Users

### Cricket Analysts

-   Analyse players, teams and matchups.
-   Prepare reports and identify trends.
-   Evaluate opposition strengths and weaknesses.

### Talent Scouts

-   Discover emerging and under-recognised players.
-   Compare candidates by role.
-   Build recruitment shortlists.

### Coaches and Team Management

-   Review player suitability.
-   Examine batter-bowler matchups.
-   Prepare tactical plans.

### Cricket Enthusiasts

-   Explore detailed player and team statistics.
-   Compare players and understand trends.

The initial product should optimise for analysts and scouts. Other user
groups can use the same core analytics with simpler navigation.

## 5. Primary User Journey

**Scenario:** An IPL franchise needs an Indian middle-order batter who
performs well against spin and scores quickly during the middle overs.

1.  The analyst opens the Scouting module.
2.  The analyst selects format, competition, seasons, nationality, role
    and minimum sample requirements.
3.  The analyst configures priorities such as spin performance,
    middle-over scoring, consistency and experience.
4.  CPI filters players using hard eligibility constraints.
5.  CPI calculates or retrieves comparable player features.
6.  CPI ranks eligible candidates using a transparent scoring
    configuration.
7.  The analyst opens a candidate profile to inspect supporting
    statistics and sample sizes.
8.  The analyst compares shortlisted players.
9.  The analyst exports a scouting report.

The system must explain why each candidate appears in the shortlist. It
must not present an unexplained AI-generated ranking.

## 6. Product Scope and Modules

### 6.1 Overview Dashboard

Display: - Number of players, teams, matches and tournaments in the
current dataset. - Dataset coverage by competition and season. -
Top-performing batters and bowlers, with filters. - Recent imported
matches. - Key trends and ingestion status.

Every statistic must indicate its competition, format, season range and
relevant sample size.

### 6.2 Player Performance Profiles

Each player profile should include:

**Batting** - Runs, innings, not-outs, dismissals and average. - Balls
faced and strike rate. - Highest score. - Fours and sixes. - Boundary
and dot-ball percentages.

**Bowling** - Wickets credited to the bowler. - Legal balls and overs
display. - Runs conceded for bowling figures. - Economy, bowling average
and bowling strike rate. - Dot-ball and boundary-concession rates.

**Contextual analysis** - Performance by innings and batting position. -
Powerplay, middle-over and death-over performance. - Performance against
pace and spin only where bowling-style metadata is sufficiently
reliable. - Season and competition comparisons. - Recent form using a
clearly defined window.

### 6.3 Phase-wise Analysis

For T20 cricket: - Powerplay: overs 1-6. - Middle overs: overs 7-15. -
Death overs: overs 16-20.

Display runs, legal balls, strike rate, dot-ball percentage, boundary
percentage and relevant wickets. Batting and bowling metrics must use
their own correct denominators.

### 6.4 Batter-Bowler Matchup Analysis

Allow an analyst to select a batter and bowler and inspect: - Balls
faced and legal balls faced. - Runs off the bat and total runs where
relevant. - Strike rate. - Dismissals and dismissal types. - Dot-ball
and boundary rates. - Match phase and competition breakdown.

Always show sample size. Direct head-to-head samples must not be treated
as conclusive when small. Style-level or broader historical evidence may
supplement the direct matchup, but must be labelled separately.

### 6.5 Player Comparison

Allow comparison of two or more players across: - Batting and bowling
metrics. - Phase-wise performance. - Pace/spin performance when metadata
supports it. - Consistency and recent form. - Role-specific features.

Charts must use comparable filters and clearly disclose different sample
sizes.

### 6.6 Scouting and Recruitment

Support hard filters such as: - Competition, season and format. -
Nationality, when reliable metadata exists. - Player role and batting
position. - Batting and bowling style, when available. - Minimum
innings, balls faced or overs. - Average, strike rate and phase-specific
metrics.

Support configurable priorities and weights for: - Spin performance. -
Pace performance. - Middle-over scoring. - Death-over scoring. -
Consistency. - Experience and sample size.

The scouting system should separate: 1. Eligibility filtering. 2.
Statistical feature calculation. 3. Candidate scoring and ranking. 4.
Explanation and evidence display.

A high score means suitability for the configured requirement, not an
objective claim that the player is universally better.

### 6.7 Team Analytics

Analyse: - Wins, losses and win percentage where result data is
reliable. - First-innings and second-innings scoring. - Chasing and
batting-first performance. - Batting and bowling by phase. - Team
performance against pace and spin where metadata permits.

### 6.8 Venue Analysis

Analyse: - First- and second-innings scores. - Batting-first versus
chasing records. - Scoring patterns by innings and phase. - Player
performance at a venue.

Do not infer pitch conditions or ground dimensions from scorecards
alone.

### 6.9 Reports and Exports

Support CSV and PDF exports for: - Player profiles. - Player
comparisons. - Matchup analysis. - Scouting shortlists. - Team and venue
analysis.

Reports must include filters, data coverage, generation date and
caveats.

## 7. Data Strategy

### 7.1 Cricsheet

Cricsheet is the primary historical delivery-level source. Use its JSON
downloads as the canonical initial input for IPL and Men's T20I.

Cricsheet data supports historical ball-by-ball analysis but does not
guarantee complete coverage of all matches or all player attributes. CPI
must report actual imported coverage rather than imply completeness.

Use the original source file and metadata as the auditable raw record.
Do not discard source identifiers.

### 7.2 OpenCricket API

OpenCricket is a supplementary API provider. It may be used for match
discovery, scorecards, player information, fixtures or live scores only
where the currently available plan and endpoint documentation explicitly
support those capabilities.

Do not assume that the free plan provides unrestricted delivery-level
data. Do not duplicate paid API functionality when Cricsheet already
supplies the historical deliveries needed by CPI.

Verify current pricing, rate limits, endpoint availability, terms and
attribution requirements before implementation.

### 7.3 Provider Abstraction

Define a provider interface so that source-specific retrieval and
parsing are separate from the canonical CPI data model.

The analytics engine must consume normalised CPI records, not
provider-specific JSON structures.

### 7.4 Automated Ingestion

The ingestion process should: 1. Check supported recent-match archives
or provider endpoints. 2. Discover match identifiers. 3. Compare
identifiers and source checksums with stored records. 4. Download new or
revised source files. 5. Parse and normalise records. 6. Validate match
and innings totals. 7. Insert new records or update revised records
idempotently. 8. Recompute affected aggregates and features. 9. Record
sync results and errors. 10. Support manual re-sync and periodic full
reconciliation.

Recent-match archives are a discovery mechanism, not a guaranteed live
feed. Reconcile periodically against the relevant full archive to reduce
missed-match risk.

## 8. Data Quality and Cricket Rules

Correct cricket calculations are a release requirement.

-   A recorded delivery is not necessarily a legal ball.
-   Wides and no-balls are not legal deliveries.
-   Batting balls faced generally exclude wides; no-balls count as balls
    faced under standard scorekeeping conventions.
-   Batter runs, extras and total runs must be stored separately.
-   Bowling runs conceded must exclude byes and leg-byes, while
    including relevant wides and no-balls.
-   Bowler wickets must exclude dismissals that are not credited to the
    bowler, such as run-outs.
-   Multiple wicket events and unusual dismissal types must be
    represented.
-   Over and delivery identifiers must not be treated as decimal
    arithmetic.
-   Boundary counts must be based on actual boundary events and
    batter-run attribution, not simply total runs equal to four or six.
-   Super overs, retired hurt, retired out, obstructing the field and
    other unusual cases need explicit handling.
-   The implementation must document the chosen scorekeeping conventions
    and test them against trusted scorecards.

Store enough granular information to recalculate derived statistics when
business rules or parser logic change.

## 9. Machine Learning and Intelligence

CPI will use a staged approach. Statistical analysis comes first; ML is
added only when it solves a defined problem.

### 9.1 Player Performance Evaluation

**Initial implementation:** Explainable, role-specific statistical
scoring using normalised metrics and configurable weights.

Potential dimensions: - Strike-rate contribution. - Phase performance. -
Consistency. - Boundary and dot-ball profile. - Spin/pace performance
where metadata is reliable. - Recent form. - Experience and sample
reliability.

Do not call a hand-written weighted score a trained ML model. Label it
as a statistical evaluation score.

### 9.2 Player Similarity

**Initial ML model:** K-nearest neighbours using cosine distance or
another justified distance metric.

Inputs may include: - Batting average and strike rate. - Phase-wise
strike rates. - Dot-ball and boundary rates. - Pace/spin performance
where available. - Batting position and role context.

Requirements: - Use role-appropriate features. - Scale numerical
features. - Handle missing values deliberately. - Exclude or flag
players with inadequate samples. - Apply eligibility filters separately
from similarity. - Explain the largest feature similarities and
differences. - Do not equate similarity with quality.

### 9.3 Batter-Bowler Matchup Modelling

Start with descriptive matchup statistics and sample-size warnings.

A later supervised model may estimate delivery-level dismissal
probability or expected runs using only information available before the
delivery. Candidate features include batter and bowler historical form,
broader style-level performance, phase, venue and innings context.

Direct matchup data should be smoothed or supplemented by broader
evidence when samples are small. Do not present raw small-sample rates
as reliable predictions.

### 9.4 Recruitment Recommendation

Start with hard eligibility filters and configurable weighted
statistical scoring. Later, incorporate validated model outputs such as
expected contribution or role-adjusted performance.

Recruitment success is affected by opportunities, role, injuries, price
and team context. Historical batting statistics alone cannot establish
auction success or player market value.

### 9.5 Performance Prediction

A later model may estimate: - Runs in an innings. - Strike rate. -
Probability of reaching a run threshold. - Wicket probability. - Bowling
economy or wickets.

Use simple baselines before more complex models. Candidate algorithms
include linear/logistic regression, Random Forest and gradient boosting.

Use chronological train/validation/test splits. Prevent data leakage by
ensuring all features were available at the prediction timestamp.
Evaluate run predictions with MAE and RMSE, and probability predictions
with log loss, Brier score and calibration.

All predictions must include appropriate uncertainty and must be
labelled as estimates, not facts.

## 10. Technical Architecture

Use a modular monolith for v1.

  Layer                Technology
  -------------------- ----------------------
  Frontend             React
  Build tool           Vite
  Styling              Tailwind CSS
  Visualisation        D3.js
  Backend              Python + FastAPI
  Database             PostgreSQL
  ORM and migrations   SQLAlchemy + Alembic
  Validation           Pydantic
  Data processing      Pandas + NumPy
  ML                   Scikit-learn
  HTTP client          HTTPX
  Testing              Pytest
  Version control      Git + GitHub

The frontend must not independently calculate canonical cricket
statistics. The backend analytics layer owns calculations and exposes
them through APIs.

Avoid microservices, Kafka, Kubernetes, Redis and deep-learning
frameworks in the initial release unless a demonstrated requirement
justifies them.

## 11. Non-Functional Requirements

### Accuracy

-   All core metrics have documented definitions.
-   Statistical calculations have unit tests and independent validation
    cases.
-   Dataset coverage is visible.

### Reproducibility

-   Ingestion runs are logged.
-   Source files and checksums are retained.
-   Model versions, feature definitions and training windows are
    recorded.
-   Training and evaluation can be repeated.

### Performance

-   Common player and team queries should use indexed database access
    and precomputed aggregates where useful.
-   Expensive model training must not run inside ordinary user-facing
    requests.
-   Establish measurable response-time targets after representative data
    volumes are known.

### Security

-   Secrets are stored in environment variables.
-   No API keys or database credentials are committed to source control.
-   Validate API inputs and restrict database permissions.

### Maintainability

-   Separate ingestion, normalisation, analytics, ML, API and UI
    responsibilities.
-   Use migrations for schema changes.
-   Include automated tests and clear documentation.

## 12. Success Metrics and Acceptance Criteria

CPI v1 is successful when:

1.  IPL and Men's T20I source files can be imported repeatably.
2.  Re-running ingestion does not create duplicate matches or
    deliveries.
3.  Revised source files can be detected and safely reprocessed.
4.  Core batting and bowling statistics match independently verified
    scorecard cases.
5.  Phase-wise metrics use correct legal-ball and run denominators.
6.  Player profiles and comparisons work across defined filters.
7.  Matchup analysis displays sample sizes and limitations.
8.  Scouting results are reproducible and explainable.
9.  Player similarity returns role-relevant candidates and exposes the
    features used.
10. Data coverage and ingestion status are visible.
11. Automated tests run successfully.
12. The application can be deployed and accessed online.

## 13. Risks and Mitigations

  -----------------------------------------------------------------------
  Risk                                Mitigation
  ----------------------------------- -----------------------------------
  Incomplete source coverage          Publish coverage by competition and
                                      season

  Inconsistent player identity        Stable source IDs, aliases and
                                      manual resolution

  Missing player attributes           Store attributes separately with
                                      provenance and confidence

  Incorrect extras or dismissal logic Explicit cricket rules and
                                      edge-case tests

  Small matchup samples               Minimum thresholds, smoothing and
                                      warnings

  Revised historical records          Checksums, source revisions and
                                      idempotent reprocessing

  API limits or pricing changes       Provider abstraction and no
                                      critical dependency on paid
                                      endpoints

  ML leakage                          Timestamp-aware features and
                                      chronological splits

  Misleading rankings                 Explain weights, eligibility and
                                      sample sizes

  Over-engineering                    Modular monolith and staged roadmap
  -----------------------------------------------------------------------

## 14. Delivery Roadmap

### Phase 1: Dataset Understanding

-   Download and inspect actual Cricsheet JSON files.
-   Confirm IPL and Men's T20I coverage.
-   Document fields, identifiers, extras and dismissal structures.
-   Build a sample parser and validation report.

### Phase 2: Data Foundation

-   Finalise PostgreSQL schema.
-   Build provider adapters and ingestion registry.
-   Implement idempotent imports and revision handling.
-   Add automated tests.

### Phase 3: Core Analytics

-   Batting and bowling calculations.
-   Player profiles.
-   Phase-wise statistics.
-   Independent validation.

### Phase 4: Advanced Analytics

-   Matchups.
-   Player comparisons.
-   Pace/spin analysis where metadata supports it.
-   D3.js visualisations.

### Phase 5: Scouting and ML

-   Eligibility filters.
-   Role-specific statistical scoring.
-   Player similarity.
-   Explainable shortlist.
-   Model evaluation and versioning.

### Phase 6: Team Intelligence and Deployment

-   Team and venue analytics.
-   Reports and exports.
-   Performance optimisation.
-   Deployment and documentation.

## 15. Product Principles

1.  Data accuracy is more important than feature count.
2.  Every metric must have a defined formula and denominator.
3.  Every recommendation must have inspectable evidence.
4.  Sample size and data coverage must be visible.
5.  Predictions must be separated from historical facts.
6.  ML must solve a real problem and beat a sensible baseline.
7.  No unsupported API capability or player attribute may be assumed.
8.  Prefer free and open-source technologies where practical.
9.  Build and validate one phase at a time.
10. Treat CPI as a serious cricket intelligence product, not a
    decorative dashboard.

------------------------------------------------------------------------

**End of PRD**
