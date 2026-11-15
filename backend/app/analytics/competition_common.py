"""Shared scope, loading, classification and statistics for Team and Venue Analytics.

Everything is computed from stored matches plus the persisted per-innings team
totals (``team_innings_summary``) and per-bowler innings (``scouting_bowl_innings``).
Nothing is imputed: undefined ratios are ``None`` and every aggregate carries
its sample size.

Result handling
    ``result_type`` is authoritative: ``no result`` (abandoned), ``tie`` and
    ``draw`` are never counted as wins or losses. Super-over innings are
    excluded from every scoring metric; a tie decided by a super over remains a
    tie (Cricsheet records the eliminator separately and it is not stored).
    Win % is wins / (wins + losses).

Complete innings
    Score averages, medians, distributions and lowest totals use *complete*
    innings only: the match produced a result (not a no-result) and, in
    limited-overs cricket, was not reduced (no ``target_overs`` below the full
    quota). Results (W/L, toss, batting first/chasing) still use every match.

Home / away
    No home team is stored, so it is derived only from evidence:
    1. ``verified_country`` - a side whose country is verified with high
       confidence (national teams) is at home when the venue is in that country
       and away when the venue is in the opponent's verified country.
    2. ``fixture_concentration`` - in a tournament season, a venue is a side's
       home ground when it played at least 2 matches there and at least twice as
       many as any other side (e.g. IPL: 7 vs 1). The other side is away; a match
       in a home-and-away season at nobody's home ground is neutral.
    Otherwise the match is ``unclassified`` and kept out of home/away splits.
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, asdict
from statistics import median
from threading import Lock
from typing import Any, Dict, Iterable, List, Optional, Sequence

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.analytics.insights import FORMAT_INNINGS_BALLS

LIMITED = ("T20", "T20I", "ODI", "ODM")
FORMATS = ("T20", "T20I", "ODI", "ODM", "Test", "MDM")
PHASES = ("pp", "mid", "death")
PHASE_NAMES = {"pp": "powerplay", "mid": "middle", "death": "death"}
# Close-match thresholds: (max run margin, max balls remaining in a won chase).
CLOSE_THRESHOLDS = {"T20": (10, 6), "T20I": (10, 6), "ODI": (20, 12), "ODM": (20, 12)}
MIN_SAMPLE = 10  # below this, percentages are shown but never turned into insights

# Venue countries spelled differently from team countries. England play home
# matches in Wales (one board: ECB).
_COUNTRY_ALIASES = {"usa": "united states of america", "united states": "united states of america",
                    "uae": "united arab emirates", "wales": "england"}


def norm_country(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    v = value.strip().casefold()
    return _COUNTRY_ALIASES.get(v, v)


# --------------------------------------------------------------------- statistics

def pct(n, d, digits=1) -> Optional[float]:
    return round(100.0 * n / d, digits) if d else None


def avg(values: Sequence[float], digits=1) -> Optional[float]:
    vals = [v for v in values if v is not None]
    return round(sum(vals) / len(vals), digits) if vals else None


def med(values: Sequence[float]) -> Optional[float]:
    vals = [v for v in values if v is not None]
    return float(median(vals)) if vals else None


def rate(runs, balls, digits=2) -> Optional[float]:
    """Runs per over."""
    return round(runs * 6.0 / balls, digits) if balls else None


def div(n, d, digits=2) -> Optional[float]:
    return round(n / d, digits) if d else None


def wilson(k: int, n: int, z: float = 1.96):
    """95% Wilson score interval for a proportion, in percent."""
    if not n:
        return None
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return [round(100 * max(0.0, centre - half), 1), round(100 * min(1.0, centre + half), 1)]


def binomial_p(k: int, n: int) -> Optional[float]:
    """Exact two-sided binomial test against p = 0.5."""
    if not n:
        return None
    if n > 1000:  # normal approximation keeps this cheap for very large samples
        z = abs(k - n / 2) / math.sqrt(n / 4)
        return round(math.erfc(z / math.sqrt(2)), 4)
    probs = [math.comb(n, i) for i in range(n + 1)]
    total = 2 ** n
    observed = probs[k]
    p = sum(x for x in probs if x <= observed) / total
    return round(min(1.0, p), 4)


def two_proportion_p(k1: int, n1: int, k2: int, n2: int) -> Optional[float]:
    """Two-sided z-test p-value for a difference between two proportions."""
    if not n1 or not n2:
        return None
    pooled = (k1 + k2) / (n1 + n2)
    se = math.sqrt(pooled * (1 - pooled) * (1 / n1 + 1 / n2))
    if se == 0:
        return 1.0
    z = abs(k1 / n1 - k2 / n2) / se
    return round(math.erfc(z / math.sqrt(2)), 4)


def fmt_p(p: Optional[float]) -> str:
    if p is None:
        return "p n/a"
    return "p<0.001" if p < 0.001 else f"p={p:.3f}"


def histogram(values: Iterable[float], width: float, start: Optional[float] = None) -> List[dict]:
    vals = [v for v in values if v is not None]
    if not vals:
        return []
    lo = start if start is not None else math.floor(min(vals) / width) * width
    out, edge = [], lo
    while edge <= max(vals):
        out.append({"bin_start": edge, "label": f"{int(edge)}–{int(edge + width - 1)}" if width > 1 else str(int(edge)),
                    "count": sum(1 for v in vals if edge <= v < edge + width)})
        edge += width
    return out


def score_bin_width(fmt: str) -> int:
    return 20 if fmt in ("T20", "T20I") else 25 if fmt in ("ODI", "ODM") else 50


def proportion(k: int, n: int) -> dict:
    """A percentage with its sample, interval and a sample-quality flag."""
    return {"value": pct(k, n), "k": k, "n": n, "ci95": wilson(k, n),
            "sample": "none" if not n else "low" if n < MIN_SAMPLE else "limited" if n < 30 else "ok"}


# ------------------------------------------------------------------------- scope

@dataclass(frozen=True)
class Scope:
    format: str = "T20"
    gender: Optional[str] = None
    competition: Optional[str] = None
    season: Optional[str] = None
    start_year: Optional[int] = None
    end_year: Optional[int] = None

    def key(self) -> tuple:
        return tuple(asdict(self).values())

    def where(self, params: dict, alias: str = "m") -> str:
        if self.format not in FORMATS:
            raise ValueError(f"format must be one of {', '.join(FORMATS)}")
        if self.start_year and self.end_year and self.start_year > self.end_year:
            raise ValueError("start_year must be on or before end_year")
        conds = [f"{alias}.match_format = :fmt"]
        params["fmt"] = self.format
        if self.gender and self.gender.lower() != "all":
            conds.append(f"lower({alias}.gender) = :gender"); params["gender"] = self.gender.lower()
        if self.competition:
            conds.append(f"{alias}.tournament_id IN (SELECT id FROM tournaments WHERE name ILIKE :competition)")
            params["competition"] = f"%{self.competition}%"
        if self.season:
            conds.append(f"{alias}.season = :season"); params["season"] = self.season
        if self.start_year:
            conds.append(f"{alias}.start_date >= :start_date"); params["start_date"] = f"{int(self.start_year)}-01-01"
        if self.end_year:
            conds.append(f"{alias}.start_date <= :end_date"); params["end_date"] = f"{int(self.end_year)}-12-31"
        return " AND ".join(conds)

    @property
    def limited(self) -> bool:
        return self.format in LIMITED

    @property
    def quota(self) -> Optional[int]:
        return FORMAT_INNINGS_BALLS.get(self.format)


# ------------------------------------------------------------------------- caches

_CACHE: Dict[tuple, Any] = {}
_LOCK = Lock()
_MAX = 96


def cached(key: tuple, build):
    with _LOCK:
        if key in _CACHE:
            return _CACHE[key]
    value = build()
    with _LOCK:
        if len(_CACHE) >= _MAX:
            _CACHE.pop(next(iter(_CACHE)))
        _CACHE[key] = value
    return value


def clear_cache() -> None:
    with _LOCK:
        _CACHE.clear()


# ------------------------------------------------------------------------ loading

_MATCH_SQL = """
SELECT m.id, m.start_date, m.season, m.match_format, lower(m.gender) AS gender, m.tournament_id,
       tr.name AS competition, m.venue_id, v.canonical_name AS venue, v.city, v.country AS venue_country,
       m.team1_id, m.team2_id, t1.canonical_name AS team1, t2.canonical_name AS team2,
       CASE WHEN t1.country_confidence = 'high' THEN t1.country END AS team1_country,
       CASE WHEN t2.country_confidence = 'high' THEN t2.country END AS team2_country,
       m.toss_winner_id, lower(m.toss_decision) AS toss_decision, m.winner_id,
       lower(coalesce(m.result_type, '')) AS result_type, m.result_margin_runs, m.result_margin_wickets,
       EXISTS (SELECT 1 FROM match_innings so WHERE so.match_id = m.id AND so.is_super_over) AS has_super_over
FROM matches m
LEFT JOIN tournaments tr ON tr.id = m.tournament_id
LEFT JOIN venues v ON v.id = m.venue_id
LEFT JOIN teams t1 ON t1.id = m.team1_id
LEFT JOIN teams t2 ON t2.id = m.team2_id
WHERE {where}
ORDER BY m.start_date, m.id
"""

_INNINGS_COLS = ("innings_id, match_id, innings_number, batting_team_id, bowling_team_id, target_runs, target_overs, "
                 "runs, legal_balls, wickets, fours, sixes, dots, extras, "
                 "pp_runs, pp_balls, pp_wkts, pp_bnd, mid_runs, mid_balls, mid_wkts, mid_bnd, "
                 "death_runs, death_balls, death_wkts, death_bnd")


def require_summary_table(db: Session) -> None:
    if not db.execute(text("SELECT to_regclass('public.team_innings_summary') IS NOT NULL")).scalar():
        raise RuntimeError("team_innings_summary is missing: run `alembic upgrade head` and "
                           "scripts/build_team_innings_summary.py")


def load_matches(db: Session, scope: Scope, extra: str = "", params: Optional[dict] = None) -> List[dict]:
    params = dict(params or {})
    where = scope.where(params) + (f" AND {extra}" if extra else "")
    rows = [dict(r._mapping) for r in db.execute(text(_MATCH_SQL.format(where=where)), params)]
    if not rows:
        return rows
    innings = defaultdict(list)
    for r in db.execute(text(f"SELECT {_INNINGS_COLS} FROM team_innings_summary WHERE match_id = ANY(:ids)"),
                        {"ids": [m["id"] for m in rows]}):
        innings[r.match_id].append(dict(r._mapping))
    for m in rows:
        m["innings"] = sorted(innings.get(m["id"], []), key=lambda i: i["innings_number"])
        annotate_match(m, scope)
    return rows


def annotate_match(m: dict, scope: Scope) -> None:
    """Derive result, batting order, chase and completeness facts for one match (in place)."""
    rt = m["result_type"]
    m["outcome"] = ("no_result" if rt in ("no result", "abandoned") else "tie" if rt in ("tie", "tied")
                    else "draw" if rt == "draw" else "decided" if m["winner_id"] else "unknown")
    inns = m["innings"]
    first = next((i for i in inns if i["innings_number"] == 1), None)
    second = next((i for i in inns if i["innings_number"] == 2), None)
    m["first_batting_id"] = first["batting_team_id"] if first else None
    m["first_innings"], m["second_innings"] = first, second
    quota = scope.quota
    reduced = bool(quota and any(i["target_overs"] and i["target_overs"] * 6 < quota for i in inns))
    m["reduced"] = reduced
    m["complete"] = m["outcome"] != "no_result" and not reduced
    for i in inns:
        i["complete"] = m["complete"]
        i["all_out"] = i["wickets"] >= 10
        # A total is "completed" (eligible for lowest-total records) when the side was bowled out or,
        # in limited-overs cricket, batted its full quota; a won chase is never a lowest total.
        i["finished"] = m["complete"] and (i["all_out"] or bool(quota and i["legal_balls"] >= quota))
    # Chase facts (limited overs only).
    m["chase"] = None
    if scope.limited and first and second and m["outcome"] in ("decided", "tie"):
        target = second["target_runs"] or first["runs"] + 1
        quota_balls = (second["target_overs"] * 6) if second["target_overs"] else quota
        won = m["winner_id"] == second["batting_team_id"] if m["outcome"] == "decided" else None
        m["chase"] = {
            "match_id": m.get("id"), "target": target, "chasing_id": second["batting_team_id"], "defending_id": first["batting_team_id"],
            "won": won, "runs": second["runs"], "balls": second["legal_balls"], "wickets": second["wickets"],
            "balls_remaining": max(0, quota_balls - second["legal_balls"]) if quota_balls else None,
            "wickets_in_hand": max(0, 10 - second["wickets"]),
            "over_completed": math.ceil(second["legal_balls"] / 6) if second["legal_balls"] else 0,
        }
    # Close match: tie, small run margin, or a chase won by ≤2 wickets / with few balls left.
    m["close"] = False
    if m["outcome"] == "tie":
        m["close"] = True
    elif m["outcome"] == "decided" and scope.format in CLOSE_THRESHOLDS:
        max_runs, max_balls = CLOSE_THRESHOLDS[scope.format]
        if m["result_margin_runs"] is not None and m["result_margin_runs"] <= max_runs:
            m["close"] = True
        elif m["result_margin_wickets"] is not None and m["result_margin_wickets"] <= 2:
            m["close"] = True
        elif m["chase"] and m["chase"]["won"] and m["chase"]["balls_remaining"] is not None \
                and m["chase"]["balls_remaining"] <= max_balls:
            m["close"] = True


def team_result(m: dict, team_id: str) -> str:
    if m["outcome"] == "decided":
        return "won" if m["winner_id"] == team_id else "lost"
    return m["outcome"]


def margin_text(m: dict) -> Optional[str]:
    if m["outcome"] == "tie":
        return "tied" + (" (super over)" if m["has_super_over"] else "")
    if m["outcome"] == "draw":
        return "drawn"
    if m["outcome"] == "no_result":
        return "no result"
    if m["result_margin_runs"]:
        return f"by {m['result_margin_runs']} runs"
    if m["result_margin_wickets"]:
        return f"by {m['result_margin_wickets']} wickets"
    return None


# ---------------------------------------------------------------- home / away

def home_ground_map(db: Session, fmt: str) -> dict:
    """{(tournament_id, season, venue_id): home team_id} plus the set of home-and-away seasons."""
    def build():
        rows = db.execute(text("""
            SELECT m.tournament_id, m.season, m.venue_id, x.tid, COUNT(*) AS n
            FROM matches m CROSS JOIN LATERAL (VALUES (m.team1_id), (m.team2_id)) x(tid)
            WHERE m.match_format = :fmt AND m.tournament_id IS NOT NULL AND m.venue_id IS NOT NULL AND x.tid IS NOT NULL
            GROUP BY 1, 2, 3, 4"""), {"fmt": fmt}).all()
        per_ground = defaultdict(list)
        for t, s, v, tid, n in rows:
            per_ground[(t, s, v)].append((int(n), tid))
        candidates = {}
        season_matches, season_home_matches = defaultdict(int), defaultdict(int)
        for key, counts in per_ground.items():
            counts.sort(reverse=True)
            ground_matches = sum(n for n, _ in counts) // 2  # each match counted once per side
            season_matches[key[:2]] += ground_matches
            top_n, top_id = counts[0]
            runner = counts[1][0] if len(counts) > 1 else 0
            if top_n >= 2 and top_n >= 2 * runner:
                candidates[key] = top_id
                season_home_matches[key[:2]] += ground_matches
        # Only trust detections in genuinely home-and-away seasons: at least half of the season's
        # matches must be at a detected home ground and at least 3 sides must have one. This drops
        # chance concentrations in group-stage events held at a few grounds (e.g. CLT20).
        sides_with_home = defaultdict(set)
        for key, tid in candidates.items():
            sides_with_home[key[:2]].add(tid)
        seasons = {s for s, n in season_matches.items()
                   if n and season_home_matches[s] / n >= 0.5 and len(sides_with_home[s]) >= 3}
        homes = {k: v for k, v in candidates.items() if k[:2] in seasons}
        return {"homes": homes, "seasons": seasons}
    return cached(("home-grounds", fmt), build)


def venue_side(m: dict, team_id: str, homes: dict) -> tuple:
    """(home|away|neutral|unclassified, method) for ``team_id`` in match ``m``."""
    is_t1 = m["team1_id"] == team_id
    own = norm_country(m["team1_country"] if is_t1 else m["team2_country"])
    opp = norm_country(m["team2_country"] if is_t1 else m["team1_country"])
    venue_c = norm_country(m["venue_country"])
    opp_id = m["team2_id"] if is_t1 else m["team1_id"]
    if venue_c and (own or opp):
        if own and own == venue_c:
            return "home", "verified_country"
        if opp and opp == venue_c:
            return "away", "verified_country"
        if own and opp:
            return "neutral", "verified_country"
    key = (m["tournament_id"], m["season"], m["venue_id"])
    home_id = homes["homes"].get(key)
    if home_id == team_id:
        return "home", "fixture_concentration"
    if home_id and home_id == opp_id:
        return "away", "fixture_concentration"
    if key[:2] in homes["seasons"]:
        return "neutral", "fixture_concentration"
    return "unclassified", None


# --------------------------------------------------------------- bowling styles

_BTYPE_CTE = """btype AS (
    SELECT DISTINCT ON (player_id) player_id, lower(attribute_value) AS btype
    FROM player_attributes WHERE attribute_type = 'bowling_type' AND lower(attribute_value) IN ('pace','spin')
    ORDER BY player_id, CASE confidence WHEN 'high' THEN 3 WHEN 'medium' THEN 2 WHEN 'low' THEN 1 ELSE 0 END DESC, updated_at DESC
)"""


def pace_spin(db: Session, scope: Scope, extra: str = "", params: Optional[dict] = None, group_by: str = "") -> List[dict]:
    """Bowling by pace/spin/unclassified from ``scouting_bowl_innings`` (super overs excluded)."""
    params = dict(params or {})
    where = scope.where(params) + (f" AND {extra}" if extra else "")
    gb = f", {group_by}" if group_by else ""
    sql = f"""
    WITH {_BTYPE_CTE}
    SELECT COALESCE(bt.btype, 'unclassified') AS style{gb},
           SUM(b.legal_balls) AS balls, SUM(b.runs) AS runs, SUM(b.wickets) AS wickets, SUM(b.dots) AS dots,
           SUM(b.fours + b.sixes) AS boundaries, COUNT(DISTINCT b.innings_id) AS innings
    FROM scouting_bowl_innings b JOIN matches m ON m.id = b.match_id
    LEFT JOIN btype bt ON bt.player_id = b.player_id
    WHERE {where}
    GROUP BY 1{gb}
    """
    return [dict(r._mapping) for r in db.execute(text(sql), params)]


def summarise_styles(rows: List[dict], baseline: Optional[List[dict]] = None) -> dict:
    by = {r["style"]: r for r in rows}
    base = {r["style"]: r for r in (baseline or [])}
    total_balls = sum(int(r["balls"] or 0) for r in rows)
    classified_wkts = sum(int(by[s]["wickets"] or 0) for s in ("pace", "spin") if s in by)
    out = []
    for s in ("pace", "spin"):
        r = by.get(s)
        b = base.get(s)
        balls, runs, wk = (int(r["balls"] or 0), int(r["runs"] or 0), int(r["wickets"] or 0)) if r else (0, 0, 0)
        econ = rate(runs, balls)
        base_econ = rate(int(b["runs"] or 0), int(b["balls"] or 0)) if b else None
        base_sr = div(int(b["balls"] or 0), int(b["wickets"] or 0), 1) if b else None
        out.append({"style": s, "balls": balls, "overs": round(balls / 6, 1), "runs": runs, "wickets": wk,
                    "economy": econ, "average": div(runs, wk), "strike_rate": div(balls, wk, 1),
                    "dot_percentage": pct(int(r["dots"] or 0), balls) if r else None,
                    "boundary_percentage": pct(int(r["boundaries"] or 0), balls) if r else None,
                    "wicket_share": pct(wk, classified_wkts), "ball_share": pct(balls, total_balls),
                    "baseline_economy": base_econ, "baseline_strike_rate": base_sr,
                    "economy_delta": round(econ - base_econ, 2) if econ is not None and base_econ is not None else None})
    unclassified = by.get("unclassified")
    return {"styles": out, "total_balls": total_balls,
            "unclassified_balls": int(unclassified["balls"] or 0) if unclassified else 0,
            "coverage_percentage": pct(total_balls - (int(unclassified["balls"] or 0) if unclassified else 0), total_balls),
            "note": "Pace/spin from verified player bowling-type attributes; deliveries by unclassified bowlers are excluded from both groups."}


# ---------------------------------------------------------------- format baseline

def format_baseline(db: Session, scope: Scope) -> dict:
    """Format-wide reference values under the same filters (all teams, all venues)."""
    def build():
        matches = load_matches(db, scope)
        inns = [i for m in matches for i in m["innings"]]
        comp = [i for i in inns if i["complete"]]
        first = sorted(i["runs"] for m in matches if m["complete"] and m["first_innings"] for i in [m["first_innings"]])
        second = [m["second_innings"]["runs"] for m in matches if m["complete"] and m["second_innings"]]
        decided = [m for m in matches if m["outcome"] == "decided" and m["first_batting_id"]]
        toss = [m for m in matches if m["outcome"] == "decided" and m["toss_winner_id"]]
        bf_wins = sum(1 for m in decided if m["winner_id"] == m["first_batting_id"])

        def q(p):
            if not first:
                return None
            idx = min(len(first) - 1, max(0, int(round(p * (len(first) - 1)))))
            return first[idx]
        phases = {}
        for p in PHASES:
            balls = sum(i[f"{p}_balls"] for i in inns)
            phases[PHASE_NAMES[p]] = {"run_rate": rate(sum(i[f"{p}_runs"] for i in inns), balls),
                                      "wickets_per_innings": div(sum(i[f"{p}_wkts"] for i in inns), sum(1 for i in inns if i[f"{p}_balls"])),
                                      "boundary_percentage": pct(sum(i[f"{p}_bnd"] for i in inns), balls)}
        balls = sum(i["legal_balls"] for i in inns)
        team_rr = defaultdict(lambda: [0, 0])
        for i in inns:
            if i["batting_team_id"]:
                team_rr[i["batting_team_id"]][0] += i["runs"]; team_rr[i["batting_team_id"]][1] += i["legal_balls"]
        return {
            "matches": len(matches), "innings": len(inns),
            "average_first_innings": avg(first), "average_second_innings": avg(second),
            "first_innings_p25": q(0.25), "first_innings_p75": q(0.75),
            "run_rate": rate(sum(i["runs"] for i in inns), balls),
            "wickets_per_innings": div(sum(i["wickets"] for i in comp), len(comp)),
            "boundary_percentage": pct(sum(i["fours"] + i["sixes"] for i in inns), balls),
            "sixes_per_innings": div(sum(i["sixes"] for i in comp), len(comp)),
            "batting_first_win_percentage": pct(bf_wins, len(decided)),
            "toss_winner_win_percentage": pct(sum(1 for m in toss if m["winner_id"] == m["toss_winner_id"]), len(toss)),
            "phases": phases,
            "pace_spin": pace_spin(db, scope),
            "team_run_rate": {k: rate(v[0], v[1]) for k, v in team_rr.items()},
        }
    return cached(("baseline",) + scope.key(), build)
