"""CPI win-probability engine v2.

Batting-team oriented, format-specific models trained on CPI's Cricsheet
ball-by-ball history with strictly chronological, match-level partitions.

Modules
-------
``constants``  format groups, partition fractions, model version
``data``       PostgreSQL loaders (reuses CPI's ingested tables; no re-ingestion)
``context``    pre-match context: chronological Elo, venue par, era par
``features``   state reconstruction, terminal rules, resource table, feature matrices
``modeling``   model factories, calibrators and metrics
``engine``     runtime predictor used by the API, simulator and precompute job
"""
