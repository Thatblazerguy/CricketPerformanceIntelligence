"""Catalogue of every source investigated for CPI, with what it really offers.

Only sources marked ``integrated`` are ever contacted by CPI. Investigation
notes record what was checked on 2026-11-15; re-check terms before integrating.
"""
from __future__ import annotations

from typing import Dict, List

from app.hybrid.sources.base import SourceInfo
from app.hybrid.sources.cricsheet_inventory import CricsheetInventoryAdapter
from app.hybrid.sources.scorecard_file import ScorecardFileAdapter

INVESTIGATED: List[SourceInfo] = [
    CricsheetInventoryAdapter.info,
    ScorecardFileAdapter.info,
    SourceInfo(
        key="espncricinfo", name="ESPNcricinfo (scorecards, Statsguru)", data_level="scorecard",
        access="licence_required", licence="Proprietary (ESPN). No public data API or bulk download.",
        url="https://www.espncricinfo.com/",
        coverage="Scorecards for virtually all international cricket since 1877 and much domestic cricket "
                 "(Ranji, Duleep, Vijay Hazare, Syed Mushtaq Ali). Ball-by-ball text commentary only for recent matches.",
        notes=["Automated requests are refused (HTTP 403 on 2026-11-15); terms of use prohibit automated collection.",
               "Visible on the website does not mean downloadable: not scraped.",
               "Integrate only under a written data licence, via the scorecard import adapter.",
               "Cricsheet people.csv already maps Cricsheet player ids to Cricinfo ids, so licensed Cricinfo "
               "scorecards would resolve players without name guessing."],
    ),
    SourceInfo(
        key="howstat", name="Howstat", data_level="scorecard", access="restricted",
        licence="All rights reserved; no API or download offered.", url="http://www.howstat.com/cricket/",
        coverage="Test (from 1877) and ODI (from 1971) scorecards and player records. No ball-by-ball. "
                 "Little or no Indian domestic cricket.",
        notes=["Automated requests are refused (HTTP 403 on 2026-11-15).",
               "Requires the owner's written permission before any use."],
    ),
    SourceInfo(
        key="bcci", name="BCCI match archives (bcci.tv)", data_level="scorecard", access="restricted",
        licence="BCCI website terms; no published data licence or bulk export.", url="https://www.bcci.tv/",
        coverage="Recent BCCI domestic seasons (Ranji, Duleep, Vijay Hazare, Syed Mushtaq Ali), some with live "
                 "ball-by-ball. Historical depth before roughly 2018 is thin on the site.",
        notes=["The richest source for Indian domestic cricket, but no sanctioned bulk access.",
               "Approach BCCI for a data agreement; import granted data with the scorecard adapter.",
               "Cricsheet people.csv carries BCCI player keys for identity resolution."],
    ),
    SourceInfo(
        key="cricketarchive", name="CricketArchive", data_level="scorecard", access="licence_required",
        licence="Paid subscription; commercial reuse needs a separate licence.", url="https://cricketarchive.com/",
        coverage="The deepest historical scorecard archive, including first-class, List A and Indian domestic "
                 "matches back to the 19th century.",
        notes=["Best candidate to close pre-2001 and domestic gaps if a data licence is obtained.",
               "people.csv already maps Cricsheet ids to CricketArchive ids."],
    ),
    SourceInfo(
        key="cricketdatabase", name="Cricket Database API (already configured in CPI)", data_level="metadata",
        access="licence_required", licence="API key (configured server-side).",
        url="https://api.cricketdatabase.com/v1",
        coverage="Used by CPI today only for player lookup and basic career stats for auction uploads.",
        notes=["Requests without a key return HTTP 401. Whether it serves match scorecards was not verified, "
               "and the configured key was not used for investigation.",
               "Its career totals must never stand in for CPI-derived totals."],
    ),
]


def catalog() -> List[Dict]:
    return [s.as_dict() for s in INVESTIGATED]
