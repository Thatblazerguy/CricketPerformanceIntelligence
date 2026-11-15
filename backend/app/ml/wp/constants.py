"""Shared constants for the v2 win-probability engine."""
from __future__ import annotations

MODEL_VERSION_PREFIX = "cpi-wp-v2"

# Evaluation/model groups. Formats with different match dynamics are never pooled,
# except T20 and T20I (identical laws; ``international`` is a feature).
GROUPS = {
    "T20": ("T20", "T20I"),
    "ODI": ("ODI",),
    "ODM": ("ODM",),
    "Test": ("Test",),
    "MDM": ("MDM",),
}
GROUP_OF_FORMAT = {fmt: group for group, formats in GROUPS.items() for fmt in formats}
LIMITED_GROUPS = ("T20", "ODI", "ODM")
MULTIDAY_GROUPS = ("Test", "MDM")
FULL_BALLS = {"T20": 120, "ODI": 300, "ODM": 300}

# Elo pools: teams play across these source formats with comparable strength.
ELO_POOL = {"T20": "t20", "T20I": "t20", "ODI": "one_day", "ODM": "one_day", "Test": "multi_day", "MDM": "multi_day"}
# Days after the start date before a result may update ratings (multi-day matches
# are still in progress for several days; same-day limited-overs results are not
# known before another match on that date starts).
ELO_RESULT_LAG_DAYS = {"T20": 1, "T20I": 1, "ODI": 1, "ODM": 1, "Test": 5, "MDM": 4}
ELO_K = 20.0
ELO_START = 1500.0

# Chronological, match-level partitions (fractions of labelled matches by date).
PARTITIONS = (("train", 0.60), ("validation", 0.15), ("calibration", 0.10), ("test", 0.15))

# Limited overs: Test/MDM classes are ordered (batting win, bowling win, draw).
MULTI_OUTCOMES = ("batting_win", "bowling_win", "draw")

# Shrinkage (in pseudo-innings) of venue par towards era par.
VENUE_SHRINK = 8.0
ERA_WINDOW_DAYS = 730
ERA_MIN_INNINGS = 20

# Minimum training states in a state cell before a prediction is called well-supported.
MIN_SUPPORT = 50
