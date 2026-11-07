# IPL auction data sources

The source files in this directory are preserved as supplied/converted reference data. CPI records source repository, import time, row status and source name for imported observations. The datasets are not treated as verified official records; review source provenance and terms before redistribution.

## outside-edge/ipl_auction

- Repository: https://github.com/outside-edge/ipl_auction
- Files: `outside_edge_auction_all_years.parquet` (original) and `outside_edge_auction_all_years.csv` (runtime import copy); `outside_edge_player_registry.csv` (ID/name/pipe-delimited alias lookup).
- CSV schema: `year, player_id, player_name, team, base_price_lakh, final_price_lakh, role, nationality, status, acquisition_type, source`.
- Snapshot inspected: 2,628 auction records, 2008–2026; 1,434 SOLD, 1,123 RETAINED and 71 UNSOLD. The source repository documents 2024 as unavailable. Blank prices remain null. CPI does not treat retained or unsold values as sale prices.
- CPI converts no prices from this source because its price columns are already INR lakh. Player registry IDs and aliases assist resolution; CPI links a history record to a CPI player only when source/CPI names yield one unambiguous match.

## rixabhh/IPL-Auction-Analysis

- Repository: https://github.com/rixabhh/IPL-Auction-Analysis
- File: `rixabhh_cleaned_ipl_auction_2013_2022.csv` (`Cleaned_IPL_Auction_Data.csv` from the repository).
- Schema: `Player, Role, Amount, Team, Year, Player_Origin, Amount_Cr, Count, Repeated`.
- Snapshot inspected: 970 rows for 2013–2022. `Amount` is INR and `Amount_Cr` is INR crore; CPI prefers `Amount_Cr` and converts crore to lakh (×100), falling back to INR / 100,000. The source provides paid-price records, so missing status defaults to SOLD for this uploaded file; users should preserve explicit status columns in custom uploads whenever available.

## Training inclusion and current import

- Both sources are imported with per-source provenance. A stable transaction key prevents repeat imports from creating duplicate records within a source.
- The price model includes only positive-price SOLD records whose acquisition type is `auction`; it excludes retained/unsold rows and excludes franchise name from predictive features.
- Cross-source repeated transactions are deduplicated using linked CPI player ID when available (otherwise normalized source name), auction year, normalized franchise and acquisition type. Duplicates remain in the source database for audit.
- Imported snapshot in the local CPI PostgreSQL database: 3,597 total rows (2,627 outside-edge accepted, 970 Rixabhh accepted); outside-edge had one rejected row. Identity match status is preserved: outside-edge 2,130 matched / 353 unresolved / 144 ambiguous; Rixabhh 645 matched / 307 unresolved / 18 ambiguous.
- Training source rows: 2,403 sold auction prices; after cross-source deduplication, 1,562 transactions were used. Chronological validation began in 2021 with 456 rows; MAE was 197.306 INR lakh compared with 222.094 INR lakh for the training-median baseline. This is a limited historical price-regression baseline, not a prediction of future performance or auction destination.
