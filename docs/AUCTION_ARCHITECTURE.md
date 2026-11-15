# CPI Auction Intelligence Architecture

## Repository audit

- CPI is a React/Vite frontend and FastAPI/SQLAlchemy backend using one PostgreSQL database.
- Canonical players, aliases, verified attributes, teams, tournaments, matches, innings, and ball-by-ball deliveries already exist in `backend/app/models/models.py`.
- Scouting and role-aware performance aggregation are implemented, but there was no auction schema, auction history, upload centre, squad import, or simulation engine before this module.
- Current dependencies include Pandas, NumPy and Scikit-learn. OR-Tools, CatBoost, XGBoost, Redis, spreadsheet parsers and authentication are not configured. No historical auction dataset was found during this pass.
- The auction module references `players.id`; it does not create another player identity or performance database.

## Implemented foundation

- Versioned scenarios and rules snapshots.
- Scenario franchises, player pool rows, retentions and import reports.
- Session, bid, purchase and ordered event-log persistence.
- Exact canonical-name/alias identity preview; unresolved, ambiguous, and duplicate rows are reported before import.
- Team purse and role-coverage summaries based on scenario records.
- Validated interactive session operations for calling a player, placing bids, closing as sold/unsold, and reading the event history.
- Frontend scenario creation and the two-file auction intake flow (retention list and player pool); franchise records are derived from the retention file instead of requiring manual team or purse entry.
- Decimal purse/bid storage, scenario/player uniqueness, session event sequence uniqueness, and per-session purchase uniqueness.

## Historical data upload and price model

- The Auction Intelligence page supports previewing and importing historical auction CSVs, and importing the two bundled public repository datasets. CSV rows are parsed with a 10 MB / 10,000 row cap, source names and source URLs are retained, duplicate transaction keys are idempotent, and unmatched/ambiguous CPI identities remain explicitly marked instead of being forcibly merged.
- Imported history is stored in `auction_history_records`; uploads and their accepted/duplicate/rejected counts are logged in `auction_history_imports`. A reference player registry is used as an alias aid. Existing canonical CPI player IDs are linked only for unique name/alias matches.
- The outside-edge source provides 2,628 rows over 2008–2026, including SOLD, RETAINED and UNSOLD outcomes; its repository notes that the 2024 auction is absent. The Rixabhh cleaned source has 970 paid-price rows covering 2013–2022. See `data/auction/SOURCES.md` for field and unit provenance.
- Import converts price fields to INR lakh, while keeping retained and unsold rows distinct. Price regression trains only on positive SOLD auction transactions. Cross-source duplicates are collapsed by canonical player (or normalized source name), year, franchise and acquisition type; retained/unsold rows are excluded. Same-year auction outcomes do not enter the prior-price features for that year.
- Scikit-learn model evaluation uses a chronological year holdout and reports MAE, RMSE and R² against a median-price baseline. This is an experimental price baseline, not a future-performance or destination prediction. The model is not surfaced as an estimate until a separate prediction UX is implemented and validated.
- Current PostgreSQL import: 3,597 source rows, 2,403 positive sold-auction source rows, 1,562 deduplicated training transactions and 841 cross-source duplicates removed. The trained model held out 456 rows from 2021, 2022, 2023 and 2026; MAE was 197.306 lakh vs 222.094 lakh for the median baseline (R² 0.0606). Coverage has gaps, including 2024.
- Historical source import remains available through the bundled-data action; within a scenario, retention-list CSV and player-pool CSV upload/preview/import are supported. Franchise teams are created from retention rows, and absent retention prices stay NULL. Player resolution uses CPI aliases joined through Cricsheet identifiers in `names.csv`; the explicitly supplied Spencer Johnson → SH Johnson correction is recorded in `data/reference/cricsheet/cpi_alias_overrides.csv`. Ambiguous initials/surname matches are rejected for review. XLSX parsing, manual identity resolution, competition-relative feature materialisation, destination/sale probability models and background imports remain outstanding.
- **Run Scenario** compares retained player roles with default squad targets (6 batters, 6 bowlers, 4 all-rounders and 2 wicketkeepers, overridable in scenario rules), lists each franchise's remaining role gaps, and recommends available pool players that address those gaps. It reports franchise-specific estimated prices from the trained historical sale-price model, along with model holdout MAE and confidence based on historical franchise sample counts. These are bids estimates, not team budgets or guaranteed auction outcomes.
- The price-model feature set includes normalized franchise identity in addition to year, base price, player role/nationality and strictly earlier sale history. Bid predictions are batched for the scenario to keep response latency low.

## Auction invariants

- Rules are scenario-scoped and versioned; a session captures the rules version in its `PLAYER_CALLED` event.
- Bid amounts use PostgreSQL `NUMERIC` and Python `Decimal` validation.
- Bid endpoints validate active session/player, scenario membership, minimum bid increment, remaining purse and squad maximum while locking relevant session/team rows.
- Closing a player writes a sold/unsold event; a sold player gets one purchase record and is removed from availability.
- Event rows are append-only through the API. Corrections should use compensating events.

## Upgrade (November 2026): integrated on the existing module

The original scenario workbench, upload adapters, rules parsing, predicted XI, manual sessions and the v1 price model are unchanged in behaviour and remain the default view. New capability is layered on the same tables, router and services.

### Data foundation
- **Sources added** (stored under `data/auction/sources/` with revision ids): Wikipedia "List of <season> IPL personnel changes" (2024–2026 sold players with set, lot, base price, RTM, previous team; retention salaries; 2024 purse remaining) and the official 2022/2023 auction lists (full pools incl. unsold, reserve prices, sets, DOB/age). Parsed deterministically by `app/auction/sources.py`; inserted into the existing `auction_history_records` with new nullable provenance columns. Original imported rows are never modified (verified by checksum after a full pipeline run).
- **`auction_seasons`**: per-season rules (date, type, purse, squad/overseas limits, min base, RTM, increments) each with a provenance level (`sourced` / `reported` / unknown). Edit `data/auction/seasons.json`.
- **`auction_lots`**: one reconciled outcome per player-season, merging sources; `corroborated` / `single_source` / `conflict` verification. Conflicts are excluded from training; whole-crore roundings are resolved to the finer value and noted. Lot ids are stable across rebuilds.
- **Identity**: exact aliases → evidence-filtered candidates (given-name contradiction, one-edit surname variants, consistency with the record's own IPL caps, IPL/T20 activity around the auction date). Improved identities are applied in reconciliation only.
- **`auction_franchise_seasons`**: pre-auction purse — sourced where published, otherwise season purse − retention salaries only where the retention list is complete (validated: matches the sourced 2024 figure exactly for 7/10 franchises; the other 3 made post-list trades).
- Coverage: `GET /auction/coverage`. 2008–2026, 3,945 lots; unsold recorded only for 2021 (partial), 2022, 2023; base prices for 2011 and 2021–2026; 2 of 182 sales for 2025 absent from the cited table.

### Models (`app/ml/auction_price.py`)
- v1 (`train_price_model`, `predict_team_bids`) kept as a baseline. v2: point-in-time features from `scouting_*_innings` (`app/auction/features.py`, `start_date < auction date`, IPL-equivalent competition factors from bridge players, recency weighting, shrinkage) → quantile gradient boosting on log(price / season purse), CQR-calibrated 80% range; logistic sale-probability ranker prior-shifted to open slots ÷ pool size.
- `POST /auction/models/train-price` now trains v1 and v2. Rolling-origin backtest: `GET/POST /auction/backtest`.
- Latest backtest (947 sales, 2018–2026): MAE ₹174.6 L vs 180.1 (performance-only), 209.3 (role median); 182.7 vs 207.8 (base price) on rows with a known base; 80% range coverage 85%. CPI does not win every season (2021, 2023). Sale probability beats the naive baseline in 2023 but not 2022 → labelled experimental.

### Scenario analysis (`run_scenario`, same response shape)
- Prices from v2; squad state, best XI (MILP), functional needs and marginal value from `app/auction/market.py` / `optimizer.py`; existing `demand_score`, `team_willingness_lakh`, `competition_adjusted_price` reused; expected close capped at the model p90.
- **Replaced flaw:** the fixed 6/6/4/2 role template — targets now come from IPL squad usage (median players per role per team-season, last three seasons); the template is only a fallback and scenario `role_targets` still override.
- Missing uploaded retention prices are filled from sourced retention records for that season, otherwise the purse is labelled approximate.

### Auction room (existing session tables)
- `POST /auction/rooms`, `POST /auction/rooms/{id}/action`: an `AuctionSession` with `simulation_mode="AI_ROOM"` holds engine state; every call/bid/sale is an ordinary `AuctionEvent` / `AuctionBid` / `AuctionPurchase` (crore). User bids pass `validate_bid`. Manual session endpoints refuse AI rooms; simulated purchases are excluded from real squads, rules checks and predicted XI. Replays of past auctions use a `REPLAY` scenario with one team per franchise.

### Other analytics (same `/auction` router)
`/contexts`, `/market`, `/players`, `/franchises`, `/optimize` (MILP purse allocation + Monte Carlo), `/purchase-scenarios/compare`, `/history`, `/history/records`, `/seasons`, `/rebuild`. Replays retrain on seasons before the auction only.

### Known limitations
No bid-level history exists, so simulated bidding is never presented as a reconstruction. Ages are known only for 2022–2023 entrants. Unsold pools are missing for 2024–2026, so those replays cannot estimate sale probability and squads may end below minimum.

## Staged roadmap

1. **Foundation and data centre (started):** schemas, scenario API/UI, identity preview, pool JSON import, audit reports.
2. **Scenario completeness:** CSV/XLSX/JSON import adapters, retention and current-squad import, rule editor/version management, manual identity resolution, import history.
3. **Team intelligence:** competition-aware feature store, requirements and gap scoring, role/phase coverage, spending plans.
4. **Predictions:** real historical auction ingestion, sale-probability and price models, role-specific temporal evaluation, transparent team fit, calibrated destination model.
5. **Optimiser:** deterministic constrained XI/squad solver after solver dependency and competition rules are selected.
6. **Simulation:** multi-franchise agents, alternative-target opportunity cost, automated mode, resume/replay and concurrency tests.
7. **Reports and hardening:** role/auction-type evaluation, scenario comparisons, auth/ownership, load tests and end-to-end validation.

Do not mark stages 2–7 complete until their real input data and validations are available.
