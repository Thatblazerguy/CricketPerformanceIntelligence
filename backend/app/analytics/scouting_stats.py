"""Statistical primitives for scouting: shrinkage, intervals, reliability, percentiles.

Everything here is pure Python so it can be unit tested without a database.

Shrinkage model
---------------
Every rate metric is a ratio ``numerator / denominator`` where the denominator
is the sample unit (balls faced, legal balls, dismissals, innings). Each player's
observed rate is pulled towards the comparison-group mean in proportion to how
little evidence they have:

    shrunk = (num + m * prior_mean) / (den + m)

``m`` (the *prior strength*, in sample units) is estimated from the cohort by the
method of moments rather than chosen by hand:

    tau^2 = between-player variance of true rates
          = (weighted observed variance) - (expected sampling variance)
    m     = unit_variance / tau^2

where ``unit_variance`` is the variance contributed by a single sample unit:

* proportions (dot %, boundary %, wicket per ball): p (1 - p)
* runs per ball (strike rate / economy): E[x^2] - E[x]^2 from stored runs_sq
* runs per dismissal (averages): mean^2, because individual scores between
  dismissals are close to exponentially distributed (variance ~= mean^2).

The *reliability* of a player's metric is ``den / (den + m)`` - the share of the
shrunk estimate that comes from the player's own data. This is the same quantity
as the classical test-theory reliability of a mean of ``den`` observations.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from statistics import median, pstdev
from typing import Iterable, List, Optional, Sequence, Tuple

Z95 = 1.959964
ESTABLISHED = 0.60
PROMISING = 0.30


@dataclass(frozen=True)
class Prior:
    mean: float
    strength: float          # m, in sample units
    unit_variance: float
    players: int
    fallback: bool = False   # True when the cohort was too small to estimate tau^2

    def as_dict(self) -> dict:
        return {"mean": round(self.mean, 5), "strength": round(self.strength, 1),
                "players": self.players, "fallback": self.fallback}


def ratio(num, den, scale: float = 1.0) -> Optional[float]:
    """Return num/den*scale, or None when the denominator is zero/missing (never 0)."""
    if num is None or not den:
        return None
    return float(num) * scale / float(den)


def estimate_prior(pairs: Sequence[Tuple[float, float]], kind: str, sumsq: Optional[float] = None,
                   min_players: int = 15, bounds: Tuple[float, float] = (1.0, 5000.0)) -> Optional[Prior]:
    """Method-of-moments estimate of the cohort prior for a ratio metric.

    ``pairs`` are (numerator, denominator) per player; players with den <= 0 are
    ignored. ``kind`` is 'proportion', 'per_unit' (needs ``sumsq`` = cohort total
    of squared per-unit values) or 'exponential'.
    """
    data = [(float(n), float(d)) for n, d in pairs if d and d > 0 and n is not None]
    if not data:
        return None
    total_n = sum(d for _, d in data)
    total_x = sum(n for n, _ in data)
    mean = total_x / total_n
    if kind == "proportion":
        unit_var = max(mean * (1 - mean), 1e-9)
    elif kind == "per_unit":
        if sumsq is None:
            raise ValueError("per_unit priors need the cohort sum of squares")
        unit_var = max(sumsq / total_n - mean * mean, 1e-9)
    elif kind == "exponential":
        unit_var = max(mean * mean, 1e-9)
    else:  # pragma: no cover - programming error
        raise ValueError(kind)

    k = len(data)
    if k < min_players:
        median_den = sorted(d for _, d in data)[k // 2]
        return Prior(mean, float(min(max(median_den, bounds[0]), bounds[1])), unit_var, k, fallback=True)
    # DerSimonian-Laird style estimator of the between-player variance.
    q = sum(d * (n / d - mean) ** 2 for n, d in data)
    denom = total_n - sum(d * d for _, d in data) / total_n
    tau2 = (q - (k - 1) * unit_var) / denom if denom > 0 else 0.0
    if tau2 <= 0:
        return Prior(mean, bounds[1], unit_var, k)
    strength = unit_var / tau2
    return Prior(mean, float(min(max(strength, bounds[0]), bounds[1])), unit_var, k)


def shrink(num, den, prior: Optional[Prior]) -> Optional[float]:
    """Posterior-mean estimate; None when the player has no sample at all."""
    if prior is None or not den:
        return None
    return (float(num) + prior.strength * prior.mean) / (float(den) + prior.strength)


def reliability(den, prior: Optional[Prior]) -> Optional[float]:
    if prior is None or den is None:
        return None
    den = float(den)
    return den / (den + prior.strength) if den > 0 else 0.0


def wilson_interval(successes, n, z: float = Z95) -> Optional[Tuple[float, float]]:
    if not n:
        return None
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def mean_interval(total, n, unit_variance: float, z: float = Z95) -> Optional[Tuple[float, float]]:
    """Normal-approximation interval for a per-unit mean (e.g. runs per ball)."""
    if not n:
        return None
    m = total / n
    half = z * sqrt(max(unit_variance, 0.0) / n)
    return m - half, m + half


def average_interval(runs, dismissals, z: float = Z95) -> Optional[Tuple[float, float]]:
    """Interval for runs per dismissal under the exponential approximation."""
    if not dismissals:
        return None
    avg = runs / dismissals
    half = z * avg / sqrt(dismissals)
    return max(0.0, avg - half), avg + half


def percentile_rank(value: Optional[float], distribution: Sequence[float], higher_is_better: bool = True) -> Optional[float]:
    """Mid-rank percentile (ties count half). Returns None for a missing value."""
    if value is None or not distribution:
        return None
    below = sum(1 for x in distribution if x < value)
    equal = sum(1 for x in distribution if x == value)
    pct = 100.0 * (below + 0.5 * equal) / len(distribution)
    return round(pct if higher_is_better else 100.0 - pct, 1)


def quantile(values: Sequence[float], q: float) -> Optional[float]:
    data = sorted(v for v in values if v is not None)
    if not data:
        return None
    pos = (len(data) - 1) * q
    lo, hi = int(pos), min(int(pos) + 1, len(data) - 1)
    return data[lo] + (data[hi] - data[lo]) * (pos - lo)


def consistency_summary(scores: Sequence[float], good: float, poor: float) -> dict:
    """Distribution summary of per-innings values (e.g. runs per innings)."""
    values = [float(v) for v in scores if v is not None]
    n = len(values)
    if not n:
        return {"innings": 0}
    avg = sum(values) / n
    sd = pstdev(values) if n > 1 else 0.0
    return {
        "innings": n,
        "mean": round(avg, 2),
        "median": round(median(values), 2),
        "sd": round(sd, 2),
        "cv": round(sd / avg, 3) if avg > 0 else None,
        "p25": round(quantile(values, 0.25), 2),
        "p75": round(quantile(values, 0.75), 2),
        "significant_pct": round(100.0 * sum(1 for v in values if v >= good) / n, 1),
        "poor_pct": round(100.0 * sum(1 for v in values if v < poor) / n, 1),
    }


def rolling(values: Sequence[float], window: int) -> List[Optional[float]]:
    """Trailing rolling mean; positions before a full window are None."""
    out: List[Optional[float]] = []
    total = 0.0
    for i, v in enumerate(values):
        total += v
        if i >= window:
            total -= values[i - window]
        out.append(round(total / window, 2) if i >= window - 1 else None)
    return out


def tier(rel: Optional[float]) -> str:
    """Evidence tier from the profile reliability (share of estimate from own data).

    Cut-offs were calibrated on T20 middle-order batters (median profile
    reliability: 0.25 at 10–20 innings, 0.34 at 20–40, 0.47 at 40–80, 0.67 at 80+):
    Established ≥ 0.60 (most of the estimate is the player's own record),
    Promising ≥ 0.30, otherwise Insufficient.
    """
    if rel is None:
        return "Insufficient data"
    if rel >= ESTABLISHED:
        return "Established"
    if rel >= PROMISING:
        return "Promising – limited evidence"
    return "Insufficient data"


def weighted_mean(pairs: Iterable[Tuple[Optional[float], float]]) -> Optional[float]:
    items = [(v, w) for v, w in pairs if v is not None and w > 0]
    total = sum(w for _, w in items)
    return sum(v * w for v, w in items) / total if total else None
