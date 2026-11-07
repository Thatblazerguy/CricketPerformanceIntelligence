# Performance audit

## Loading and query changes

| View/action | Before | After implementation |
|---|---|---|
| Players initial render | Automatically requested `/players/performance`, including stat aggregation across the current filter cohort (default page, but analytics aggregation was not limited to the current player rows). | **0 API requests / 0 player rows** until Search. Search requests only one page (`page_size` capped at 100) of basic player/bio data. No profile statistics are included. |
| Players search | Performance endpoint aggregated batting and bowling statistics before paging. | 1 list endpoint request; 2 page/count SQL statements + one batched attribute lookup and role/filter subqueries. The previous per-player attribute lookup loop is removed. |
| Matches initial render | Automatically fetched a match page on mount. | **0 API requests / 0 match summaries** until Search. |
| Matches search | One summary query plus up to four `db.get()` calls per match row (N+1 pattern). | One count query + one page query + up to three batched lookup queries for teams, venues and competitions. `page_size` is capped at 100. |
| Match detail | The list route returned summaries only; no lazy detail view existed. | A separate `/matches/{id}/details` endpoint and page fetch innings/deliveries only after opening a match. It returns one match, rather than match histories. |

## Timing and database measurements

The app was later run against local PostgreSQL with managed escalation. Single-run local `TestClient` request times after the changes were: KL Rahul ODI player search **174.5 ms**; exact 2023 World Cup match list returning 39 summaries **73.6 ms**; one match detail returning 2 innings/569 deliveries, extras and wickets **65.0 ms**. These are single measurements, not stable benchmark results. Before-change timings were not recorded, so no before/after latency delta is claimed. The query counts above remain structural counts from route code, not measured PostgreSQL statement telemetry or `EXPLAIN ANALYZE`.

Indexes already present cover match format/date/season and delivery innings/batter/bowler. Added migration indexes cover match tournament/date, venue/date and both team/date directions. Apply Alembic migrations before using the reference alias tables and indexes.

## Remaining bottlenecks

- Player profile analytics still aggregate over delivery data when the analytics endpoint is requested. A durable per-format/per-season aggregate table or materialized view remains a follow-up; it requires a verified migration/backfill and refresh strategy.
- Player-profile initial analytics is not yet split into a lightweight career summary and independently requested advanced tabs.
- Filter combinations and reference CSV mapping have not been exercised against PostgreSQL in this run.
- The match detail endpoint loads all deliveries for one match. This is intentionally scoped to one match and is expected to be manageable, but has not been timed against production data.
