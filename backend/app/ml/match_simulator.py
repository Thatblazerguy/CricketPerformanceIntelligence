"""Ball-by-ball cricket match engine calibrated from CPI delivery history.

How a delivery is decided
-------------------------
Every ball samples one outcome class (``sim_calibration.CLASSES``: runs off the
bat 0-6, bowler wicket, run out, wide, no-ball, bye, leg-bye). The probability
of each class is a log-linear combination of empirical, smoothed rates::

    p(c) ∝ base[innings, over bucket, wickets down](c)       # format/gender baseline
           × chase_pressure[phase, required-rate band](c)     # limited-overs chases
           × batter_ratio[phase, bowling type](c)             # batter vs league
           × bowler_ratio[phase](c)                           # bowler vs league
           × venue_ratio[bowling type](c)                     # historical venue effect
           × conditions(c)                                    # pitch / weather settings

Each ratio is an observed/expected rate shrunk toward its parent level
(career → phase → phase×bowling-type) with pseudo-counts, so small samples fall
back smoothly to a position-specific prior (openers, top order, middle order,
tail) instead of producing extreme values. All of this is prepared once per
request in :class:`SimModel`; the per-ball cost is a cached lookup and a
bisect.

Match rules implemented: legal-ball over completion, strike rotation on odd
runs (including byes, leg-byes, wides and run-outs) and at over end, new batter
on strike after a caught dismissal, free hits after no-balls, per-bowler over
limits with no consecutive overs, all-out at ten wickets, target chases ending
the innings immediately, ties with repeated super overs (limited overs), and
for Tests: four innings, a 450-over match budget, follow-on, declarations and
draws.
"""
from __future__ import annotations

import math
import random
from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from app.ml.sim_calibration import (
    BAT_CLASSES, CLASS_INDEX, CLASSES, DEFAULT_OVERS, FORMAT_TO_FAMILY, PHASES, RRR_BANDS,
    bowler_band, over_bucket, phase_of, position_band,
)

NC = len(CLASSES)
I = CLASS_INDEX
BAT_IDX = tuple(I[c] for c in BAT_CLASSES)
BOWL_IDX = BAT_IDX + (I["WD"], I["NB"])
RUNS_OF = {I["R0"]: 0, I["R1"]: 1, I["R2"]: 2, I["R3"]: 3, I["R4"]: 4, I["R5"]: 5, I["R6"]: 6}
BOWLER_WICKET_KINDS = ("caught", "bowled", "lbw", "stumped", "caught and bowled", "hit wicket")
MAX_SIMULATIONS = {"T20": 5000, "ODI": 2000, "Test": 300}

# Player ratios enter as ratio**exponent (a damping hook). Conditioning the baseline on wickets lost
# could double count batting quality, but backtests on 120 men's T20 matches (2024+) showed exponent
# 1.0 unbiased (first innings -1.2 runs) with the best Brier score; see scripts/backtest_match_simulator.py.
PLAYER_EXPONENT = {"T20": 1.0, "ODI": 1.0, "Test": 1.0}
# Half-life (years) for the scoring-era adjustment of the baseline.
ERA_HALF_LIFE_YEARS = 3.0
# Pseudo-counts (in balls) for hierarchical shrinkage.
K_BASE, K_PRESSURE, K_POSITION = 400.0, 300.0, 300.0
K_BAT_CAREER, K_BAT_PHASE, K_BAT_TYPE = 200.0, 150.0, 120.0
K_BOWL_CAREER, K_BOWL_PHASE = 240.0, 150.0
K_VENUE, K_USAGE, K_DISMISSAL = 3000.0, 120.0, 30.0
# A player with fewer recorded balls than this is treated as a part-time bowler.
PART_TIME_BALLS = 60
# Players with at least this many balls bowled (or a recorded bowling type) are frontline options.
GENUINE_BOWLER_BALLS = 300

# Pitch and weather are user-selected scenario settings, not inferred from data:
# these multipliers are deliberately modest, documented assumptions.
PITCH_EFFECTS = {
    "balanced": {},
    "batting": {"*": {"R4": 1.12, "R6": 1.15, "W": 0.88, "R0": 0.95}},
    "bowling": {"*": {"R4": 0.88, "R6": 0.85, "W": 1.15, "R0": 1.06}},
    "spin": {"spin": {"W": 1.2, "R4": 0.9, "R6": 0.9, "R0": 1.05}, "pace": {"R4": 1.03}},
    "seam": {"pace": {"W": 1.2, "R4": 0.92, "R0": 1.05}, "spin": {"R4": 1.04}},
}
WEATHER_EFFECTS = {
    "clear": {},
    "overcast": {"pace": {"W": 1.12, "R4": 0.95, "WD": 1.05}},
    # Dew affects bowling later in the day: applied from the second innings.
    "dew": {"spin": {"W": 0.85, "R4": 1.08, "R6": 1.08, "WD": 1.15}, "pace": {"WD": 1.1, "R4": 1.04}},
}
# Fallback prior for players with almost no bowling record, used only when the
# calibration lacks workload-band priors (older calibration files).
PART_TIMER_PRIOR = {"R4": 1.2, "R6": 1.25, "R0": 0.92, "W": 0.8, "WD": 1.3}
K_BAND = 2000.0
# Latent match conditions: equal-probability bins of a standard normal.
CONDITION_BINS = 7
_ND = __import__("statistics").NormalDist()
CONDITION_Z = [_ND.inv_cdf((k + 0.5) / CONDITION_BINS) for k in range(CONDITION_BINS)]
MID_BIN = CONDITION_BINS // 2


@dataclass
class FormatRules:
    fmt: str
    family: str
    overs: Optional[int]          # per innings; None for Tests
    max_bowler_overs: Optional[int]
    innings: int                  # innings per side x 2
    free_hit: bool
    super_over: bool
    match_overs: Optional[int] = None   # Tests: playing-time budget in overs
    follow_on: int = 200

    @property
    def limited(self) -> bool:
        return self.overs is not None


def rules_for(fmt: str, *, overs: Optional[int] = None, super_over: bool = True) -> FormatRules:
    family = FORMAT_TO_FAMILY.get(fmt)
    if family is None:
        raise ValueError(f"Unsupported format {fmt!r}; use T20, T20I, ODI, ODM or Test")
    if family == "Test":
        return FormatRules(fmt, family, None, None, 4, False, False, match_overs=450)
    default = DEFAULT_OVERS[family]
    n = int(overs or default)
    if not 1 <= n <= default:
        raise ValueError(f"{fmt} innings must be between 1 and {default} overs")
    per_bowler = max(1, math.ceil(n / 5))  # 4 of 20, 10 of 50, and pro-rata for shortened games
    return FormatRules(fmt, family, n, per_bowler, 2, True, super_over)


def _normalise(vec):
    s = sum(vec)
    return [v / s for v in vec] if s > 0 else [1.0 / len(vec)] * len(vec)


def _cum(vec):
    out, acc = [], 0.0
    for v in vec:
        acc += v
        out.append(acc)
    return out


def _dist_from_counts(counts: Dict[str, float], default: int = 1) -> Tuple[List[int], List[float]]:
    items = sorted((int(k), float(v)) for k, v in (counts or {}).items() if float(v) > 0)
    if not items:
        return [default], [1.0]
    values = [k for k, _ in items]
    return values, _cum(_normalise([v for _, v in items]))


def _restricted(vec, idx):
    """Probability vector over the classes in ``idx`` (others zero)."""
    total = sum(vec[i] for i in idx)
    out = [0.0] * NC
    if total > 0:
        for i in idx:
            out[i] = vec[i] / total
    return out


# ---------------------------------------------------------------------------
# Model: everything precomputed once per request
# ---------------------------------------------------------------------------

class SimModel:
    """Smoothed rates for one format family, gender, venue and pair of XIs."""

    def __init__(self, calibration: dict, family: str, gender: str, profiles: Dict[str, dict], meta: Dict[str, dict],
                 *, venue: Optional[dict] = None, pitch: str = "balanced", weather: str = "clear",
                 positions: Optional[Dict[str, int]] = None, keepers: Optional[set] = None,
                 player_exponent: Optional[float] = None, condition_scale: Optional[float] = None,
                 bowler_priors: bool = True):
        block = calibration["genders"].get(gender) or next(iter(calibration["genders"].values()))
        self.family, self.gender = family, gender
        self.player_exponent = PLAYER_EXPONENT.get(family, 1.0) if player_exponent is None else player_exponent
        self.phases = PHASES[family]
        self.meta = meta
        self.keepers = set(keepers or ())
        self.calibration_meta = {"version": calibration.get("version"), "built_at": calibration.get("built_at"),
                                 "since": calibration.get("since"), "deliveries": block.get("deliveries"),
                                 "historical_innings": block.get("innings_totals", {})}
        # League references by phase and bowling type.
        self.ref: Dict[str, List[float]] = {}
        for key, counts in block["ref"].items():
            self.ref[key] = _normalise(counts)
        self.ref_all = _normalise([sum(block["ref"].get(f"{p}|*", [0] * NC)[i] for p in self.phases) for i in range(NC)])
        for p in self.phases:
            self.ref.setdefault(f"{p}|*", self.ref_all)
            for t in ("pace", "spin", "unknown"):
                self.ref.setdefault(f"{p}|{t}", self.ref[f"{p}|*"])
        self.ref_year = {key: _normalise(counts) for key, counts in block.get("ref_year", {}).items()}
        # Latent match conditions shared by both innings (pitch/weather/ground on the day).
        cond_cal = block.get("conditions") or {}
        beta = cond_cal.get("beta") or [0.0] * NC
        scale = cond_cal.get("scale", 0.0) if condition_scale is None else condition_scale
        self.condition_scale = scale
        self.condition_info = {"rho_observed": cond_cal.get("rho"), "scale": scale, "matches": cond_cal.get("pairs"),
                               "rho_simulated": cond_cal.get("rho_simulated")}
        self.cond_mult = [[math.exp(scale * beta[i] * z) for i in range(NC)] for z in CONDITION_Z]
        # Bowling priors by career workload band (part-time ... frontline), from data.
        self.bowler_priors = bowler_priors
        self.band_prior: Dict[str, List[float]] = {}
        observed: Dict[str, List[float]] = defaultdict(lambda: [0.0] * NC)
        expected: Dict[str, List[float]] = defaultdict(lambda: [0.0] * NC)
        for key, info in (block.get("bowler_bands") or {}).items():
            band, _, phase = key.partition("|")
            ref_p = _restricted(self.ref.get(f"{phase}|*", self.ref_all), BOWL_IDX)
            counts = info["counts"]
            n = sum(counts[i] for i in BOWL_IDX)
            for i in BOWL_IDX:
                observed[band][i] += counts[i]
                expected[band][i] += n * ref_p[i]
        ref_b = _restricted(self.ref_all, BOWL_IDX)
        for band in observed:
            # Phase-adjusted observed/expected ratio, lightly shrunk toward 1.
            self.band_prior[band] = [((observed[band][i] + K_BAND * ref_b[i]) / (expected[band][i] + K_BAND * ref_b[i]))
                                     if i in BOWL_IDX and ref_b[i] > 0 else 1.0 for i in range(NC)]
        # Era adjustment: recency-weighted league rates relative to the whole window, per phase.
        years = sorted({int(k.split("|")[0]) for k in block.get("ref_year", {})})
        self.era: Dict[str, List[float]] = {}
        latest = years[-1] if years else None
        for p in self.phases:
            acc = [0.0] * NC
            for y in years:
                counts = block["ref_year"].get(f"{y}|{p}|*")
                if not counts:
                    continue
                w = 0.5 ** ((latest - y) / ERA_HALF_LIFE_YEARS)
                for i in range(NC):
                    acc[i] += w * counts[i]
            era_ref = _normalise(acc) if sum(acc) else self.ref[f"{p}|*"]
            base_ref = self.ref[f"{p}|*"]
            self.era[p] = [era_ref[i] / base_ref[i] if base_ref[i] > 0 else 1.0 for i in range(NC)]
        # Baseline by innings/over bucket/wickets, smoothed to the innings/over level.
        self.base: Dict[Tuple[int, int, int], List[float]] = {}
        by_over: Dict[Tuple[int, int], List[float]] = defaultdict(lambda: [0.0] * NC)
        for key, counts in block["base"].items():
            inn, ob, wk = (int(x) for x in key.split("|"))
            agg = by_over[(inn, ob)]
            for i, v in enumerate(counts):
                agg[i] += v
        self._by_over = {}
        for (inn, ob), counts in by_over.items():
            phase_ref = self._phase_ref_for_bucket(ob)
            n = sum(counts)
            self._by_over[(inn, ob)] = [(counts[i] + K_BASE * phase_ref[i]) / (n + K_BASE) for i in range(NC)]
        for key, counts in block["base"].items():
            inn, ob, wk = (int(x) for x in key.split("|"))
            parent = self._by_over[(inn, ob)]
            n = sum(counts)
            self.base[(inn, ob, wk)] = [(counts[i] + K_BASE * parent[i]) / (n + K_BASE) for i in range(NC)]
        # Chase pressure tilt relative to all second-innings balls in the phase.
        self.pressure: Dict[Tuple[str, int], List[float]] = {}
        for p in self.phases:
            allp = block["pressure"].get(f"{p}|all")
            if not allp:
                continue
            ref = _normalise(allp)
            for band in range(0, 6):
                counts = block["pressure"].get(f"{p}|{band}")
                if not counts:
                    continue
                n = sum(counts)
                sm = [(counts[i] + K_PRESSURE * ref[i]) / (n + K_PRESSURE) for i in range(NC)]
                self.pressure[(p, band)] = [sm[i] / ref[i] if ref[i] > 0 else 1.0 for i in range(NC)]
        # Batting-position priors (ratio over batter-controlled classes).
        self.position: Dict[str, List[float]] = {}
        pos_totals: Dict[str, List[float]] = defaultdict(lambda: [0.0] * NC)
        ref_totals: Dict[str, List[float]] = defaultdict(lambda: [0.0] * NC)
        for key, counts in block["position"].items():
            phase, band = key.split("|")
            for i, v in enumerate(counts):
                pos_totals[band][i] += v
        for band, counts in pos_totals.items():
            bat = _restricted(counts, BAT_IDX)
            ref = _restricted(self.ref_all, BAT_IDX)
            n = sum(counts[i] for i in BAT_IDX)
            self.position[band] = [((bat[i] * n + K_POSITION * ref[i]) / (n + K_POSITION)) / ref[i] if i in BAT_IDX and ref[i] > 0 else 1.0
                                   for i in range(NC)]
        # Extras / run-out detail distributions.
        det = block.get("details", {})
        self.wide_runs = _dist_from_counts(det.get("WD"), 1)
        self.noball_bat_runs = _dist_from_counts(det.get("NB"), 0)
        self.bye_runs = _dist_from_counts(det.get("B"), 1)
        self.legbye_runs = _dist_from_counts(det.get("LB"), 1)
        self.runout_runs = _dist_from_counts(det.get("RO"), 0)
        ro = block.get("runout_striker") or [1, 1]
        self.runout_striker_p = (ro[0] + 1) / (sum(ro) + 2)
        self.dismissal_mix_type = {t: dict(v) for t, v in (block.get("dismissal_mix") or {}).items()}
        toss = block.get("toss") or {}
        self.toss_field_p = (toss.get("field", 1) + 1) / (sum(toss.values()) + 2) if toss else 0.6
        self.venue = venue
        if venue and venue.get("toss"):
            vt = venue["toss"]
            k = 20.0
            self.toss_field_p = (vt.get("field", 0) + k * self.toss_field_p) / (vt.get("field", 0) + vt.get("bat", 0) + k)
        # Venue ratios by bowling type.
        self.venue_ratio: Dict[str, List[float]] = {}
        for t in ("pace", "spin", "unknown", "*"):
            ref_t = _normalise([sum(block["ref"].get(f"{p}|{t}", [0] * NC)[i] for p in self.phases) for i in range(NC)])
            counts = (venue or {}).get("counts", {}).get(t) if venue else None
            if not counts or sum(ref_t) == 0:
                self.venue_ratio[t] = [1.0] * NC
                continue
            n = sum(counts)
            self.venue_ratio[t] = [((counts[i] + K_VENUE * ref_t[i]) / (n * ref_t[i] + K_VENUE * ref_t[i])) if ref_t[i] > 0 else 1.0
                                   for i in range(NC)]
        # Conditions: pitch for every innings, weather (dew) from the second innings.
        self.pitch, self.weather = pitch, weather
        self.cond: Dict[Tuple[str, bool], List[float]] = {}
        for t in ("pace", "spin", "unknown"):
            for later in (False, True):
                vec = [1.0] * NC
                for effects in (PITCH_EFFECTS.get(pitch, {}),
                                WEATHER_EFFECTS.get(weather, {}) if (weather != "dew" or later) else {}):
                    for scope in ("*", t):
                        for cls, mult in effects.get(scope, {}).items():
                            vec[I[cls]] *= mult
                self.cond[(t, later)] = vec
        # Player ratios.
        self.positions = dict(positions or {})
        self.profiles = profiles
        self.bat_ratio: Dict[str, Dict[str, List[float]]] = {}
        self.bowl_ratio: Dict[str, Dict[str, List[float]]] = {}
        self.usage: Dict[str, Dict[str, float]] = {}
        self.quality: Dict[str, float] = {}
        self.dismissal_cum: Dict[str, Tuple[List[str], List[float]]] = {}
        for pid in set(self.positions) | set(profiles):
            self._prepare_player(pid)
        self._cache: Dict[tuple, List[float]] = {}

    # -- preparation ---------------------------------------------------------
    def _phase_ref_for_bucket(self, ob: int) -> List[float]:
        if self.family == "T20":
            over = ob
        elif self.family == "ODI":
            over = ob * 5
        else:
            over = ob * 10
        return self.ref.get(f"{phase_of(self.family, over)}|*", self.ref_all)

    def btype(self, pid: str) -> str:
        return (self.meta.get(pid) or {}).get("bowling_type") or "unknown"

    def _year_ref(self, year: str, phase: str, btype: str, idx) -> List[float]:
        vec = self.ref_year.get(f"{year}|{phase}|{btype}") or self.ref.get(f"{phase}|{btype}") or self.ref_all
        return _restricted(vec, idx)

    def _prepare_player(self, pid: str) -> None:
        """Smoothed batting/bowling ratios. Observed counts are compared with the
        league rates of the *same season*, so scoring-era inflation is not
        attributed to individual players (the era is applied once, in ``era``)."""
        prof = self.profiles.get(pid) or {}
        band = position_band(self.positions.get(pid, 6))
        # Recency weights decide which seasons dominate a player's rates, not how much
        # evidence there is: rescale weighted counts to the actual number of balls, so a
        # retired or older player's record is not shrunk away toward the prior.
        bat_w = sum(sum(v[i] for i in BAT_IDX) for v in (prof.get("bat") or {}).values())
        bat_scale = (prof.get("bat_balls", 0) / bat_w) if bat_w > 0 and prof.get("bat_balls") else 1.0
        bowl_w = sum(sum(v) for v in (prof.get("bowl") or {}).values())
        bowl_scale = (prof.get("bowl_balls", 0) / bowl_w) if bowl_w > 0 and prof.get("bowl_balls") else 1.0
        pos = self.position.get(band, [1.0] * NC)
        # ---- batting: career -> phase -> phase x bowling type
        o = defaultdict(lambda: [0.0] * NC)   # keys: (phase, type)
        e = defaultdict(lambda: [0.0] * NC)
        for key, counts in prof.get("bat", {}).items():
            phase, t, year = key.split("|")
            if phase not in self.phases:
                continue
            counts = [c * bat_scale for c in counts]
            n = sum(counts[i] for i in BAT_IDX)
            refc = self._year_ref(year, phase, t, BAT_IDX)
            ov, ev = o[(phase, t)], e[(phase, t)]
            for i in BAT_IDX:
                ov[i] += counts[i]
                ev[i] += n * refc[i]
        o_all, e_all = [0.0] * NC, [0.0] * NC
        o_ph = {p: [0.0] * NC for p in self.phases}
        e_ph = {p: [0.0] * NC for p in self.phases}
        for (phase, t), ov in o.items():
            ev = e[(phase, t)]
            for i in BAT_IDX:
                o_ph[phase][i] += ov[i]
                e_ph[phase][i] += ev[i]
                o_all[i] += ov[i]
                e_all[i] += ev[i]
        m_all = _restricted(self.ref_all, BAT_IDX)
        career = [1.0] * NC
        for i in BAT_IDX:
            career[i] = (o_all[i] + K_BAT_CAREER * m_all[i] * pos[i]) / (e_all[i] + K_BAT_CAREER * m_all[i]) if m_all[i] > 0 else 1.0
        ratios: Dict[str, List[float]] = {}
        for p in self.phases:
            m_p = _restricted(self.ref[f"{p}|*"], BAT_IDX)
            r_p = [1.0] * NC
            for i in BAT_IDX:
                r_p[i] = (o_ph[p][i] + K_BAT_PHASE * m_p[i] * career[i]) / (e_ph[p][i] + K_BAT_PHASE * m_p[i]) if m_p[i] > 0 else 1.0
            ratios[f"{p}|unknown"] = r_p
            for t in ("pace", "spin"):
                ov, ev = o.get((p, t), [0.0] * NC), e.get((p, t), [0.0] * NC)
                refc = _restricted(self.ref[f"{p}|{t}"], BAT_IDX)
                r_t = [1.0] * NC
                for i in BAT_IDX:
                    r_t[i] = (ov[i] + K_BAT_TYPE * refc[i] * r_p[i]) / (ev[i] + K_BAT_TYPE * refc[i]) if refc[i] > 0 else 1.0
                ratios[f"{p}|{t}"] = r_t
        a = self.player_exponent
        if a != 1.0:
            ratios = {k: [x ** a for x in v] for k, v in ratios.items()}
        self.bat_ratio[pid] = ratios
        # ---- bowling: career -> phase (vs the all-type league reference of the season)
        n_total = prof.get("bowl_balls", 0)
        prior = [1.0] * NC
        if self.bowler_priors and self.band_prior:
            prior = list(self.band_prior.get(bowler_band(n_total)) or prior)
        elif self.bowler_priors and n_total < PART_TIME_BALLS:
            for cls, mult in PART_TIMER_PRIOR.items():
                prior[I[cls]] = mult
        bo = {p: [0.0] * NC for p in self.phases}
        be = {p: [0.0] * NC for p in self.phases}
        for key, counts in prof.get("bowl", {}).items():
            phase, year = key.split("|")
            if phase not in self.phases:
                continue
            refb = self._year_ref(year, phase, "*", BOWL_IDX)
            counts = [c * bowl_scale for c in counts]
            n = sum(counts[i] for i in BOWL_IDX)
            for i in BOWL_IDX:
                bo[phase][i] += counts[i]
                be[phase][i] += n * refb[i]
        o_all = [sum(bo[p][i] for p in self.phases) for i in range(NC)]
        e_all = [sum(be[p][i] for p in self.phases) for i in range(NC)]
        m_all_b = _restricted(self.ref_all, BOWL_IDX)
        career_b = [1.0] * NC
        for i in BOWL_IDX:
            career_b[i] = (o_all[i] + K_BOWL_CAREER * m_all_b[i] * prior[i]) / (e_all[i] + K_BOWL_CAREER * m_all_b[i]) if m_all_b[i] > 0 else 1.0
        bratios = {}
        for p in self.phases:
            refb = _restricted(self.ref[f"{p}|*"], BOWL_IDX)
            r = [1.0] * NC
            for i in BOWL_IDX:
                r[i] = (bo[p][i] + K_BOWL_PHASE * refb[i] * career_b[i]) / (be[p][i] + K_BOWL_PHASE * refb[i]) if refb[i] > 0 else 1.0
            bratios[p] = r
        if a != 1.0:
            bratios = {k: [x ** a for x in v] for k, v in bratios.items()}
        self.bowl_ratio[pid] = bratios
        # Bowling quality (for selection) and phase usage from history.
        exp_runs = sum(self.ref_all[i] * career_b[i] * RUNS_OF.get(i, 1 if i in (I["WD"], I["NB"]) else 0) for i in range(NC))
        base_runs = sum(self.ref_all[i] * RUNS_OF.get(i, 1 if i in (I["WD"], I["NB"]) else 0) for i in range(NC))
        wk_rel = career_b[I["W"]]
        self.quality[pid] = (base_runs / max(exp_runs, 1e-6)) ** 1.5 * wk_rel ** 0.5 * (1.0 if n_total >= PART_TIME_BALLS else 0.35)
        shares = self._phase_shares()
        phase_balls = prof.get("bowl_phase_balls", {})
        total = sum(phase_balls.values())
        self.usage[pid] = {p: ((phase_balls.get(p, 0.0) + K_USAGE * shares[p]) / (total + K_USAGE)) / shares[p] for p in self.phases}
        # Dismissal mix for bowler-credited wickets.
        type_mix = self.dismissal_mix_type.get(self.btype(pid)) or self.dismissal_mix_type.get("*") or {"caught": 1}
        tm_total = sum(type_mix.values()) or 1.0
        own = prof.get("dismissals", {})
        own_total = sum(own.get(k, 0) for k in BOWLER_WICKET_KINDS)
        kinds = list(BOWLER_WICKET_KINDS)
        weights = [(own.get(k, 0) + K_DISMISSAL * type_mix.get(k, 0) / tm_total) / (own_total + K_DISMISSAL) for k in kinds]
        self.dismissal_cum[pid] = (kinds, _cum(_normalise(weights)))

    def _phase_shares(self) -> Dict[str, float]:
        if self.family == "T20":
            return {"powerplay": 6 / 20, "middle": 9 / 20, "death": 5 / 20}
        if self.family == "ODI":
            return {"powerplay": 10 / 50, "middle": 30 / 50, "death": 10 / 50}
        return {"new_ball": 20 / 120, "middle": 60 / 120, "old_ball": 40 / 120}

    def ensure_player(self, pid: str, position: Optional[int] = None) -> None:
        if position is not None and self.positions.get(pid) != position:
            self.positions[pid] = position
            self._prepare_player(pid)
            self._cache = {k: v for k, v in self._cache.items() if k[0] != pid}
        elif pid not in self.bat_ratio:
            self._prepare_player(pid)

    # -- per-ball distribution -------------------------------------------------
    def cum_probs(self, batter: str, bowler: str, inn: int, over_index: int, wickets: int,
                  rrb: int, free_hit: bool, later: bool, survival: bool = False, zk: int = MID_BIN) -> List[float]:
        ob = over_bucket(self.family, over_index)
        wk = min(wickets, 9)
        key = (batter, bowler, inn, ob, wk, rrb, free_hit, later, survival, over_index if self.family == "Test" else 0, zk)
        hit = self._cache.get(key)
        if hit is not None:
            return hit
        phase = phase_of(self.family, over_index)
        base = self.base.get((inn, ob, wk)) or self._by_over.get((inn, ob)) or self.ref.get(f"{phase}|*", self.ref_all)
        t = self.btype(bowler)
        bat = self.bat_ratio[batter].get(f"{phase}|{t}") or self.bat_ratio[batter][f"{phase}|unknown"]
        bowl = self.bowl_ratio[bowler][phase]
        venue = self.venue_ratio.get(t) or self.venue_ratio["*"]
        cond = self.cond[(t, later)]
        era = self.era.get(phase) or [1.0] * NC
        press = self.pressure.get((phase, rrb)) if rrb >= 0 else None
        match_cond = self.cond_mult[zk]
        vec = [0.0] * NC
        for i in range(NC):
            v = base[i] * era[i] * bat[i] * bowl[i] * venue[i] * cond[i] * match_cond[i]
            if press is not None:
                v *= press[i]
            vec[i] = v
        if survival:  # Test fourth innings with the target out of reach: block for the draw
            vec[I["W"]] *= 0.7
            vec[I["R4"]] *= 0.55
            vec[I["R6"]] *= 0.4
            vec[I["R0"]] *= 1.25
        if free_hit:
            vec[I["W"]] = 0.0
        out = _cum(_normalise(vec))
        self._cache[key] = out
        return out

    def probabilities(self, batter: str, bowler: str, inn: int, over_index: int, wickets: int,
                      rrb: int = -1, free_hit: bool = False, later: bool = False, zk: int = MID_BIN) -> Dict[str, float]:
        cum = self.cum_probs(batter, bowler, inn, over_index, wickets, rrb, free_hit, later, zk=zk)
        prev, out = 0.0, {}
        for c, v in zip(CLASSES, cum):
            out[c] = v - prev
            prev = v
        return out

    def rrb_for(self, target: Optional[int], score: int, balls_left: int) -> int:
        bands = RRR_BANDS.get(self.family)
        if target is None or not bands or balls_left <= 0:
            return -1
        rate = (target - score) * 6.0 / balls_left
        band = 0
        for b in bands:
            if rate >= b:
                band += 1
        return band

    def __getstate__(self):
        state = dict(self.__dict__)
        state["_cache"] = {}
        return state


# ---------------------------------------------------------------------------
# Match state
# ---------------------------------------------------------------------------

@dataclass
class TeamSetup:
    key: str
    name: str
    order: List[str]
    keeper: Optional[str] = None
    captain: Optional[str] = None
    team_id: Optional[str] = None
    bowling_options: List[str] = field(default_factory=list)


@dataclass
class InningsResult:
    number: int
    batting: str
    bowling: str
    runs: int = 0
    wickets: int = 0
    legal_balls: int = 0
    target: Optional[int] = None
    declared: bool = False
    all_out: bool = False
    super_over: bool = False
    follow_on: bool = False
    deliveries: List[dict] = field(default_factory=list)
    bat: Dict[str, List[int]] = field(default_factory=dict)    # pid -> [runs, balls, 4s, 6s, out]
    bowl: Dict[str, List[int]] = field(default_factory=dict)   # pid -> [legal balls, conceded, wickets]
    field_credits: Dict[str, int] = field(default_factory=dict)
    batting_order_used: List[str] = field(default_factory=list)
    snapshots: List[dict] = field(default_factory=list)   # state at each over end (detailed runs)
    extras: Dict[str, int] = field(default_factory=lambda: {"wides": 0, "noballs": 0, "byes": 0, "legbyes": 0})


def _pick(values_cum: Tuple[List[int], List[float]], rng: random.Random) -> int:
    values, cum = values_cum
    return values[min(len(values) - 1, bisect_right(cum, rng.random() * cum[-1]))]


def can_cover(quota: Dict[str, int], last: Optional[str], remaining: int) -> bool:
    """Can ``remaining`` overs be bowled from these quotas with no bowler bowling consecutive overs?"""
    if remaining <= 0:
        return True
    usable = 0
    for b, q in quota.items():
        cap = remaining // 2 if b == last else (remaining + 1) // 2
        usable += min(q, cap)
    return usable >= remaining


class BowlingPlanner:
    """Chooses the bowler for each over from historical usage and quality."""

    def __init__(self, model: SimModel, options: List[str], rules: FormatRules, rng: random.Random):
        self.model, self.rules, self.rng = model, rules, rng
        self.options = list(options)
        cap = rules.max_bowler_overs
        self.quota = {b: (cap if cap is not None else 10 ** 6) for b in self.options}
        self.overs_bowled: Dict[str, int] = defaultdict(int)
        self.last: Optional[str] = None
        self.prev_last: Optional[str] = None
        self.spell: Dict[str, int] = defaultdict(int)

    def choose(self, over_index: int, overs_remaining_after: Optional[int]) -> str:
        phase = phase_of(self.model.family, over_index)
        cands, weights = [], []
        for b in self.options:
            if b == self.last or self.quota[b] <= 0:
                continue
            if overs_remaining_after is not None:
                q = dict(self.quota)
                q[b] -= 1
                if not can_cover(q, b, overs_remaining_after):
                    continue
            w = (self.model.quality.get(b, 0.3) ** 2) * (self.model.usage.get(b, {}).get(phase, 1.0) ** 1.2)
            continuing = b == self.prev_last
            if self.rules.family == "Test":
                s = self.spell[b] if continuing else 0
                w *= 3.0 if continuing and s < 5 else 1.0 if s < 8 else 0.15
            elif self.rules.family == "ODI" and continuing and self.spell[b] < 4:
                w *= 2.0
            w *= math.exp(self.rng.gauss(0.0, 0.3))
            cands.append(b)
            weights.append(w)
        if not cands:
            # Should not happen given the coverage check; fall back to anyone legal.
            cands = [b for b in self.options if b != self.last] or self.options
            weights = [1.0] * len(cands)
        x = self.rng.random() * sum(weights)
        for b, w in zip(cands, weights):
            x -= w
            if x <= 0:
                break
        self.spell[b] = self.spell[b] + 1 if b == self.prev_last else 1
        self.prev_last, self.last = self.last, b
        self.quota[b] -= 1
        self.overs_bowled[b] += 1
        return b


def is_frontline(model: SimModel, pid: str) -> bool:
    """A frontline bowler has a substantial record, or a recorded style and some record."""
    balls = (model.profiles.get(pid) or {}).get("bowl_balls", 0)
    return balls >= GENUINE_BOWLER_BALLS or (model.btype(pid) != "unknown" and balls >= PART_TIME_BALLS)


def bowling_options(model: SimModel, team: TeamSetup, rules: FormatRules) -> List[str]:
    """The attack a captain would use: frontline bowlers by quality (at most seven),
    topped up with part-timers until the overs can be covered under the limits."""
    if team.bowling_options:
        opts = [p for p in team.bowling_options if p in team.order]
    else:
        genuine = [p for p in team.order if p != team.keeper and is_frontline(model, p)]
        opts = sorted(genuine, key=lambda p: -model.quality.get(p, 0))[: 7 if rules.limited else 6]
    if rules.limited:
        cap = rules.max_bowler_overs
        need = max(1, math.ceil(rules.overs / cap))
    else:
        need = 5
    if len(opts) < need:
        extra = [p for p in team.order if p not in opts and p != team.keeper]
        extra.sort(key=lambda p: (-(model.profiles.get(p) or {}).get("bowl_balls", 0), -team.order.index(p)))
        opts += extra[: need - len(opts)]
    if rules.limited:
        cap = rules.max_bowler_overs
        while not can_cover({b: cap for b in opts}, None, rules.overs):
            extra = [p for p in team.order if p not in opts]
            if not extra:
                break
            opts.append(extra[-1])
    return opts


# ---------------------------------------------------------------------------
# Innings simulation
# ---------------------------------------------------------------------------

def play_innings(model: SimModel, rules: FormatRules, batting: TeamSetup, bowling: TeamSetup, inn: InningsResult,
                 rng: random.Random, *, base_inn: int, later: bool, detailed: bool,
                 max_balls: Optional[int] = None, max_wickets: int = 10, order: Optional[List[str]] = None,
                 bowlers: Optional[List[str]] = None, start: Optional[dict] = None,
                 lead_before: int = 0, overs_left_in_match: Optional[int] = None,
                 declare_fn=None, survival_target: bool = False, forced_bowler: Optional[str] = None,
                 zk: int = MID_BIN, loglik: Optional[List[float]] = None) -> InningsResult:
    """Simulate one innings ball by ball; mutates and returns ``inn``.

    ``zk`` is the match-conditions bin. When ``loglik`` (one entry per bin) is given,
    the log-likelihood of every sampled outcome under each bin is accumulated so
    later win-probability estimates can infer the conditions from what happened.

    ``start`` lets the innings resume from a live state:
    {score, wickets, legal_balls, striker, non_striker, next_index, overs_bowled}.
    """
    order = list(order or batting.order)
    options = list(bowlers or bowling_options(model, bowling, rules))
    planner = BowlingPlanner(model, options, rules, rng)
    start = start or {}
    score, wkts, legal = int(start.get("score", 0)), int(start.get("wickets", 0)), int(start.get("legal_balls", 0))
    striker = start.get("striker") or order[0]
    non_striker = start.get("non_striker") or order[1]
    next_idx = int(start.get("next_index", 2))
    for b, n in (start.get("overs_bowled") or {}).items():
        if b in planner.quota:
            planner.quota[b] -= int(n)
            planner.overs_bowled[b] += int(n)
    inn.runs, inn.wickets, inn.legal_balls = score, wkts, legal
    for pid in (striker, non_striker):
        inn.bat.setdefault(pid, [0, 0, 0, 0, 0])
        if pid not in inn.batting_order_used:
            inn.batting_order_used.append(pid)
    cap_balls = max_balls if max_balls is not None else (rules.overs * 6 if rules.limited else None)
    if detailed and not inn.super_over:
        inn.snapshots.append({"score": score, "wickets": wkts, "legal_balls": legal, "striker": striker, "non_striker": non_striker,
                              "next_index": next_idx, "overs_bowled": dict(planner.overs_bowled), "last_bowler": planner.last,
                              "loglik": list(loglik) if loglik is not None else None})
    target = inn.target
    free_hit = False
    keeper = bowling.keeper
    fielders = [p for p in bowling.order]
    survival = False
    bowler = start.get("bowler")
    chosen_for_over = legal // 6 if legal % 6 else -1
    if start.get("last_bowler") and legal % 6 == 0:
        planner.last = start["last_bowler"]
    if legal % 6 and bowler is None:
        raise ValueError("The current bowler is required to resume mid-over")
    if bowler is not None:
        inn.bowl.setdefault(bowler, [0, 0, 0])
        planner.last = bowler
    while True:
        if wkts >= max_wickets:
            inn.all_out = True
            break
        if cap_balls is not None and legal >= cap_balls:
            break
        if target is not None and score >= target:
            break
        if overs_left_in_match is not None and legal // 6 >= overs_left_in_match and legal % 6 == 0:
            break
        over_index = legal // 6
        if legal % 6 == 0 and over_index != chosen_for_over:
            # New over (first delivery, even if it is a wide/no-ball): declaration check (Tests) then choose the bowler.
            chosen_for_over = over_index
            if declare_fn is not None and legal > 0 and declare_fn(score, wkts, over_index):
                inn.declared = True
                break
            if forced_bowler is not None:
                bowler = forced_bowler
            else:
                remaining_after = None
                if cap_balls is not None:
                    remaining_after = max(0, math.ceil((cap_balls - legal) / 6) - 1)
                bowler = planner.choose(over_index, remaining_after)
            inn.bowl.setdefault(bowler, [0, 0, 0])
            if survival_target and target is not None and overs_left_in_match is not None:
                balls_left = max(1, overs_left_in_match * 6 - legal)
                survival = (target - score) * 6.0 / balls_left > 5.0
        balls_left = (cap_balls - legal) if cap_balls is not None else 0
        rrb = model.rrb_for(target, score, balls_left) if (rules.limited and target is not None) else -1
        cum = model.cum_probs(striker, bowler, base_inn, over_index, wkts, rrb, free_hit, later, survival, zk)
        ci = bisect_right(cum, rng.random() * cum[-1])
        if ci >= NC:
            ci = NC - 1
        if loglik is not None:
            for k in range(CONDITION_BINS):
                ck = model.cum_probs(striker, bowler, base_inn, over_index, wkts, rrb, free_hit, later, survival, k)
                pk = (ck[ci] - (ck[ci - 1] if ci else 0.0)) / ck[-1]
                loglik[k] += math.log(pk) if pk > 0 else -50.0
        cls = CLASSES[ci]
        was_free_hit = free_hit
        free_hit = False
        bat_runs = extras_runs = 0
        extra_type = None
        legal_ball = True
        wicket = None
        swap_runs = 0
        if ci in RUNS_OF:
            bat_runs = RUNS_OF[ci]
            swap_runs = bat_runs
        elif cls == "W":
            kinds, kcum = model.dismissal_cum[bowler]
            kind = kinds[min(len(kinds) - 1, bisect_right(kcum, rng.random() * kcum[-1]))]
            fielder = None
            if kind == "stumped" and (keeper is None or model.btype(bowler) == "pace"):
                kind = "caught"
            if kind == "caught":
                keeper_p = 0.22 if model.btype(bowler) == "pace" else 0.07
                if keeper and rng.random() < keeper_p:
                    fielder = keeper
                else:
                    pool = [p for p in fielders if p not in (bowler, keeper)] or fielders
                    fielder = pool[int(rng.random() * len(pool))]
            elif kind == "stumped":
                fielder = keeper
            elif kind == "caught and bowled":
                fielder = bowler
            wicket = {"player_out": striker, "kind": kind, "fielder": fielder, "bowler_credited": True}
        elif cls == "RO":
            bat_runs = _pick(model.runout_runs, rng)
            swap_runs = bat_runs
            out_striker = rng.random() < model.runout_striker_p
            pool = [p for p in fielders if p != bowler] or fielders
            wicket = {"player_out": striker if out_striker else non_striker, "kind": "run out",
                      "fielder": pool[int(rng.random() * len(pool))], "bowler_credited": False}
        elif cls == "WD":
            extra_type, legal_ball = "wides", False
            extras_runs = _pick(model.wide_runs, rng)
            swap_runs = extras_runs - 1
        elif cls == "NB":
            extra_type, legal_ball = "noballs", False
            extras_runs = 1
            bat_runs = _pick(model.noball_bat_runs, rng)
            swap_runs = bat_runs
            free_hit = rules.free_hit
        elif cls in ("B", "LB"):
            extra_type = "byes" if cls == "B" else "legbyes"
            extras_runs = _pick(model.bye_runs if cls == "B" else model.legbye_runs, rng)
            swap_runs = extras_runs if extras_runs != 4 else 0
        if cls == "R4" or cls == "R6":
            swap_runs = 0
        if cls == "WD" and extras_runs == 5:
            swap_runs = 0
        if was_free_hit and wicket and wicket["kind"] != "run out":
            wicket = None
        total = bat_runs + extras_runs
        # Book-keeping
        bowl_row = inn.bowl[bowler]
        bat_row = inn.bat.setdefault(striker, [0, 0, 0, 0, 0])
        bat_row[0] += bat_runs
        if cls != "WD":
            bat_row[1] += 1
        if bat_runs == 4 and cls in ("R4", "NB"):
            bat_row[2] += 1
        if bat_runs == 6:
            bat_row[3] += 1
        conceded = bat_runs + (extras_runs if extra_type in ("wides", "noballs") else 0)
        bowl_row[1] += conceded
        if legal_ball:
            bowl_row[0] += 1
            legal += 1
        if extra_type:
            inn.extras[extra_type] += extras_runs
        score += total
        dismissed = None
        if wicket:
            dismissed = wicket["player_out"]
            wkts += 1
            inn.bat.setdefault(dismissed, [0, 0, 0, 0, 0])[4] = 1
            if wicket["bowler_credited"]:
                bowl_row[2] += 1
            if wicket["fielder"] and wicket["kind"] != "caught and bowled":
                inn.field_credits[wicket["fielder"]] = inn.field_credits.get(wicket["fielder"], 0) + 1
            elif wicket["kind"] == "caught and bowled":
                inn.field_credits[bowler] = inn.field_credits.get(bowler, 0) + 1
        if detailed:
            inn.deliveries.append({
                "over_index": over_index, "ball": legal % 6 if legal_ball and legal % 6 else (6 if legal_ball else legal % 6 + 1),
                "batter_id": striker, "non_striker_id": non_striker, "bowler_id": bowler, "outcome": cls,
                "batter_runs": bat_runs, "extras": {extra_type: extras_runs} if extra_type else {},
                "total_runs": total, "legal": legal_ball, "free_hit": was_free_hit, "wicket": wicket,
                "score": score, "wickets": wkts,
            })
        # Strike rotation and incoming batter.
        if swap_runs % 2 == 1:
            striker, non_striker = non_striker, striker
        if dismissed:
            incoming = order[next_idx] if next_idx < len(order) and wkts < max_wickets else None
            next_idx += 1
            if incoming is None and wkts < max_wickets:
                inn.all_out = True  # no batters left
                break
            if incoming:
                inn.bat.setdefault(incoming, [0, 0, 0, 0, 0])
                inn.batting_order_used.append(incoming)
                if wicket["kind"] in BOWLER_WICKET_KINDS:
                    # New batter takes strike after a bowler-credited dismissal (current playing conditions).
                    if dismissed == striker:
                        striker = incoming
                    else:
                        non_striker, striker = striker, incoming
                else:
                    if dismissed == striker:
                        striker = incoming
                    else:
                        non_striker = incoming
        if legal_ball and legal % 6 == 0:
            striker, non_striker = non_striker, striker
            if detailed and not inn.super_over:
                inn.snapshots.append({"score": score, "wickets": wkts, "legal_balls": legal, "striker": striker,
                                      "non_striker": non_striker, "next_index": next_idx,
                                      "overs_bowled": dict(planner.overs_bowled), "last_bowler": bowler,
                                      "loglik": list(loglik) if loglik is not None else None})
    inn.runs, inn.wickets, inn.legal_balls = score, wkts, legal
    inn.final_pair = (striker, non_striker)
    return inn


# ---------------------------------------------------------------------------
# Full match
# ---------------------------------------------------------------------------

def _best_super_over(model: SimModel, team: TeamSetup) -> Tuple[List[str], str]:
    def bat_score(p):
        r = model.bat_ratio[p].get("death|unknown") if model.family != "Test" else None
        r = r or next(iter(model.bat_ratio[p].values()))
        return r[I["R4"]] + 1.5 * r[I["R6"]] - 0.5 * r[I["W"]]
    batters = sorted(team.order, key=lambda p: (-bat_score(p), team.order.index(p)))[:3]
    opts = bowling_options(model, team, rules_for("T20"))
    bowler = max(opts, key=lambda p: model.quality.get(p, 0) * model.usage.get(p, {}).get("death", 1.0))
    return batters, bowler


def toss(model: SimModel, teams: Dict[str, TeamSetup], rng: random.Random, winner: str = "random",
         decision: str = "auto") -> Tuple[str, str]:
    w = winner if winner in teams else ("A" if rng.random() < 0.5 else "B")
    if decision in ("bat", "field"):
        d = decision
    else:
        d = "field" if rng.random() < model.toss_field_p else "bat"
    return w, d


def simulate_match(model: SimModel, rules: FormatRules, teams: Dict[str, TeamSetup], rng: random.Random, *,
                   toss_winner: str = "random", toss_decision: str = "auto", detailed: bool = False,
                   conditions_bin: Optional[int] = None) -> dict:
    """Simulate a full match. Returns innings, result and (optionally) every delivery."""
    tw, td = toss(model, teams, rng, toss_winner, toss_decision)
    # Match conditions are drawn once and shared by every innings of this match.
    zk = conditions_bin if conditions_bin is not None else int(rng.random() * CONDITION_BINS)
    ll = [0.0] * CONDITION_BINS if detailed else None
    other = "B" if tw == "A" else "A"
    first = tw if td == "bat" else other
    second = other if first == tw else tw
    innings: List[InningsResult] = []
    result: Dict[str, object] = {"toss": {"winner": tw, "decision": td}, "batting_first": first, "conditions_bin": zk}
    if rules.limited:
        i1 = play_innings(model, rules, teams[first], teams[second], InningsResult(1, first, second), rng,
                          base_inn=1, later=False, detailed=detailed, zk=zk, loglik=ll)
        innings.append(i1)
        i2 = InningsResult(2, second, first, target=i1.runs + 1)
        play_innings(model, rules, teams[second], teams[first], i2, rng, base_inn=2, later=True, detailed=detailed, zk=zk, loglik=ll)
        innings.append(i2)
        if i2.runs >= i2.target:
            result.update(winner=second, margin_wickets=10 - i2.wickets, balls_remaining=rules.overs * 6 - i2.legal_balls,
                          method="wickets")
        elif i2.runs == i1.runs:
            result.update(winner=None, tie=True, method="tie")
            if rules.super_over:
                so_rounds = []
                bat_first, bat_second = second, first
                for _ in range(5):
                    a_bat, a_bowl = _best_super_over(model, teams[bat_first])[0], _best_super_over(model, teams[bat_second])[1]
                    so1 = play_innings(model, rules, teams[bat_first], teams[bat_second],
                                       InningsResult(len(innings) + 1, bat_first, bat_second, super_over=True), rng,
                                       base_inn=1, later=True, detailed=detailed, zk=zk, loglik=ll, max_balls=6, max_wickets=2,
                                       order=a_bat, forced_bowler=a_bowl, start={"legal_balls": 0},
                                       bowlers=[a_bowl])
                    b_bat, b_bowl = _best_super_over(model, teams[bat_second])[0], _best_super_over(model, teams[bat_first])[1]
                    so2 = InningsResult(len(innings) + 2, bat_second, bat_first, target=so1.runs + 1, super_over=True)
                    play_innings(model, rules, teams[bat_second], teams[bat_first], so2, rng, base_inn=2, later=True,
                                 detailed=detailed, zk=zk, loglik=ll, max_balls=6, max_wickets=2, order=b_bat, forced_bowler=b_bowl,
                                 bowlers=[b_bowl])
                    _shift_super_over(so1, rules)
                    _shift_super_over(so2, rules)
                    innings.extend([so1, so2])
                    so_rounds.append((so1.runs, so2.runs))
                    if so2.runs != so1.runs:
                        result["winner"] = bat_second if so2.runs > so1.runs else bat_first
                        result["method"] = "super over"
                        break
                    bat_first, bat_second = bat_second, bat_first
                result["super_overs"] = so_rounds
        else:
            result.update(winner=first, margin_runs=i1.runs - i2.runs, method="runs")
    else:
        _simulate_test(model, rules, teams, first, second, innings, result, rng, detailed, zk, ll)
    result["innings"] = innings
    return result


def _shift_super_over(inn: InningsResult, rules: FormatRules) -> None:
    for d in inn.deliveries:
        d["super_over"] = True


def _simulate_test(model, rules, teams, first, second, innings, result, rng, detailed, zk=MID_BIN, ll=None):
    overs_left = rules.match_overs

    def run(num, bat, bowl, target=None, declare_fn=None, follow_on=False, base_inn=None):
        nonlocal overs_left
        inn = InningsResult(num, bat, bowl, target=target, follow_on=follow_on)
        play_innings(model, rules, teams[bat], teams[bowl], inn, rng, base_inn=base_inn or num, later=num >= 3,
                     detailed=detailed, zk=zk, loglik=ll, overs_left_in_match=overs_left, declare_fn=declare_fn,
                     survival_target=target is not None)
        used = math.ceil(inn.legal_balls / 6)
        overs_left = max(0, overs_left - used - 2)  # two overs lost per change of innings
        innings.append(inn)
        return inn

    def first_innings_declare(score, wkts, over):
        return (score >= 650) or (score >= 550 and wkts >= 5) or (over >= 170 and score >= 450)

    i1 = run(1, first, second, declare_fn=first_innings_declare)
    if overs_left <= 0:
        result.update(winner=None, method="draw")
        return
    i2 = run(2, second, first, declare_fn=lambda s, w, o: s >= i1.runs + 250 and w >= 5)
    lead = i1.runs - i2.runs
    if overs_left <= 0:
        result.update(winner=None, method="draw")
        return
    follow_on = lead >= rules.follow_on and (lead >= 250 or rng.random() < 0.6) and overs_left > 100
    if follow_on:
        i3 = run(3, second, first, follow_on=True)
        deficit_after = i1.runs - (i2.runs + i3.runs)
        if i3.all_out and deficit_after > 0:
            result.update(winner=first, margin_runs=deficit_after, method="innings")
            return
        if overs_left <= 0 or not i3.all_out:
            result.update(winner=None, method="draw")
            return
        target = i2.runs + i3.runs - i1.runs + 1
        i4 = run(4, first, second, target=target)
        _test_finish(result, i4, target, first, second, i2.runs + i3.runs, i1.runs)
        return

    def third_declare(score, wkts, over):
        lead_now = lead + score
        remaining = overs_left - over
        return remaining >= 40 and lead_now >= max(200, 4 * remaining - 120)

    i3 = run(3, first, second, declare_fn=third_declare)
    total_first = i1.runs + i3.runs
    if lead < 0 and i3.all_out and total_first < i2.runs:
        result.update(winner=second, margin_runs=i2.runs - total_first, method="innings")
        return
    if overs_left <= 0:
        result.update(winner=None, method="draw")
        return
    target = total_first - i2.runs + 1
    i4 = run(4, second, first, target=target)
    _test_finish(result, i4, target, second, first, total_first, i2.runs)


def _test_finish(result, i4, target, chasing, defending, defending_total, chasing_prior):
    if i4.runs >= target:
        result.update(winner=chasing, margin_wickets=10 - i4.wickets, method="wickets")
    elif i4.all_out:
        if chasing_prior + i4.runs == defending_total:
            result.update(winner=None, tie=True, method="tie")
        else:
            result.update(winner=defending, margin_runs=target - 1 - i4.runs, method="runs")
    else:
        result.update(winner=None, method="draw")


# ---------------------------------------------------------------------------
# Summaries, scorecards and impact
# ---------------------------------------------------------------------------

def result_text(result: dict, teams: Dict[str, TeamSetup]) -> str:
    w = result.get("winner")
    method = result.get("method")
    if method == "draw":
        return "Match drawn"
    if w is None:
        return "Match tied"
    name = teams[w].name
    if method == "runs":
        return f"{name} won by {result['margin_runs']} runs"
    if method == "wickets":
        extra = ""
        if result.get("balls_remaining"):
            extra = f" ({result['balls_remaining']} balls left)"
        n = result["margin_wickets"]
        return f"{name} won by {n} wicket{'s' if n != 1 else ''}{extra}"
    if method == "innings":
        return f"{name} won by an innings and {result['margin_runs']} runs"
    if method == "super over":
        return f"Match tied; {name} won the super over"
    return f"{name} won"


def player_match_lines(result: dict) -> Dict[str, dict]:
    """Aggregate per-player lines across the main innings (super overs excluded)."""
    lines: Dict[str, dict] = {}

    def line(pid):
        return lines.setdefault(pid, {"runs": 0, "balls": 0, "fours": 0, "sixes": 0, "outs": 0, "innings": 0,
                                      "wickets": 0, "conceded": 0, "bowled": 0, "field": 0})
    for inn in result["innings"]:
        if inn.super_over:
            continue
        for pid, (r, b, f4, s6, out) in inn.bat.items():
            ln = line(pid)
            ln["runs"] += r
            ln["balls"] += b
            ln["fours"] += f4
            ln["sixes"] += s6
            ln["outs"] += out
            ln["innings"] += 1
        for pid, (balls, conc, w) in inn.bowl.items():
            ln = line(pid)
            ln["bowled"] += balls
            ln["conceded"] += conc
            ln["wickets"] += w
        for pid, n in inn.field_credits.items():
            line(pid)["field"] += n
    return lines


def impact_scores(result: dict, rules: FormatRules, teams: Dict[str, TeamSetup]) -> Dict[str, float]:
    """Simple, transparent match impact: runs and tempo, wickets and economy, fielding."""
    main = [i for i in result["innings"] if not i.super_over]
    runs = sum(i.runs for i in main)
    balls = sum(i.legal_balls for i in main) or 1
    rpb = runs / balls
    wicket_value = 20.0 if rules.limited else 25.0
    tempo = 0.5 if rules.limited else 0.1
    scores: Dict[str, float] = {}
    for pid, ln in player_match_lines(result).items():
        bat = ln["runs"] + tempo * (ln["runs"] - ln["balls"] * rpb)
        bowl = wicket_value * ln["wickets"] + (tempo * 2) * (ln["bowled"] * rpb - ln["conceded"])
        scores[pid] = round(bat + bowl + 8.0 * ln["field"], 2)
    return scores


def player_team(teams: Dict[str, TeamSetup]) -> Dict[str, str]:
    return {pid: key for key, t in teams.items() for pid in t.order}


def player_of_match(result: dict, rules: FormatRules, teams: Dict[str, TeamSetup], scores=None) -> Optional[str]:
    scores = scores if scores is not None else impact_scores(result, rules, teams)
    if not scores:
        return None
    owner = player_team(teams)
    winner = result.get("winner")
    def adj(pid):
        s = scores[pid]
        return s if winner is None or owner.get(pid) == winner else s * 0.75
    return max(scores, key=adj)


def summarise(result: dict, rules: FormatRules, teams: Dict[str, TeamSetup]) -> dict:
    """Compact per-simulation record used by Monte Carlo aggregation."""
    main = [i for i in result["innings"] if not i.super_over]
    scores = impact_scores(result, rules, teams)
    lines = player_match_lines(result)
    return {
        "winner": result.get("winner"), "tie": bool(result.get("tie")), "method": result.get("method"),
        "super_over": any(i.super_over for i in result["innings"]),
        "toss": result["toss"], "batting_first": result["batting_first"],
        "margin_runs": result.get("margin_runs"), "margin_wickets": result.get("margin_wickets"),
        "innings": [(i.batting, i.runs, i.wickets, i.legal_balls, i.declared) for i in main],
        "players": {pid: (ln["runs"], ln["balls"], ln["outs"], ln["wickets"], ln["conceded"], ln["bowled"], ln["field"],
                          scores.get(pid, 0.0)) for pid, ln in lines.items()},
        "potm": player_of_match(result, rules, teams, scores),
    }


def run_batch(model: SimModel, rules: FormatRules, teams: Dict[str, TeamSetup], seed: int, start: int, count: int,
              toss_winner: str = "random", toss_decision: str = "auto") -> List[dict]:
    """Simulate matches ``start..start+count-1``; each uses its own seed so batches are order-independent."""
    out = []
    for i in range(start, start + count):
        rng = random.Random(f"{seed}:{i}")
        res = simulate_match(model, rules, teams, rng, toss_winner=toss_winner, toss_decision=toss_decision)
        out.append(summarise(res, rules, teams))
    return out


def condition_posterior(loglik: Optional[List[float]]) -> List[float]:
    """Posterior over the conditions bins given per-bin log-likelihoods (equal prior)."""
    if not loglik:
        return [1.0 / CONDITION_BINS] * CONDITION_BINS
    top = max(loglik)
    w = [math.exp(x - top) for x in loglik]
    total = sum(w)
    return [x / total for x in w]


def jeffreys_interval(wins: float, n: int, level: float = 0.95) -> Tuple[float, float]:
    """Equal-tailed Jeffreys interval, Beta(wins + 1/2, n - wins + 1/2)."""
    try:
        from scipy.stats import beta
        lo = 0.0 if wins <= 0 else float(beta.ppf((1 - level) / 2, wins + 0.5, n - wins + 0.5))
        hi = 1.0 if wins >= n else float(beta.ppf(1 - (1 - level) / 2, wins + 0.5, n - wins + 0.5))
        return lo, hi
    except Exception:  # pragma: no cover - scipy is a scikit-learn dependency
        p = (wins + 0.5) / (n + 1)
        half = 1.96 * math.sqrt(p * (1 - p) / (n + 1))
        return max(0.0, p - half), min(1.0, p + half)


def outcome_from_state(model: SimModel, rules: FormatRules, teams: Dict[str, TeamSetup], innings_index: int,
                       first: InningsResult, inn: InningsResult, snap: dict, rng: random.Random, zk: int) -> Tuple[float, float]:
    """Play out a limited-overs match from an over-end state. Returns (team A share, tie share)."""
    start = dict(snap)
    start.pop("loglik", None)
    if innings_index == 0:
        i1 = InningsResult(1, first.batting, first.bowling)
        play_innings(model, rules, teams[first.batting], teams[first.bowling], i1, rng, base_inn=1, later=False,
                     detailed=False, start=start, zk=zk)
        i2 = InningsResult(2, first.bowling, first.batting, target=i1.runs + 1)
        play_innings(model, rules, teams[first.bowling], teams[first.batting], i2, rng, base_inn=2, later=True, detailed=False, zk=zk)
        r1, r2, chasing = i1.runs, i2.runs, first.bowling
    else:
        i2 = InningsResult(2, inn.batting, inn.bowling, target=inn.target)
        play_innings(model, rules, teams[inn.batting], teams[inn.bowling], i2, rng, base_inn=2, later=True,
                     detailed=False, start=start, zk=zk)
        r1, r2, chasing = inn.target - 1, i2.runs, inn.batting
    if r2 == r1:
        return 0.5, 1.0
    chase_won = r2 > r1
    a_won = chase_won if chasing == "A" else not chase_won
    return (1.0 if a_won else 0.0), 0.0


def _terminal(rules: FormatRules, innings_index: int, inn: InningsResult, snap: dict) -> Optional[float]:
    """Exact Team-A probability when the state already decides the match, else None."""
    if innings_index != 1:
        return None
    target = inn.target
    a_chasing = inn.batting == "A"
    if snap["score"] >= target:
        return 1.0 if a_chasing else 0.0
    if snap["wickets"] >= 10 or snap["legal_balls"] >= rules.overs * 6:
        if snap["score"] == target - 1:
            return 0.5  # tie: decided by a super over (or shared)
        return 0.0 if a_chasing else 1.0
    return None


def win_probability_path(model: SimModel, rules: FormatRules, teams: Dict[str, TeamSetup], result: dict,
                         sims: int = 1000, seed: int = 0, step: int = 1, progress=None) -> List[dict]:
    """Team-A win probability after each over, by re-simulating the rest of the match from that state.

    * The probability always refers to Team A (``teams['A']``), whichever side is batting.
    * Match conditions are unknown to an observer, so each re-simulation draws them from
      the posterior given every ball bowled so far (equal prior at the start).
    * Estimates are Jeffreys posterior means (wins + 1/2) / (n + 1) with a 95% Jeffreys
      interval; a tie counts half. States that already decide the match are exact.
    Limited overs only.
    """
    main = [i for i in result["innings"] if not i.super_over]
    if not rules.limited or not main:
        return []
    points = []
    first = main[0]
    total_points = sum(len(i.snapshots) for i in main[:2]) or 1
    seen_points = 0
    for idx, inn in enumerate(main[:2]):
        snaps = inn.snapshots
        for k, snap in enumerate(snaps):
            over = snap["legal_balls"] // 6
            seen_points += 1
            if progress:
                progress(seen_points / total_points)
            if over % step and k != len(snaps) - 1:
                continue
            if idx == 1 and k == 0 and points:
                continue  # identical to the end of the first innings
            post = condition_posterior(snap.get("loglik"))
            exact = _terminal(rules, idx, inn, snap)
            point = {"innings": inn.number, "batting": inn.batting, "over": over, "score": snap["score"],
                     "wickets": snap["wickets"], "label": "start" if snap["legal_balls"] == 0 and idx == 0 else "over",
                     "target": inn.target, "balls_left": rules.overs * 6 - snap["legal_balls"],
                     "conditions_posterior_mean_z": round(sum(w * z for w, z in zip(post, CONDITION_Z)), 3)}
            if exact is not None:
                point.update(team_a=exact, team_b=round(1 - exact, 4), draw_or_tie=1.0 if exact == 0.5 else 0.0,
                             ci_low=exact, ci_high=exact, simulations=0, exact=True)
                points.append(point)
                continue
            cum_post = _cum(post)
            a = tie = 0.0
            for j in range(sims):
                rng = random.Random(f"{seed}:wp:{j}")  # common random numbers across points
                zk = min(CONDITION_BINS - 1, bisect_right(cum_post, rng.random() * cum_post[-1]))
                share, t = outcome_from_state(model, rules, teams, idx, first, inn, snap, rng, zk)
                a += share
                tie += t
            p_a = (a + 0.5) / (sims + 1)
            lo, hi = jeffreys_interval(a, sims)
            point.update(team_a=round(p_a, 4), team_b=round(1 - p_a, 4), draw_or_tie=round(tie / sims, 4),
                         ci_low=round(lo, 4), ci_high=round(hi, 4), simulations=sims, exact=False,
                         raw_team_a=round(a / sims, 4))
            points.append(point)
    return points


def fit_condition_scale(calibration: dict, family: str, gender: str, sims: int = 1500,
                        grid=(0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0)) -> Optional[dict]:
    """Choose the latent-conditions scale so simulated innings correlate like real ones.

    Simulates neutral (league-average) XIs for the first ``overs`` of both innings and
    matches the correlation of log run rates to the value measured in CPI matches.
    """
    from app.ml.sim_calibration import CONDITION_OVERS
    block = calibration["genders"].get(gender) or {}
    cond = block.get("conditions")
    if not cond:
        return None
    target = cond["rho"]
    k = CONDITION_OVERS[family]
    rules = rules_for({"T20": "T20", "ODI": "ODI", "Test": "Test"}[family])
    if rules.family == "Test":
        rules = FormatRules("Test", "Test", None, None, 4, False, False, match_overs=450)
    a = [f"na{i}" for i in range(11)]
    b = [f"nb{i}" for i in range(11)]
    positions = {p: i + 1 for i, p in enumerate(a)}
    positions.update({p: i + 1 for i, p in enumerate(b)})
    teams = {"A": TeamSetup("A", "A", a, bowling_options=a[5:]), "B": TeamSetup("B", "B", b, bowling_options=b[5:])}
    curve = []
    for scale in grid:
        model = SimModel(calibration, family, gender, {}, {}, positions=positions, condition_scale=scale, bowler_priors=False)
        x1, x2 = [], []
        for j in range(sims):
            rng = random.Random(f"fit:{j}")
            zk = int(rng.random() * CONDITION_BINS)
            lim = FormatRules(rules.fmt, rules.family, k, max(1, math.ceil(k / 5)), 2, rules.free_hit, False)
            i1 = play_innings(model, lim, teams["A"], teams["B"], InningsResult(1, "A", "B"), rng, base_inn=1, later=False, detailed=False, zk=zk)
            i2 = play_innings(model, lim, teams["B"], teams["A"], InningsResult(2, "B", "A"), rng, base_inn=2, later=True, detailed=False, zk=zk)
            if i1.legal_balls >= k * 6 and i2.legal_balls >= k * 6:
                x1.append(math.log(max(1, i1.runs) / i1.legal_balls))
                x2.append(math.log(max(1, i2.runs) / i2.legal_balls))
        n = len(x1)
        m1, m2 = sum(x1) / n, sum(x2) / n
        v1 = sum((x - m1) ** 2 for x in x1) / n
        v2 = sum((x - m2) ** 2 for x in x2) / n
        rho = sum((p - m1) * (q - m2) for p, q in zip(x1, x2)) / n / math.sqrt(v1 * v2)
        curve.append((scale, rho))
    chosen = curve[-1][0]
    for (s0, r0), (s1, r1) in zip(curve, curve[1:]):
        if r0 <= target <= r1 and r1 > r0:
            chosen = s0 + (target - r0) * (s1 - s0) / (r1 - r0)
            break
    else:
        if target <= curve[0][1]:
            chosen = 0.0
    return {"scale": round(chosen, 4), "rho_target": target, "fit_curve": [[round(x, 2), round(y, 4)] for x, y in curve]}


def _hist(values, width):
    bins = defaultdict(int)
    for v in values:
        bins[int(v // width * width)] += 1
    return [{"start": k, "end": k + width - 1, "count": c} for k, c in sorted(bins.items())]


def _mean(xs):
    return round(sum(xs) / len(xs), 2) if xs else None


def _pct(xs, q):
    if not xs:
        return None
    s = sorted(xs)
    return s[min(len(s) - 1, int(q * (len(s) - 1) + 0.5))]


def aggregate_monte_carlo(summaries: List[dict], teams: Dict[str, TeamSetup], rules: FormatRules,
                          names: Optional[Dict[str, str]] = None) -> dict:
    """Aggregate Monte Carlo outcomes. Every figure is computed from the simulated matches."""
    n = len(summaries)
    if n == 0:
        raise ValueError("No simulations to aggregate")
    names = names or {}
    owner = player_team(teams)
    wins = {k: sum(1 for s in summaries if s["winner"] == k) for k in teams}
    ties = sum(1 for s in summaries if s["tie"])
    draws = sum(1 for s in summaries if s["method"] == "draw")
    first_scores = [s["innings"][0][1] for s in summaries if s["innings"]]
    first_by_team = {k: [s["innings"][0][1] for s in summaries if s["innings"] and s["innings"][0][0] == k] for k in teams}
    chases = [s for s in summaries if rules.limited and len(s["innings"]) >= 2]
    successful = [s["innings"][1][1] for s in chases if s["winner"] == s["innings"][1][0] and s["method"] == "wickets"]
    failed = [s["innings"][1][1] for s in chases if s["winner"] == s["innings"][0][0]]
    wickets_lost = {k: [] for k in teams}
    totals = {k: [] for k in teams}
    for s in summaries:
        for (bat, runs, wk, balls, _dec) in s["innings"]:
            wickets_lost[bat].append(wk)
            totals[bat].append(runs)
    toss_won_match = sum(1 for s in summaries if s["winner"] is not None and s["winner"] == s["toss"]["winner"])
    decided = sum(1 for s in summaries if s["winner"] is not None)
    bat_first_wins = sum(1 for s in summaries if s["winner"] is not None and s["winner"] == s["batting_first"])
    # Player influence: average impact, and the win-rate gap between their good and poor games.
    per_player: Dict[str, dict] = {}
    for s in summaries:
        for pid, (r, b, outs, w, conc, bowled, fld, imp) in s["players"].items():
            pp = per_player.setdefault(pid, {"impact": [], "won": [], "runs": 0, "balls": 0, "outs": 0, "wickets": 0,
                                             "conceded": 0, "bowled": 0, "field": 0, "potm": 0, "fifties": 0})
            pp["impact"].append(imp)
            pp["won"].append(1 if s["winner"] == owner.get(pid) else 0)
            pp["runs"] += r
            pp["balls"] += b
            pp["outs"] += outs
            pp["wickets"] += w
            pp["conceded"] += conc
            pp["bowled"] += bowled
            pp["field"] += fld
            pp["fifties"] += 1 if r >= 50 else 0
        if s["potm"] in per_player:
            per_player[s["potm"]]["potm"] += 1
        elif s["potm"]:
            per_player.setdefault(s["potm"], {"impact": [], "won": [], "runs": 0, "balls": 0, "outs": 0, "wickets": 0,
                                              "conceded": 0, "bowled": 0, "field": 0, "potm": 1, "fifties": 0})
    players = []
    for pid, pp in per_player.items():
        k = len(pp["impact"])
        if k == 0:
            continue
        mean_imp = sum(pp["impact"]) / k
        # Point-biserial correlation between impact and the team winning.
        mw = sum(pp["won"]) / k
        var_i = sum((x - mean_imp) ** 2 for x in pp["impact"]) / k
        var_w = mw * (1 - mw)
        cov = sum((x - mean_imp) * (y - mw) for x, y in zip(pp["impact"], pp["won"])) / k
        corr = cov / math.sqrt(var_i * var_w) if var_i > 0 and var_w > 0 else 0.0
        hi = [y for x, y in zip(pp["impact"], pp["won"]) if x >= mean_imp]
        lo = [y for x, y in zip(pp["impact"], pp["won"]) if x < mean_imp]
        players.append({
            "player_id": pid, "name": names.get(pid, pid), "team": owner.get(pid),
            "appearances": k, "avg_impact": round(mean_imp, 2), "win_correlation": round(corr, 3),
            "win_rate_when_above_avg": round(sum(hi) / len(hi), 4) if hi else None,
            "win_rate_when_below_avg": round(sum(lo) / len(lo), 4) if lo else None,
            "potm_pct": round(100 * pp["potm"] / n, 2),
            "avg_runs": round(pp["runs"] / n, 2), "batting_average": round(pp["runs"] / pp["outs"], 2) if pp["outs"] else None,
            "strike_rate": round(100 * pp["runs"] / pp["balls"], 2) if pp["balls"] else None,
            "fifty_plus_pct": round(100 * pp["fifties"] / n, 2),
            "avg_wickets": round(pp["wickets"] / n, 3),
            "economy": round(6 * pp["conceded"] / pp["bowled"], 2) if pp["bowled"] else None,
            "influence": round(mean_imp * max(0.0, corr), 2),
        })
    players.sort(key=lambda p: (-p["influence"], -p["avg_impact"]))
    margins_runs = [s["margin_runs"] for s in summaries if s["method"] in ("runs", "innings") and s["margin_runs"] is not None]
    margins_wkts = [s["margin_wickets"] for s in summaries if s["method"] == "wickets" and s["margin_wickets"] is not None]
    width = 10 if rules.family != "Test" else 25
    return {
        "simulations": n,
        "win_pct": {k: round(100 * wins[k] / n, 2) for k in teams},
        "tie_pct": round(100 * ties / n, 2),
        "draw_pct": round(100 * draws / n, 2),
        "super_over_pct": round(100 * sum(1 for s in summaries if s["super_over"]) / n, 2),
        "avg_first_innings": _mean(first_scores),
        "first_innings_p10_p90": [_pct(first_scores, 0.1), _pct(first_scores, 0.9)],
        "avg_first_innings_by_team": {k: _mean(v) for k, v in first_by_team.items()},
        "avg_successful_chase": _mean(successful),
        "successful_chases": len(successful),
        "avg_failed_chase": _mean(failed),
        "chase_success_pct": round(100 * len(successful) / len(chases), 2) if chases else None,
        "avg_wickets_lost": {k: _mean(v) for k, v in wickets_lost.items()},
        "avg_innings_total": {k: _mean(v) for k, v in totals.items()},
        "toss_winner_win_pct": round(100 * toss_won_match / decided, 2) if decided else None,
        "bat_first_win_pct": round(100 * bat_first_wins / decided, 2) if decided else None,
        "distributions": {
            "first_innings": _hist(first_scores, width),
            "team_totals": {k: _hist(v, width) for k, v in totals.items()},
            "wickets_lost": {k: [{"wickets": w, "count": sum(1 for x in v if x == w)} for w in range(11)] for k, v in wickets_lost.items()},
            "margin_runs": _hist(margins_runs, 10 if rules.family != "Test" else 25),
            "margin_wickets": [{"wickets": w, "count": sum(1 for x in margins_wkts if x == w)} for w in range(1, 11)],
        },
        "influential_players": players[:12],
        "all_players": players,
    }
