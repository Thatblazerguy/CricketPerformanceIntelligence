"""Hybrid cricket data engine.

Two independent layers share one canonical match identity:

* Ball-by-ball layer: the existing ``matches`` / ``match_innings`` / ``deliveries``
  tables. All advanced analytics keep reading only these.
* Scorecard layer: ``scorecard_innings`` / ``scorecard_batting`` / ``scorecard_bowling``
  for matches without delivery data. Never read by delivery-level analytics.

``canonical_matches`` gives each real-world match one CPI identity and a coverage
classification; ``match_source_refs`` keeps every source's own reference.
"""
