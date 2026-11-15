"""Pure statistical helpers shared by the insight endpoints.

Every function here works on already-aggregated rows so it can be unit tested
without a database. Formulas are documented inline; nothing here substitutes a
missing value with zero - undefined ratios are returned as ``None``.
"""
from __future__ import annotations

import math
from statistics import median
from typing import Iterable, Optional, Sequence

# Standard innings length used for net run rate when a side is bowled out.
FORMAT_INNINGS_BALLS = {"T20": 120, "T20I": 120, "ODI": 300, "ODM": 300}

# Delivery-phase boundaries (zero-indexed over numbers), identical to PHASE_RULES.md.
PHASE_OVERS = {
    "T20": {"powerplay": (0, 5), "middle": (6, 14), "death": (15, 19)},
    "T20I": {"powerplay": (0, 5), "middle": (6, 14), "death": (15, 19)},
    "ODI": {"powerplay": (0, 9), "middle": (10, 39), "death": (40, 49)},
    "ODM": {"powerplay": (0, 9), "middle": (10, 39), "death": (40, 49)},
}


def ratio(numerator, denominator, scale: float = 1.0, digits: int = 2) -> Optional[float]:
    """``numerator / denominator * scale`` or ``None`` when the denominator is 0/None."""
    if numerator is None or not denominator:
        return None
    return round(numerator * scale / denominator, digits)


def overs_display(legal_balls: Optional[int]) -> Optional[str]:
    """Cricket overs notation (overs.balls), never decimal overs."""
    if legal_balls is None:
        return None
    return f"{legal_balls // 6}.{legal_balls % 6}"


def batting_rates(runs: int, balls: int, dismissals: int, fours: int = 0, sixes: int = 0, dots: int = 0) -> dict:
    """Average = runs / dismissals; SR = runs per 100 balls faced;
    boundary % and dot % use balls faced as denominator."""
    return {
        "average": ratio(runs, dismissals),
        "strike_rate": ratio(runs, balls, 100),
        "boundary_percentage": ratio(fours + sixes, balls, 100),
        "dot_percentage": ratio(dots, balls, 100),
        "balls_per_dismissal": ratio(balls, dismissals, 1, 1),
    }


def bowling_rates(runs: int, legal_balls: int, wickets: int, dots: int = 0, boundaries: int = 0) -> dict:
    """Economy = runs * 6 / legal balls; average = runs / wickets;
    strike rate = legal balls / wickets; dot/boundary % over legal balls."""
    return {
        "economy": ratio(runs, legal_balls, 6),
        "average": ratio(runs, wickets),
        "strike_rate": ratio(legal_balls, wickets, 1, 1),
        "dot_percentage": ratio(dots, legal_balls, 100),
        "boundary_percentage": ratio(boundaries, legal_balls, 100),
    }


def rolling_mean(values: Sequence[Optional[float]], window: int) -> list:
    """Trailing moving average. Positions with fewer than ``window`` observations are ``None``."""
    out = []
    for i in range(len(values)):
        if i + 1 < window:
            out.append(None)
            continue
        chunk = [v for v in values[i + 1 - window:i + 1] if v is not None]
        out.append(round(sum(chunk) / len(chunk), 2) if len(chunk) == window else None)
    return out


def rolling_average_by_dismissal(runs: Sequence[int], dismissed: Sequence[bool], window: int) -> list:
    """Trailing batting average over the last ``window`` innings (runs / dismissals in window)."""
    out = []
    for i in range(len(runs)):
        if i + 1 < window:
            out.append(None)
            continue
        r = sum(runs[i + 1 - window:i + 1])
        d = sum(1 for x in dismissed[i + 1 - window:i + 1] if x)
        out.append(round(r / d, 2) if d else None)
    return out


def consistency_summary(innings_runs: Sequence[int], dismissed: Optional[Sequence[bool]] = None) -> dict:
    """Distribution of runs per innings.

    * ``std_dev`` is the sample standard deviation (n-1); ``None`` below two innings.
    * ``coefficient_of_variation`` = std_dev / mean (lower = more consistent).
    * band counts are inclusive lower bounds (30+ counts 50s and 100s too).
    """
    n = len(innings_runs)
    if n == 0:
        return {"innings": 0}
    mean = sum(innings_runs) / n
    sd = math.sqrt(sum((x - mean) ** 2 for x in innings_runs) / (n - 1)) if n > 1 else None
    bands = {
        "under_10": sum(1 for x in innings_runs if x < 10),
        "ducks": sum(1 for i, x in enumerate(innings_runs) if x == 0 and (dismissed is None or dismissed[i])),
        "30_plus": sum(1 for x in innings_runs if x >= 30),
        "50_plus": sum(1 for x in innings_runs if x >= 50),
        "100_plus": sum(1 for x in innings_runs if x >= 100),
    }
    return {
        "innings": n,
        "mean_runs_per_innings": round(mean, 2),
        "median_runs": median(innings_runs),
        "std_dev": round(sd, 2) if sd is not None else None,
        "coefficient_of_variation": round(sd / mean, 3) if sd is not None and mean else None,
        **{f"{k}_count": v for k, v in bands.items()},
        **{f"{k}_percentage": round(v * 100 / n, 1) for k, v in bands.items()},
    }


def histogram(values: Iterable[float], bin_width: float, start: float = 0) -> list:
    """Fixed-width bins ``[lo, hi)``; empty interior bins are kept so gaps are visible."""
    vals = [v for v in values if v is not None]
    if not vals or bin_width <= 0:
        return []
    lo = start if min(vals) >= start else math.floor(min(vals) / bin_width) * bin_width
    top = max(vals)
    bins = []
    edge = lo
    while edge <= top:
        hi = edge + bin_width
        bins.append({"bin_start": edge, "bin_end": hi, "label": (str(int(edge)) if bin_width == 1 else f"{int(edge)}–{int(hi - 1)}") if float(bin_width).is_integer() else f"{edge}–{hi}",
                     "count": sum(1 for v in vals if edge <= v < hi)})
        edge = hi
    return bins


def normalise_bowling_style(raw: Optional[str]) -> Optional[str]:
    """Canonical casing for stored bowling-style labels ("Right-arm off break" -> "Right-arm Off Break")."""
    if not raw or not raw.strip():
        return None
    words = []
    for word in raw.strip().split():
        parts = word.split("-")
        words.append("-".join(p if p.lower() == "arm" else p.capitalize() for p in parts))
    return " ".join(words)


def net_run_rate(runs_for: int, balls_faced: int, runs_against: int, balls_bowled: int) -> Optional[float]:
    """NRR = runs_for / overs_faced - runs_against / overs_bowled.

    Callers must already have replaced balls with the full quota for innings in
    which the side was bowled out (see :func:`nrr_balls`)."""
    if not balls_faced or not balls_bowled:
        return None
    return round(runs_for * 6 / balls_faced - runs_against * 6 / balls_bowled, 3)


def nrr_balls(legal_balls: int, wickets: int, quota_balls: Optional[int]) -> int:
    """All-out innings count as the full quota of overs for NRR (ICC rule)."""
    if quota_balls and wickets >= 10:
        return quota_balls
    return legal_balls


def build_standings(results: Sequence[dict]) -> list:
    """Aggregate per-team results into a table.

    ``results`` rows: team, team_id, outcome in {won, lost, tied, no_result},
    runs_for, balls_for, runs_against, balls_against (balls already NRR-adjusted).
    Points use the common 2 per win, 1 per tie / no result convention.
    """
    table: dict = {}
    for r in results:
        row = table.setdefault(r["team_id"], {"team_id": r["team_id"], "team": r["team"], "played": 0, "won": 0, "lost": 0,
                                              "tied": 0, "no_result": 0, "runs_for": 0, "balls_for": 0,
                                              "runs_against": 0, "balls_against": 0})
        row["played"] += 1
        row[r["outcome"]] += 1
        if r["outcome"] != "no_result":
            for k in ("runs_for", "balls_for", "runs_against", "balls_against"):
                row[k] += r.get(k) or 0
    out = []
    for row in table.values():
        row["points"] = row["won"] * 2 + row["tied"] + row["no_result"]
        row["net_run_rate"] = net_run_rate(row["runs_for"], row["balls_for"], row["runs_against"], row["balls_against"])
        row["win_percentage"] = ratio(row["won"], row["played"] - row["no_result"], 100, 1)
        row["overs_for"] = overs_display(row["balls_for"])
        row["overs_against"] = overs_display(row["balls_against"])
        out.append(row)
    out.sort(key=lambda r: (-r["points"], -(r["net_run_rate"] if r["net_run_rate"] is not None else -99), r["team"]))
    for i, row in enumerate(out, 1):
        row["position"] = i
    return out


def percentile_rank(value: Optional[float], population: Sequence[float], lower_is_better: bool = False) -> Optional[float]:
    """Share of the population the value beats or equals (0-100, mid-rank for ties)."""
    pop = [p for p in population if p is not None]
    if value is None or not pop:
        return None
    below = sum(1 for p in pop if p < value)
    equal = sum(1 for p in pop if p == value)
    pct = (below + 0.5 * equal) / len(pop) * 100
    return round(100 - pct if lower_is_better else pct, 1)
