"""Per-innings reconciliation between the ball-by-ball and scorecard layers.

One innings is counted once, however many sources hold it. When sources agree
the value is used. When they disagree the disagreement is returned as a conflict
(with every source's value) for the caller to persist, and the value used is
chosen by an explicit, documented precedence, never arbitrarily:

1. Ball-by-ball data from an innings whose coverage is complete (every delivery
   present) is the primary record and wins.
2. If delivery data is partial, a validated scorecard is preferred for totals,
   because missing deliveries can only under-count.
3. If only scorecards remain and they disagree, the value is left unresolved
   (``None``): the innings still counts as played but the metric is marked
   incomplete until someone reconciles it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

BALL_BY_BALL, SCORECARD = "ball_by_ball", "scorecard"

BAT_FIELDS = ("runs", "balls", "fours", "sixes", "is_out")
BOWL_FIELDS = ("legal_balls", "runs_conceded", "wickets", "maidens")


@dataclass
class SourceRecord:
    level: str                    # ball_by_ball / scorecard
    source_key: str
    values: Dict[str, Optional[object]]
    complete: bool = True         # for ball-by-ball: innings coverage is FULL


@dataclass
class Reconciled:
    values: Dict[str, Optional[object]]
    provenance: str               # ball_by_ball / scorecard / both_agree / reconciled
    sources: List[str]
    conflicts: List[Tuple[str, Dict[str, object], Optional[object], str]] = field(default_factory=list)
    # (metric, {source: value}, value_used, rule)


def _pick(field_name: str, records: Sequence[SourceRecord]):
    present = [(r, r.values.get(field_name)) for r in records if r.values.get(field_name) is not None]
    if not present:
        return None, None
    distinct = {v for _, v in present}
    if len(distinct) == 1:
        return present[0][1], None
    values = {r.source_key: v for r, v in present}
    full_bb = [v for r, v in present if r.level == BALL_BY_BALL and r.complete]
    if full_bb:
        return full_bb[0], (field_name, values, full_bb[0], "complete_ball_by_ball_precedence")
    scorecards = {v for r, v in present if r.level == SCORECARD}
    if len(scorecards) == 1:
        v = next(iter(scorecards))
        return v, (field_name, values, v, "scorecard_over_partial_deliveries")
    return None, (field_name, values, None, "unresolved_scorecard_disagreement")


def reconcile(records: Sequence[SourceRecord], fields: Sequence[str]) -> Reconciled:
    if not records:
        raise ValueError("reconcile() needs at least one source record")
    out: Dict[str, Optional[object]] = {}
    conflicts = []
    for f in fields:
        value, conflict = _pick(f, records)
        out[f] = value
        if conflict:
            conflicts.append(conflict)
    levels = {r.level for r in records}
    if len(records) == 1:
        provenance = records[0].level
    elif conflicts:
        provenance = "reconciled"
    else:
        provenance = "both_agree" if len(levels) > 1 else records[0].level
    return Reconciled(out, provenance, sorted(r.source_key for r in records), conflicts)
