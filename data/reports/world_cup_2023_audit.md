# 2023 ICC Cricket World Cup Match Reconciliation

Source: local Cricsheet archive under `gamedata/`. The official matches page was opened, but it returned an anti-bot verification page, so this report uses the supplied archive as the source of truth.

- ODI files matching the exact competition name `ICC Cricket World Cup` and 2023 match dates: **39 of 48 expected tournament matches**.
- The 48-match tournament size is confirmed by the [ICC's official 2023 tournament announcement](https://www.icc-cricket.com/news/prize-money-announced-for-icc-mens-cricket-world-cup-2023).
- The nine expected source IDs absent from the supplied Cricsheet archive are: `1384394`, `1384400`, `1384404`, `1384407`, `1384413`, `1384421`, `1384425`, `1384430`, `1384433`. No matching JSON files exist locally, so they were not ingested. The official current downloads page identifies its all-matches collection as 23,241 matches, the same collection count as the local archive; no per-match JSON downloads for those IDs were exposed by the official page during this audit.
- The supplied archive migration report lists 23,241 of 23,241 archive match IDs imported, with zero archive IDs missing from the database at the last successful database reconciliation. Thus all listed World Cup source IDs were included in that reconciliation.
- The collection includes separate 2023 events such as the Cricket World Cup Qualifier and Qualifier Play-off; those are excluded from this main-tournament list.
- CPI display/API discovery could not be exercised in the current sandbox because PostgreSQL connections are denied. Competition text `ICC Cricket World Cup`, ODI format and date range 2023-10-01 through 2023-11-30 are supported match list filters.

| Source ID | Date | Season | Teams | Venue |
|---|---|---|---|---|
| 1384392 | 2023-10-05 | 2023/24 | England, New Zealand | Narendra Modi Stadium, Ahmedabad |
| 1384393 | 2023-10-06 | 2023/24 | Pakistan, Netherlands | Rajiv Gandhi International Stadium, Uppal |
| 1384395 | 2023-10-07 | 2023/24 | South Africa, Sri Lanka | Arun Jaitley Stadium |
| 1384396 | 2023-10-08 | 2023/24 | Australia, India | MA Chidambaram Stadium |
| 1384397 | 2023-10-09 | 2023/24 | New Zealand, Netherlands | Rajiv Gandhi International Stadium, Uppal |
| 1384398 | 2023-10-10 | 2023/24 | England, Bangladesh | Himachal Pradesh Cricket Association Stadium, Dharamsala |
| 1384399 | 2023-10-10 | 2023/24 | Sri Lanka, Pakistan | Rajiv Gandhi International Stadium, Uppal |
| 1384401 | 2023-10-12 | 2023/24 | South Africa, Australia | Bharat Ratna Shri Atal Bihari Vajpayee Ekana Cricket Stadium, Lucknow |
| 1384402 | 2023-10-13 | 2023/24 | Bangladesh, New Zealand | MA Chidambaram Stadium |
| 1384403 | 2023-10-14 | 2023/24 | Pakistan, India | Narendra Modi Stadium, Ahmedabad |
| 1384405 | 2023-10-16 | 2023/24 | Sri Lanka, Australia | Bharat Ratna Shri Atal Bihari Vajpayee Ekana Cricket Stadium, Lucknow |
| 1384406 | 2023-10-17 | 2023/24 | Netherlands, South Africa | Himachal Pradesh Cricket Association Stadium, Dharamsala |
| 1384408 | 2023-10-19 | 2023/24 | Bangladesh, India | Maharashtra Cricket Association Stadium, Pune |
| 1384409 | 2023-10-20 | 2023/24 | Australia, Pakistan | M Chinnaswamy Stadium, Bengaluru |
| 1384410 | 2023-10-21 | 2023/24 | Netherlands, Sri Lanka | Bharat Ratna Shri Atal Bihari Vajpayee Ekana Cricket Stadium, Lucknow |
| 1384411 | 2023-10-21 | 2023/24 | South Africa, England | Wankhede Stadium, Mumbai |
| 1384412 | 2023-10-22 | 2023/24 | New Zealand, India | Himachal Pradesh Cricket Association Stadium, Dharamsala |
| 1384414 | 2023-10-24 | 2023/24 | South Africa, Bangladesh | Wankhede Stadium, Mumbai |
| 1384415 | 2023-10-25 | 2023/24 | Australia, Netherlands | Arun Jaitley Stadium |
| 1384416 | 2023-10-26 | 2023/24 | England, Sri Lanka | M Chinnaswamy Stadium, Bengaluru |
| 1384417 | 2023-10-27 | 2023/24 | Pakistan, South Africa | MA Chidambaram Stadium |
| 1384418 | 2023-10-28 | 2023/24 | Australia, New Zealand | Himachal Pradesh Cricket Association Stadium, Dharamsala |
| 1384419 | 2023-10-28 | 2023/24 | Netherlands, Bangladesh | Eden Gardens, Kolkata |
| 1384420 | 2023-10-29 | 2023/24 | India, England | Bharat Ratna Shri Atal Bihari Vajpayee Ekana Cricket Stadium, Lucknow |
| 1384422 | 2023-10-31 | 2023/24 | Bangladesh, Pakistan | Eden Gardens, Kolkata |
| 1384423 | 2023-11-01 | 2023/24 | South Africa, New Zealand | Maharashtra Cricket Association Stadium, Pune |
| 1384424 | 2023-11-02 | 2023/24 | India, Sri Lanka | Wankhede Stadium, Mumbai |
| 1384426 | 2023-11-04 | 2023/24 | New Zealand, Pakistan | M Chinnaswamy Stadium, Bengaluru |
| 1384427 | 2023-11-04 | 2023/24 | Australia, England | Narendra Modi Stadium, Ahmedabad |
| 1384428 | 2023-11-05 | 2023/24 | India, South Africa | Eden Gardens, Kolkata |
| 1384429 | 2023-11-06 | 2023/24 | Sri Lanka, Bangladesh | Arun Jaitley Stadium |
| 1384431 | 2023-11-08 | 2023/24 | England, Netherlands | Maharashtra Cricket Association Stadium, Pune |
| 1384432 | 2023-11-09 | 2023/24 | Sri Lanka, New Zealand | M Chinnaswamy Stadium, Bengaluru |
| 1384434 | 2023-11-11 | 2023/24 | Bangladesh, Australia | Maharashtra Cricket Association Stadium, Pune |
| 1384435 | 2023-11-11 | 2023/24 | England, Pakistan | Eden Gardens, Kolkata |
| 1384436 | 2023-11-12 | 2023/24 | India, Netherlands | M Chinnaswamy Stadium, Bengaluru |
| 1384437 | 2023-11-15 | 2023/24 | India, New Zealand | Wankhede Stadium, Mumbai |
| 1384438 | 2023-11-16 | 2023/24 | South Africa, Australia | Eden Gardens, Kolkata |
| 1384439 | 2023-11-19 | 2023/24 | India, Australia | Narendra Modi Stadium, Ahmedabad |
