"""Cross-source match identity.

Matches are never merged on team names and date alone. Hard constraints
(gender, compatible format, same two teams, start date within tolerance) narrow
the candidates; venue, competition, result and innings totals then have to
support the choice. Same-day double-headers (common in associate T20Is and in
men's/women's double-headers that share team ids) are only merged when innings
totals or results tell them apart; otherwise the record is held as ambiguous.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, Iterable, List, Optional, Sequence

from app.hybrid.formats import compatible, is_limited_overs

MATCHED, NEW, AMBIGUOUS = "matched", "new", "ambiguous"
ACCEPT_SCORE = 3.0
MIN_MARGIN = 2.0

_STOP = {"the", "ground", "stadium", "cricket", "oval", "park", "club", "international", "and", "of"}


def norm_text(value: Optional[str]) -> str:
    if not value:
        return ""
    v = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", v.lower()).strip()


def norm_team(name: str, aliases: Optional[Dict[str, str]] = None) -> str:
    key = norm_text(name)
    if aliases:
        key = aliases.get(key, key)
    return key


def _tokens(value: Optional[str]) -> set:
    return {t for t in norm_text(value).split() if t not in _STOP and len(t) > 1}


def venue_similarity(a: Optional[str], b: Optional[str]) -> Optional[float]:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return None
    return len(ta & tb) / len(ta | tb)


@dataclass
class MatchKey:
    """The identifying facts one source gives about a match."""
    start_date: date
    gender: str
    format_class: str
    teams: Sequence[str]
    venue: Optional[str] = None
    competition: Optional[str] = None
    winner: Optional[str] = None
    result_type: Optional[str] = None
    innings_totals: Dict[int, int] = field(default_factory=dict)  # innings_number -> runs
    canonical_id: Optional[str] = None


@dataclass
class Decision:
    status: str
    canonical_id: Optional[str] = None
    confidence: Optional[float] = None
    evidence: Dict = field(default_factory=dict)
    candidates: List[Dict] = field(default_factory=list)


def score(record: MatchKey, cand: MatchKey, team_aliases: Optional[Dict[str, str]] = None) -> Optional[Dict]:
    """Score a candidate; ``None`` when a hard constraint rules it out."""
    if record.gender != cand.gender or not compatible(record.format_class, cand.format_class):
        return None
    if {norm_team(t, team_aliases) for t in record.teams} != {norm_team(t, team_aliases) for t in cand.teams}:
        return None
    tolerance = 1 if is_limited_overs(record.format_class) else 2
    delta = abs((record.start_date - cand.start_date).days)
    if delta > tolerance:
        return None
    ev: Dict = {"date_delta_days": delta}
    s = 3.0 if delta == 0 else 1.0
    sim = venue_similarity(record.venue, cand.venue)
    if sim is not None:
        ev["venue_similarity"] = round(sim, 2)
        s += 2.0 if sim >= 0.5 else (0.5 if sim > 0 else -1.5)
    if record.competition and cand.competition:
        same = bool(_tokens(record.competition) & _tokens(cand.competition))
        ev["competition_overlap"] = same
        s += 1.0 if same else -0.5
    if record.result_type and cand.result_type and (record.winner or cand.winner):
        agree = record.result_type == cand.result_type and (
            norm_team(record.winner or "", team_aliases) == norm_team(cand.winner or "", team_aliases))
        ev["result_agrees"] = agree
        s += 1.0 if agree else -5.0
    shared = set(record.innings_totals) & set(cand.innings_totals)
    if shared:
        agree = sum(1 for n in shared if record.innings_totals[n] == cand.innings_totals[n])
        if agree == 0:
            return None  # every comparable innings total differs: a different fixture (e.g. a double-header)
        ev["innings_totals_agree"] = f"{agree}/{len(shared)}"
        s += 2.0 * agree - 4.0 * (len(shared) - agree)
    ev["score"] = round(s, 2)
    return ev


def decide(record: MatchKey, candidates: Iterable[MatchKey], team_aliases: Optional[Dict[str, str]] = None) -> Decision:
    scored = []
    for cand in candidates:
        ev = score(record, cand, team_aliases)
        if ev is not None:
            scored.append((ev["score"], cand, ev))
    if not scored:
        return Decision(NEW)
    scored.sort(key=lambda x: -x[0])
    summary = [{"canonical_id": c.canonical_id, **ev} for _, c, ev in scored]
    best_score, best, best_ev = scored[0]
    if best_score < ACCEPT_SCORE:
        # Same teams/date but contradicting evidence: a different fixture, not this one.
        return Decision(NEW, evidence={"rejected": summary}) if best_score < 0 else Decision(AMBIGUOUS, candidates=summary)
    if len(scored) > 1 and best_score - scored[1][0] < MIN_MARGIN:
        return Decision(AMBIGUOUS, candidates=summary)
    confidence = min(1.0, round(best_score / 9.0, 2))
    return Decision(MATCHED, best.canonical_id, confidence, best_ev, summary)
