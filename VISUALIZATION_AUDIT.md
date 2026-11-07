# CPI Visualization Audit

Updated: 2026-11-08

## Data-backed visualizations added or retained

| Area | Visualization | Data source and filter behavior |
| --- | --- | --- |
| Global dashboard | Match format share, dated matches by year, available-year match bars | `/dataset/coverage` aggregates stored `matches`; format and year counts are kept separate. |
| Player profile | Runs, wickets, batting strike rate and bowling economy by format; year appearances/runs/strike rate; recent batting runs by match; phase runs/strike rate/dot and boundary rates; phase bowling wickets/economy/strike rate/dot and boundary rates; pace/spin batting and bowling splits; opponent and venue runs/strike rates | Existing `/players/{id}/analytics` aggregates. Charts redraw with the profile's format, applied year range, venue, opponent and other server filters. Missing metrics are omitted, not plotted as zero. T20 and T20I stay separate. |
| Player comparison | Multi-player radar comparison for batting average, strike rate, boundary percentage, wickets, economy and bowling average | Existing batting and bowling APIs; selected format is explicit. Only axes populated for every selected player are compared. Metrics are normalized within the selected players and lower economy/average scores are treated as better. |
| Teams | Outcome counts, batting-first/chasing/home-away-neutral rates, and win rates by ground country, ground and opponent | Existing filtered team record endpoint; current gender, format, period/date, country and opposition filters apply. Samples are included in chart labels. |
| Grounds | Scoring, wickets lost by innings, phase scoring and bowling wickets/economy by phase/style, pace-spin wickets/economy, toss-decision outcome, chase rate, recent-vs-period first/second-innings averages, yearly score trend and stored-format comparison | Existing selected-ground analytics and format-aware phase rules; only available measurements are drawn. |
| Scouting | Top role-fit score plus a selectable actual performance metric comparison among the current role- and format-filtered candidates | Existing scouting response metrics and eligibility filters. Missing values are omitted. |
| Auction scenario | Highest predicted closes, demand scores, remaining purse, historical records by year, demand-vs-close scatter, individual-value-vs-close scatter, and confidence ranges for highest-demand players | Existing selected-scenario prediction output and auction-history summary. Scatter point size/color and tooltip details expose feasible bidder count, competition and scarcity. |
| Auction ML | Chronological holdout MAE/RMSE, median-baseline MAE when present, training/validation sample sizes, and R² when present | Persisted evaluation JSON from the trained price model only. |

Reusable SVG chart components live in `frontend/src/components/charts.jsx`. No chart dependency was added. Charts include labels, hover titles/tooltips, responsive sizing, and empty-data states.

## Deeper chart pass (2026-11-08)

- Expanded player charts with format-specific batting/bowling totals, batting pace/spin efficiency, phase rate and pressure indicators, and top opponent/venue splits.
- Expanded team charts with win-rate comparisons by country, ground and opponent from the filtered team response.
- Expanded ground views with innings wicket loss, phase/style bowling measures, toss-decision outcomes, recent second-innings scoring and yearly first-innings scoring trends. The mini-bar renderer now filters missing observations rather than drawing them as zero.
- Added a selectable actual-statistic comparison to Scouting and demand/valuation/price-range charts to Auction Scenario. These display model output, not historical actual-vs-predicted training residuals.
- Production build verified with Vite. No additional dependencies or new backend aggregate queries were introduced.

## Data dependencies not currently available

- **Geographic map:** Venue records have canonical name, city and country but no verified latitude/longitude. A map would require a sourced coordinate dataset; none is attached to the venue schema, so no coordinates are inferred.
- **Actual-vs-predicted scatter and residual distribution:** The auction trainer persists aggregate holdout metrics but does not persist row-level predictions/residuals. These plots need a versioned holdout prediction table or equivalent stored evaluation rows.
- **Feature importance and correlation heatmap:** The stored model artifact contains the fitted pipeline, but the model-run API does not publish feature names/importance or a correlation dataset. These are not represented as guessed charts.
- **Dismissal distribution and batting-style distribution:** The player analytics response currently does not expose dismissal-type or style-grouped delivery aggregates for player profiles.
- **Bowling match-by-match workload trends:** Player recent-match records currently expose batting totals; bowling fields in that response are placeholders, so only aggregated bowling phases and pace/spin outputs are graphed.
- **Top performers and high-impact global performances:** The dashboard coverage API has counts and date coverage, but no bounded top-performer/high-impact aggregate endpoint. Raw delivery scans on dashboard load were avoided.
- **Live bid-intensity timeline:** Scenario predictions are estimates and the interactive auction event API is not currently integrated into a plotted stream; estimated demand is shown separately from actual session bids.

These are documented as data/API dependencies, not filled with estimates or mock values.
