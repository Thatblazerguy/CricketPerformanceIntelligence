"""Format classes used for aggregation. Each canonical match has exactly one, so
international and domestic records can never be double-counted."""
from __future__ import annotations

from typing import Optional

TEST, ODI, T20I = "TEST", "ODI", "T20I"
FIRST_CLASS, LIST_A, T20_DOMESTIC = "FIRST_CLASS", "LIST_A", "T20_DOMESTIC"
# Cricsheet's MDM / ODM are "other multi-day / one-day matches". Cricsheet does not
# say whether each one holds first-class / List A status, so they are kept apart
# rather than being relabelled as such.
MULTI_DAY, ONE_DAY = "MULTI_DAY", "ONE_DAY"

INTERNATIONAL = (TEST, ODI, T20I)
LIMITED_OVERS = (ODI, T20I, LIST_A, T20_DOMESTIC, ONE_DAY)
ALL_CLASSES = (TEST, ODI, T20I, FIRST_CLASS, MULTI_DAY, LIST_A, ONE_DAY, T20_DOMESTIC)

LABELS = {
    TEST: "Test", ODI: "ODI", T20I: "T20I",
    FIRST_CLASS: "First-class", LIST_A: "List A", T20_DOMESTIC: "Domestic / franchise T20",
    MULTI_DAY: "Other multi-day (Cricsheet MDM)", ONE_DAY: "Other one-day (Cricsheet ODM)",
}

_CRICSHEET = {"Test": TEST, "ODI": ODI, "T20I": T20I, "T20": T20_DOMESTIC, "MDM": MULTI_DAY, "ODM": ONE_DAY}

# Classes a scorecard source may describe the same match with.
_COMPATIBLE = {
    FIRST_CLASS: {FIRST_CLASS, MULTI_DAY}, MULTI_DAY: {FIRST_CLASS, MULTI_DAY},
    LIST_A: {LIST_A, ONE_DAY}, ONE_DAY: {LIST_A, ONE_DAY},
}


def from_cricsheet(match_format: str) -> str:
    return _CRICSHEET.get(match_format, match_format.upper())


def normalise(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    v = value.strip().upper().replace("-", "_").replace(" ", "_")
    aliases = {"FC": FIRST_CLASS, "FIRSTCLASS": FIRST_CLASS, "LISTA": LIST_A, "T20": T20_DOMESTIC,
               "IT20": T20I, "MDM": MULTI_DAY, "ODM": ONE_DAY}
    v = aliases.get(v, v)
    return v if v in ALL_CLASSES else None


def compatible(a: str, b: str) -> bool:
    return a == b or b in _COMPATIBLE.get(a, set())


def is_limited_overs(format_class: str) -> bool:
    return format_class in LIMITED_OVERS
