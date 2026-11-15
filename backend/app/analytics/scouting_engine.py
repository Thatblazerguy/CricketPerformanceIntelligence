"""Role-specific, reliability-aware scouting engine.

Pipeline for a recruitment request
----------------------------------
1. **Scope** (format, gender, competitions, seasons, years) selects innings from
   the persisted per-innings aggregates.
2. **Player rows** are summed in SQL per player, together with the scoring
   environment each player batted/bowled in (competition-season × phase run
   rates) so context-adjusted indices can be computed.
3. **Comparison group** = players eligible for the role (position share,
   pace/spin classification, keeper evidence) with the format's baseline sample.
   Requirement filters such as nationality or bowling style narrow the
   *candidates* but never the comparison group, so an Indian batter is compared
   with every middle-order batter in scope, not just with other Indians.
4. **Metrics**: each metric is shrunk towards the comparison-group mean with a
   prior strength estimated from the cohort (``scouting_stats.estimate_prior``),
   then converted to a percentile within the comparison group.
5. **Score** = weighted mean of metric percentiles (weights: equal per group by
   default, user-overridable). Metrics a player has no sample for are omitted
   and the remaining weights renormalised; missing data is never treated as 0.
6. **Reliability** = weight-averaged ``n / (n + m)`` across the scored metrics.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.analytics import scouting_stats as st
from app.analytics.player_roles import classify_player_role
from app.analytics.scouting_roles import (
    BAT_METRICS, BOWL_METRICS, KEEPER_MIN_STUMPINGS, LIMITED, METRICS, POSITION_SHARE, ROLES,
    MetricSpec, RoleModel, thresholds,
)
from app.ml.similarity.cache import get_or_build

FORMATS = ("T20", "T20I", "ODI", "ODM", "Test", "MDM")
CACHE_VERSION = "scout-v2.1"


# ----------------------------------------------------------------------------
# Scope
# ----------------------------------------------------------------------------

@dataclass(frozen=True)
class Scope:
    match_format: str = "T20"
    gender: str = "male"
    competitions: Tuple[str, ...] = ()
    seasons: Tuple[str, ...] = ()
    start_year: Optional[int] = None
    end_year: Optional[int] = None

    def key(self) -> tuple:
        return (self.match_format, self.gender, self.competitions, self.seasons, self.start_year, self.end_year)

    def sql(self, alias: str = "b") -> Tuple[str, dict]:
        clauses = [f"{alias}.match_format = :format"]
        params: dict = {"format": self.match_format}
        if self.gender != "all":
            clauses.append(f"{alias}.gender = :gender")
            params["gender"] = self.gender
        if self.competitions:
            clauses.append(f"{alias}.tournament_id IN (SELECT id FROM tournaments WHERE name = ANY(:competitions))")
            params["competitions"] = list(self.competitions)
        if self.seasons:
            clauses.append(f"{alias}.season = ANY(:seasons)")
            params["seasons"] = list(self.seasons)
        if self.start_year:
            clauses.append(f"{alias}.start_date >= :start_date")
            params["start_date"] = date(self.start_year, 1, 1)
        if self.end_year:
            clauses.append(f"{alias}.start_date <= :end_date")
            params["end_date"] = date(self.end_year, 12, 31)
        return " AND ".join(clauses), params

    def describe(self) -> str:
        parts = [self.match_format, {"male": "men", "female": "women"}.get(self.gender, "all genders")]
        if self.competitions:
            parts.append(", ".join(self.competitions))
        if self.seasons:
            parts.append("seasons " + ", ".join(self.seasons))
        if self.start_year or self.end_year:
            parts.append(f"{self.start_year or '…'}–{self.end_year or '…'}")
        return " · ".join(parts)


# ----------------------------------------------------------------------------
# SQL aggregation
# ----------------------------------------------------------------------------

_BAT_SQL = """
WITH scoped AS (SELECT b.* FROM scouting_bat_innings b WHERE {scope}),
env AS (
    SELECT tournament_id, season,
        SUM(runs)::float / NULLIF(SUM(balls), 0) AS all_rpb,
        SUM(pp_runs)::float / NULLIF(SUM(pp_balls), 0) AS pp_rpb,
        SUM(mid_runs)::float / NULLIF(SUM(mid_balls), 0) AS mid_rpb,
        SUM(death_runs)::float / NULLIF(SUM(death_balls), 0) AS death_rpb
    FROM scoped GROUP BY 1, 2
),
inn AS (
    SELECT s.*, e.all_rpb, COALESCE(e.pp_rpb, e.all_rpb) AS pp_rpb, COALESCE(e.mid_rpb, e.all_rpb) AS mid_rpb,
           COALESCE(e.death_rpb, e.all_rpb) AS death_rpb,
           ROW_NUMBER() OVER (PARTITION BY s.player_id ORDER BY s.start_date DESC, s.innings_number DESC) AS recency
    FROM scoped s JOIN env e ON e.tournament_id IS NOT DISTINCT FROM s.tournament_id AND e.season IS NOT DISTINCT FROM s.season
    {player_filter}
)
SELECT player_id,
    COUNT(*) AS innings, COUNT(DISTINCT match_id) AS matches, MAX(start_date) AS last_date, MIN(start_date) AS first_date,
    SUM(runs) AS runs, SUM(balls) AS balls, SUM(runs_sq) AS runs_sq, SUM(dismissed::int) AS outs,
    SUM(fours) AS fours, SUM(sixes) AS sixes, SUM(fours + sixes) AS boundaries, SUM(dots) AS dots, SUM(rotations) AS rotations,
    SUM(pp_runs) AS pp_runs, SUM(pp_balls) AS pp_balls, SUM(pp_outs) AS pp_outs, SUM(pp_dots) AS pp_dots, SUM(pp_bnd) AS pp_bnd,
    SUM(mid_runs) AS mid_runs, SUM(mid_balls) AS mid_balls, SUM(mid_outs) AS mid_outs, SUM(mid_dots) AS mid_dots, SUM(mid_bnd) AS mid_bnd,
    SUM(death_runs) AS death_runs, SUM(death_balls) AS death_balls, SUM(death_outs) AS death_outs, SUM(death_dots) AS death_dots, SUM(death_bnd) AS death_bnd,
    SUM(pace_runs) AS pace_runs, SUM(pace_balls) AS pace_balls, SUM(pace_outs) AS pace_outs, SUM(pace_dots) AS pace_dots, SUM(pace_bnd) AS pace_bnd,
    SUM(spin_runs) AS spin_runs, SUM(spin_balls) AS spin_balls, SUM(spin_outs) AS spin_outs, SUM(spin_dots) AS spin_dots, SUM(spin_bnd) AS spin_bnd,
    SUM(pp_balls * pp_rpb + mid_balls * mid_rpb + death_balls * death_rpb
        + (balls - pp_balls - mid_balls - death_balls) * all_rpb) AS exp_runs,
    SUM(pp_balls * pp_rpb) AS exp_pp_runs, SUM(mid_balls * mid_rpb) AS exp_mid_runs, SUM(death_balls * death_rpb) AS exp_death_runs,
    COUNT(*) FILTER (WHERE batting_position <= 2) AS pos_1_2, COUNT(*) FILTER (WHERE batting_position = 3) AS pos_3,
    COUNT(*) FILTER (WHERE batting_position = 4) AS pos_4, COUNT(*) FILTER (WHERE batting_position = 5) AS pos_5,
    COUNT(*) FILTER (WHERE batting_position = 6) AS pos_6, COUNT(*) FILTER (WHERE batting_position = 7) AS pos_7,
    COUNT(*) FILTER (WHERE batting_position >= 8) AS pos_8_plus,
    COUNT(*) FILTER (WHERE dismissed AND balls <= 10) AS early_outs,
    COUNT(*) FILTER (WHERE dismissed OR balls > 10) AS early_eligible,
    COUNT(*) FILTER (WHERE runs >= :sig) AS sig_innings,
    COUNT(*) FILTER (WHERE dismissed AND runs < :poor) AS fail_innings,
    COUNT(*) FILTER (WHERE :pp_end > 0 AND entry_wickets >= 2 AND entry_over < :pp_end AND batting_position >= 3) AS pressure_innings,
    COALESCE(SUM(runs) FILTER (WHERE :pp_end > 0 AND entry_wickets >= 2 AND entry_over < :pp_end AND batting_position >= 3), 0) AS pressure_runs,
    COUNT(*) FILTER (WHERE :pp_end > 0 AND entry_wickets >= 2 AND entry_over < :pp_end AND batting_position >= 3 AND dismissed) AS pressure_outs,
    COUNT(*) FILTER (WHERE is_chase) AS chase_innings,
    COALESCE(SUM(runs) FILTER (WHERE is_chase), 0) AS chase_runs,
    COALESCE(SUM(balls) FILTER (WHERE is_chase), 0) AS chase_balls,
    COUNT(*) FILTER (WHERE is_chase AND dismissed) AS chase_outs,
    COUNT(*) FILTER (WHERE is_chase AND team_won) AS chase_won_innings,
    COUNT(*) FILTER (WHERE is_chase AND team_won AND NOT dismissed) AS chase_won_notouts,
    COALESCE(SUM(runs) FILTER (WHERE innings_number = 1 AND match_format IN ('T20','T20I','ODI','ODM')), 0) AS first_runs,
    COALESCE(SUM(balls) FILTER (WHERE innings_number = 1 AND match_format IN ('T20','T20I','ODI','ODM')), 0) AS first_balls,
    COUNT(*) FILTER (WHERE innings_number = 1 AND match_format IN ('T20','T20I','ODI','ODM') AND dismissed) AS first_outs,
    COUNT(*) FILTER (WHERE innings_number = 1 AND match_format IN ('T20','T20I','ODI','ODM')) AS first_innings,
    COALESCE(SUM(runs) FILTER (WHERE recency <= 10), 0) AS recent_runs,
    COALESCE(SUM(balls) FILTER (WHERE recency <= 10), 0) AS recent_balls,
    COUNT(*) FILTER (WHERE recency <= 10 AND dismissed) AS recent_outs,
    COUNT(*) FILTER (WHERE recency <= 10) AS recent_innings,
    percentile_cont(0.5) WITHIN GROUP (ORDER BY runs) AS median_runs,
    stddev_pop(runs) AS sd_runs,
    COUNT(*) FILTER (WHERE dismissal_type = 'caught') AS out_caught,
    COUNT(*) FILTER (WHERE dismissal_type = 'bowled') AS out_bowled,
    COUNT(*) FILTER (WHERE dismissal_type = 'lbw') AS out_lbw,
    COUNT(*) FILTER (WHERE dismissal_type = 'run out') AS out_run_out,
    COUNT(*) FILTER (WHERE dismissal_type = 'stumped') AS out_stumped,
    COUNT(*) FILTER (WHERE dismissal_type = 'caught and bowled') AS out_caught_and_bowled,
    COUNT(*) FILTER (WHERE dismissed AND dismissal_type NOT IN ('caught','bowled','lbw','run out','stumped','caught and bowled')) AS out_other
FROM inn GROUP BY player_id
"""

_BOWL_SQL = """
WITH scoped AS (SELECT b.* FROM scouting_bowl_innings b WHERE {scope}),
par AS (SELECT SUM(runs)::float / NULLIF(SUM(legal_balls), 0) AS par_rpb FROM scoped),
env AS (
    SELECT tournament_id, season,
        SUM(runs)::float / NULLIF(SUM(legal_balls), 0) AS all_rpb,
        SUM(pp_runs)::float / NULLIF(SUM(pp_balls), 0) AS pp_rpb,
        SUM(mid_runs)::float / NULLIF(SUM(mid_balls), 0) AS mid_rpb,
        SUM(death_runs)::float / NULLIF(SUM(death_balls), 0) AS death_rpb
    FROM scoped GROUP BY 1, 2
),
inn AS (
    SELECT s.*, e.all_rpb, COALESCE(e.pp_rpb, e.all_rpb) AS pp_rpb, COALESCE(e.mid_rpb, e.all_rpb) AS mid_rpb,
           COALESCE(e.death_rpb, e.all_rpb) AS death_rpb, par.par_rpb,
           ROW_NUMBER() OVER (PARTITION BY s.player_id ORDER BY s.start_date DESC, s.innings_number DESC) AS recency
    FROM scoped s CROSS JOIN par
    JOIN env e ON e.tournament_id IS NOT DISTINCT FROM s.tournament_id AND e.season IS NOT DISTINCT FROM s.season
    {player_filter}
)
SELECT player_id,
    COUNT(*) AS innings, COUNT(DISTINCT match_id) AS matches, MAX(start_date) AS last_date, MIN(start_date) AS first_date,
    SUM(legal_balls) AS legal_balls, SUM(runs) AS runs, SUM(runs_sq) AS runs_sq, SUM(wickets) AS wickets,
    SUM(dots) AS dots, SUM(fours) AS fours, SUM(sixes) AS sixes, SUM(fours + sixes) AS boundaries,
    SUM(wides) AS wides, SUM(noballs) AS noballs,
    SUM(pp_balls) AS pp_balls, SUM(pp_runs) AS pp_runs, SUM(pp_wkts) AS pp_wkts, SUM(pp_dots) AS pp_dots, SUM(pp_bnd) AS pp_bnd,
    SUM(mid_balls) AS mid_balls, SUM(mid_runs) AS mid_runs, SUM(mid_wkts) AS mid_wkts, SUM(mid_dots) AS mid_dots, SUM(mid_bnd) AS mid_bnd,
    SUM(death_balls) AS death_balls, SUM(death_runs) AS death_runs, SUM(death_wkts) AS death_wkts, SUM(death_dots) AS death_dots, SUM(death_bnd) AS death_bnd,
    SUM(pp_balls * pp_rpb + mid_balls * mid_rpb + death_balls * death_rpb
        + (legal_balls - pp_balls - mid_balls - death_balls) * all_rpb) AS exp_runs,
    MAX(par_rpb) AS par_rpb,
    COUNT(*) FILTER (WHERE legal_balls >= :spell_min) AS spells,
    COUNT(*) FILTER (WHERE legal_balls >= :spell_min AND runs <= legal_balls * par_rpb) AS good_spells,
    COUNT(*) FILTER (WHERE legal_balls >= :spell_min AND wickets = 0) AS wicketless,
    COUNT(*) FILTER (WHERE wickets >= :haul) AS hauls,
    COUNT(*) FILTER (WHERE is_defending) AS defend_innings,
    COALESCE(SUM(runs) FILTER (WHERE is_defending AND team_won), 0) AS defend_won_runs,
    COALESCE(SUM(legal_balls) FILTER (WHERE is_defending AND team_won), 0) AS defend_won_balls,
    COALESCE(SUM(wickets) FILTER (WHERE is_defending AND team_won), 0) AS defend_won_wkts,
    COALESCE(SUM(runs) FILTER (WHERE is_defending AND team_won = FALSE), 0) AS defend_lost_runs,
    COALESCE(SUM(legal_balls) FILTER (WHERE is_defending AND team_won = FALSE), 0) AS defend_lost_balls,
    COALESCE(SUM(wickets) FILTER (WHERE is_defending AND team_won = FALSE), 0) AS defend_lost_wkts,
    COALESCE(SUM(runs) FILTER (WHERE recency <= 10), 0) AS recent_runs,
    COALESCE(SUM(legal_balls) FILTER (WHERE recency <= 10), 0) AS recent_balls,
    COALESCE(SUM(wickets) FILTER (WHERE recency <= 10), 0) AS recent_wkts,
    COUNT(*) FILTER (WHERE recency <= 10) AS recent_innings,
    SUM(wk_bowled) AS wk_bowled, SUM(wk_lbw) AS wk_lbw, SUM(wk_caught) AS wk_caught,
    SUM(wk_stumped) AS wk_stumped, SUM(wk_other) AS wk_other
FROM inn GROUP BY player_id
"""

_DUAL_SQL = """
SELECT b.player_id, COUNT(DISTINCT b.match_id) AS dual_matches
FROM scouting_bat_innings b
JOIN scouting_bowl_innings w ON w.match_id = b.match_id AND w.player_id = b.player_id
WHERE {scope} AND b.balls >= :dual_bat AND w.legal_balls >= :dual_bowl
GROUP BY b.player_id
"""

_KEEPER_SQL = """
SELECT w.fielder_id AS player_id,
       COUNT(*) FILTER (WHERE w.dismissal_type = 'stumped') AS stumpings
FROM wickets w
JOIN deliveries d ON d.id = w.delivery_id
JOIN match_innings mi ON mi.id = d.innings_id
JOIN matches m ON m.id = mi.match_id
WHERE w.dismissal_type = 'stumped' AND w.fielder_id IS NOT NULL AND mi.is_super_over = FALSE
  AND m.match_format = :format {gender}
GROUP BY w.fielder_id
"""

_ATTR_TYPES = ("nationality", "batting_style", "bowling_style", "bowling_type", "bowling_arm",
               "bowling_speed_category", "primary_role", "date_of_birth")


def _num(value):
    if value is None:
        return 0
    return float(value) if not isinstance(value, int) else value


def _fetch(db: Session, sql: str, scope: Scope, extra: dict, player_ids: Optional[Sequence[str]] = None) -> Dict[str, dict]:
    scope_sql, params = scope.sql("b")
    player_filter = "WHERE s.player_id = ANY(:pids)" if player_ids is not None else ""
    params = {**params, **extra}
    if player_ids is not None:
        params["pids"] = list(player_ids)
    rows = db.execute(text(sql.format(scope=scope_sql, player_filter=player_filter)), params).mappings().all()
    out = {}
    for row in rows:
        rec = {k: (_num(v) if k not in ("player_id", "last_date", "first_date") else v) for k, v in row.items()}
        out[row["player_id"]] = rec
    return out


def _attributes(db: Session, ids: Iterable[str]) -> Dict[str, dict]:
    ids = list(ids)
    if not ids:
        return {}
    rows = db.execute(text("""
        SELECT player_id, attribute_type, attribute_value FROM player_attributes
        WHERE player_id = ANY(:ids) AND attribute_type = ANY(:types)
        ORDER BY player_id, attribute_type,
                 CASE confidence WHEN 'high' THEN 3 WHEN 'medium' THEN 2 WHEN 'low' THEN 1 ELSE 0 END DESC, updated_at DESC
    """), {"ids": ids, "types": list(_ATTR_TYPES)}).mappings().all()
    attrs: Dict[str, dict] = {}
    for row in rows:
        value = row["attribute_value"]
        if value and value.strip().casefold() not in ("unknown", "other / unclassified"):
            attrs.setdefault(row["player_id"], {}).setdefault(row["attribute_type"], value)
    names = dict(db.execute(text("SELECT id, canonical_name FROM players WHERE id = ANY(:ids)"), {"ids": ids}).all())
    for pid in ids:
        attrs.setdefault(pid, {})["name"] = names.get(pid, "Unknown")
    return attrs


@dataclass
class ScopeData:
    scope: Scope
    bat: Dict[str, dict]
    bowl: Dict[str, dict]
    attrs: Dict[str, dict]
    keepers: Dict[str, int]
    dual: Dict[str, int]
    thresholds: dict
    priors: Dict[Tuple[str, str], Optional[st.Prior]] = field(default_factory=dict)


def load_scope(db: Session, scope: Scope) -> ScopeData:
    """Aggregate every player in scope (cached for 5 minutes; cleared after imports)."""
    def build():
        th = thresholds(scope.match_format)
        bat = _fetch(db, _BAT_SQL, scope, {"sig": th["sig"], "poor": th["poor"], "pp_end": th["pp_end"]})
        bowl = _fetch(db, _BOWL_SQL, scope, {"spell_min": th["spell_min"], "haul": th["haul"]})
        scope_sql, params = scope.sql("b")
        dual = dict(db.execute(text(_DUAL_SQL.format(scope=scope_sql)),
                               {**params, "dual_bat": th["dual_bat_balls"], "dual_bowl": th["dual_bowl_balls"]}).all())
        gender = "" if scope.gender == "all" else "AND lower(m.gender) = :gender"
        keepers = dict(db.execute(text(_KEEPER_SQL.format(gender=gender)),
                                  {"format": scope.match_format, "gender": scope.gender}).all())
        attrs = _attributes(db, set(bat) | set(bowl))
        return ScopeData(scope, bat, bowl, attrs, keepers, dual, th)
    return get_or_build((CACHE_VERSION, "scope") + scope.key(), build)


# ----------------------------------------------------------------------------
# Metric evaluation
# ----------------------------------------------------------------------------

def _second_moment(rows: Iterable[dict]) -> Optional[float]:
    rows = list(rows)
    sq = sum(r.get("runs_sq", 0) for r in rows)
    n = sum(r.get("balls", r.get("legal_balls", 0)) for r in rows)
    return sq / n if n else None


def _metric_prior(spec: MetricSpec, cohort: List[dict]) -> Optional[st.Prior]:
    pairs = [(r.get(spec.num, 0), r.get(spec.den, 0)) for r in cohort]
    if spec.kind == "per_unit":
        if spec.sumsq:
            sumsq = sum(r.get(spec.sumsq, 0) for r in cohort)
            return st.estimate_prior(pairs, "per_unit", sumsq=sumsq)
        # Phase/matchup subsets do not store their own sum of squares; the cohort's
        # overall per-ball second moment is used as the unit-variance approximation.
        moment = _second_moment(cohort)
        total_den = sum(d for _, d in pairs if d)
        if moment is None or not total_den:
            return None
        return st.estimate_prior(pairs, "per_unit", sumsq=moment * total_den)
    if spec.kind == "exponential":
        return st.estimate_prior(pairs, "exponential")
    return st.estimate_prior(pairs, "proportion")


def _display(spec: MetricSpec, rate: Optional[float]) -> Optional[float]:
    if rate is None:
        return None
    if spec.inverse:
        return round(spec.scale / rate, spec.decimals) if rate > 0 else None
    return round(rate * spec.scale, spec.decimals)


def evaluate_base(spec: MetricSpec, row: dict, prior: Optional[st.Prior]) -> dict:
    num, den = row.get(spec.num, 0) or 0, row.get(spec.den, 0) or 0
    raw = st.ratio(num, den)
    shrunk = st.shrink(num, den, prior)
    ci = None
    if den:
        if spec.kind == "proportion":
            ci = st.wilson_interval(num, den)
        elif spec.kind == "per_unit" and prior is not None:
            ci = st.mean_interval(num, den, prior.unit_variance)
        elif spec.kind == "exponential":
            ci = st.average_interval(num, den)
    if ci is not None:
        lo, hi = (_display(spec, ci[0]), _display(spec, ci[1]))
        if spec.inverse:
            lo, hi = hi, lo
        ci = [lo, hi]
    return {
        "value": _display(spec, raw), "adjusted": _display(spec, shrunk), "rank_value": shrunk,
        "n": int(den), "unit": spec.unit, "reliability": st.reliability(den, prior), "ci": ci,
    }


def _derived(key: str, row: dict, m: Dict[str, dict]) -> dict:
    empty = {"value": None, "adjusted": None, "rank_value": None, "n": 0, "unit": "balls", "reliability": None, "ci": None}

    def index(base: str, exp_key: str, balls_key: str, lower: bool = False) -> dict:
        b = m.get(base) or {}
        exp, balls = row.get(exp_key), row.get(balls_key)
        if not b.get("rank_value") or not exp or not balls:
            return dict(empty, n=int(balls or 0))
        env_rate = exp / balls
        value = round(100.0 * (row[METRICS[base].num] / balls) / env_rate, 1)
        adjusted = round(100.0 * b["rank_value"] / env_rate, 1)
        ci = None
        if b.get("ci"):
            scale = METRICS[base].scale
            ci = [round(100.0 * (c / scale) / env_rate, 1) for c in b["ci"]]
        return {"value": value, "adjusted": adjusted, "rank_value": adjusted, "n": b["n"], "unit": b["unit"],
                "reliability": b["reliability"], "ci": ci,
                "environment": round(env_rate * METRICS[base].scale, 2)}

    if key == "sr_index":
        return index("strike_rate", "exp_runs", "balls")
    if key == "pp_sr_index":
        return index("pp_sr", "exp_pp_runs", "pp_balls")
    if key == "mid_sr_index":
        return index("mid_sr", "exp_mid_runs", "mid_balls")
    if key == "death_sr_index":
        return index("death_sr", "exp_death_runs", "death_balls")
    if key == "econ_index":
        return index("economy", "exp_runs", "legal_balls", lower=True)
    if key == "weaker_style_sr":
        pace, spin = m.get("pace_sr") or {}, m.get("spin_sr") or {}
        if pace.get("rank_value") is None or spin.get("rank_value") is None:
            return empty
        pick = pace if pace["rank_value"] <= spin["rank_value"] else spin
        return {**pick, "value": pick["value"], "style": "pace" if pick is pace else "spin"}
    if key == "acceleration":
        death = m.get("death_sr") or {}
        if death.get("rank_value") is None:
            return empty
        pre_balls = row.get("balls", 0) - row.get("death_balls", 0)
        pre_runs = row.get("runs", 0) - row.get("death_runs", 0)
        prior = m.get("_strike_rate_prior")
        if not pre_balls or prior is None:
            return empty
        pre = st.shrink(pre_runs, pre_balls, prior)
        raw_gap = (row["death_runs"] / row["death_balls"] - pre_runs / pre_balls) * 100 if row.get("death_balls") else None
        adj = round((death["rank_value"] - pre) * 100, 1)
        rel = min(death["reliability"] or 0, st.reliability(pre_balls, prior) or 0)
        return {"value": round(raw_gap, 1) if raw_gap is not None else None, "adjusted": adj, "rank_value": adj,
                "n": death["n"], "unit": "balls", "reliability": rel, "ci": None}
    return empty


def evaluate_player(row: dict, priors: Dict[str, Optional[st.Prior]], disc: str) -> Dict[str, dict]:
    specs = BAT_METRICS if disc == "bat" else BOWL_METRICS
    out: Dict[str, dict] = {}
    for spec in specs:
        if spec.kind != "derived":
            out[spec.key] = evaluate_base(spec, row, priors.get(spec.key))
    out["_strike_rate_prior"] = priors.get("strike_rate")
    for spec in specs:
        if spec.kind == "derived":
            out[spec.key] = _derived(spec.key, row, out)
    out.pop("_strike_rate_prior", None)
    return out


# ----------------------------------------------------------------------------
# Role eligibility and comparison groups
# ----------------------------------------------------------------------------

def position_share(row: dict, positions: Sequence[int]) -> float:
    if not row or not row.get("innings"):
        return 0.0
    buckets = {1: "pos_1_2", 2: "pos_1_2", 3: "pos_3", 4: "pos_4", 5: "pos_5", 6: "pos_6", 7: "pos_7"}
    count, seen = 0, set()
    for p in positions:
        key = buckets.get(p, "pos_8_plus")
        if key not in seen:
            seen.add(key)
            count += row.get(key, 0)
    return count / row["innings"]


def primary_positions(row: dict) -> str:
    if not row or not row.get("innings"):
        return "—"
    buckets = [("1–2", row.get("pos_1_2", 0)), ("3", row.get("pos_3", 0)), ("4", row.get("pos_4", 0)),
               ("5", row.get("pos_5", 0)), ("6", row.get("pos_6", 0)), ("7", row.get("pos_7", 0)),
               ("8+", row.get("pos_8_plus", 0))]
    label, count = max(buckets, key=lambda b: b[1])
    return f"#{label} ({100 * count / row['innings']:.0f}% of innings)"


def bowling_class(attrs: dict) -> Optional[str]:
    value = (attrs.get("bowling_type") or "").lower()
    return value if value in ("pace", "spin") else None


def is_keeper(pid: str, data: ScopeData) -> bool:
    role = (data.attrs.get(pid, {}).get("primary_role") or "").lower()
    return data.keepers.get(pid, 0) >= KEEPER_MIN_STUMPINGS or "wk" in role or "keeper" in role


def meets_baseline(row: Optional[dict], disc: str, th: dict) -> bool:
    if not row:
        return False
    if disc == "bat":
        return row["innings"] >= th["bat_innings"] and row["balls"] >= th["bat_balls"]
    return row["innings"] >= th["bowl_innings"] and row["legal_balls"] >= th["bowl_balls"]


def role_eligible(role: RoleModel, pid: str, data: ScopeData, positions: Optional[Sequence[int]] = None) -> bool:
    bat, bowl = data.bat.get(pid), data.bowl.get(pid)
    if role.disc == "bat":
        if not bat:
            return False
        pos = positions or role.positions
        if pos and position_share(bat, pos) < POSITION_SHARE:
            return False
        if role.requires_keeper and not is_keeper(pid, data):
            return False
        return True
    if role.disc == "bowl":
        if not bowl:
            return False
        if role.bowling_type and bowling_class(data.attrs.get(pid, {})) != role.bowling_type:
            return False
        return True
    return bool(bat and bowl)


def comparison_group(role: RoleModel, data: ScopeData, disc: str, positions=None) -> List[str]:
    th = data.thresholds
    if role.disc == "allround":
        # All-rounders are measured against regular batters / regular bowlers.
        source = data.bat if disc == "bat" else data.bowl
        return [pid for pid, row in source.items() if meets_baseline(row, disc, th)]
    rows = data.bat if disc == "bat" else data.bowl
    return [pid for pid in rows if meets_baseline(rows[pid], disc, th) and role_eligible(role, pid, data, positions)]


@dataclass
class Cohort:
    disc: str
    members: List[str]
    priors: Dict[str, Optional[st.Prior]]
    evaluated: Dict[str, Dict[str, dict]]
    distributions: Dict[str, List[float]]
    fallback_note: Optional[str] = None


def build_cohort(data: ScopeData, role: RoleModel, disc: str, positions=None) -> Cohort:
    pos_key = tuple(positions) if positions else None
    key = (CACHE_VERSION, "cohort") + data.scope.key() + (role.key, disc, pos_key)

    def build():
        members = comparison_group(role, data, disc, positions)
        note = None
        if len(members) < 30 and role.disc != "allround":
            generic = ROLES["batter" if disc == "bat" else "bowler"]
            wider = comparison_group(generic, data, disc)
            note = (f"Only {len(members)} {role.label.lower()}s met the baseline sample in this scope; percentiles use all "
                    f"{len(wider)} regular {'batters' if disc == 'bat' else 'bowlers'} instead.")
            members = wider
        rows = data.bat if disc == "bat" else data.bowl
        cohort_rows = [rows[p] for p in members]
        specs = BAT_METRICS if disc == "bat" else BOWL_METRICS
        priors = {s.key: _metric_prior(s, cohort_rows) for s in specs if s.kind != "derived"}
        evaluated = {pid: evaluate_player(rows[pid], priors, disc) for pid in members}
        distributions: Dict[str, List[float]] = {}
        for spec in specs:
            distributions[spec.key] = sorted(
                ev[spec.key]["rank_value"] for ev in evaluated.values() if ev[spec.key]["rank_value"] is not None)
        return Cohort(disc, members, priors, evaluated, distributions, note)
    return get_or_build(key, build)


def percentile_for(spec: MetricSpec, cohort: Cohort, rank_value: Optional[float]) -> Optional[float]:
    dist = cohort.distributions.get(spec.key) or []
    if rank_value is None or len(dist) < 5:
        return None
    higher = spec.higher
    return st.percentile_rank(rank_value, dist, higher_is_better=higher)


def cohort_median(spec: MetricSpec, cohort: Cohort) -> Optional[float]:
    values = [cohort.evaluated[p][spec.key]["value"] for p in cohort.members
              if cohort.evaluated[p][spec.key]["value"] is not None]
    q = st.quantile(values, 0.5)
    return round(q, spec.decimals) if q is not None else None


# ----------------------------------------------------------------------------
# Scoring
# ----------------------------------------------------------------------------

def normalise_weights(weights: Dict[str, float], allowed: Iterable[str]) -> Dict[str, float]:
    allowed = set(allowed)
    clean = {k: float(v) for k, v in (weights or {}).items() if k in allowed and v and float(v) > 0}
    total = sum(clean.values())
    return {k: v / total for k, v in clean.items()} if total else {}


def score_metrics(metrics: Dict[str, dict], weights: Dict[str, float], cohort: Cohort, groups: Dict[str, str]) -> dict:
    """Weighted mean of percentiles over metrics the player has evidence for."""
    parts = []
    for key, weight in weights.items():
        spec = METRICS[key]
        m = metrics.get(key) or {}
        pct = percentile_for(spec, cohort, m.get("rank_value"))
        parts.append({
            "metric": key, "label": spec.label, "group": groups.get(key, "Custom"), "weight": round(weight, 4),
            "value": m.get("value"), "adjusted": m.get("adjusted"), "ci": m.get("ci"),
            "n": m.get("n", 0), "unit": m.get("unit"), "reliability": _r(m.get("reliability")),
            "percentile": pct, "environment": m.get("environment"), "higher_is_better": spec.higher,
            "cohort_median": cohort_median(spec, cohort), "style": m.get("style"),
        })
    scored = [p for p in parts if p["percentile"] is not None]
    wsum = sum(p["weight"] for p in scored)
    score = sum(p["percentile"] * p["weight"] for p in scored) / wsum if wsum else None
    rel = st.weighted_mean((p["reliability"], p["weight"]) for p in scored)
    for p in parts:
        p["contribution"] = round(p["percentile"] * p["weight"] / wsum, 2) if (p["percentile"] is not None and wsum) else None
    coverage = wsum / sum(weights.values()) if weights else 0
    return {"score": round(score, 1) if score is not None else None, "reliability": _r(rel),
            "weight_coverage": round(coverage, 3), "metrics": parts}


def _r(value, digits=3):
    return round(value, digits) if value is not None else None


def _fmt_value(part: dict) -> str:
    spec = METRICS[part["metric"]]
    v = part["value"]
    if v is None:
        return "—"
    text_v = f"{v:.{spec.decimals}f}"
    return text_v + ("%" if spec.key.endswith("_pct") else "")


def narrative(parts: List[dict], cohort_label: str, cohort_size: int) -> Tuple[List[str], List[str]]:
    """Evidence-backed strengths / weaknesses (no unsupported adjectives)."""
    scored = [p for p in parts if p["percentile"] is not None]
    strengths, weaknesses = [], []
    for p in sorted(scored, key=lambda x: -x["percentile"]):
        if p["percentile"] >= 75 and len(strengths) < 3:
            strengths.append(_sentence(p, cohort_label, cohort_size))
    for p in sorted(scored, key=lambda x: x["percentile"]):
        if p["percentile"] <= 25 and len(weaknesses) < 3:
            weaknesses.append(_sentence(p, cohort_label, cohort_size))
    return strengths, weaknesses


def _ordinal(value: float) -> str:
    n = int(round(value))
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _sentence(p: dict, cohort_label: str, cohort_size: int) -> str:
    median_txt = f"; group median {p['cohort_median']}" if p.get("cohort_median") is not None else ""
    adj = f" (shrunk {p['adjusted']})" if p.get("adjusted") is not None and p["adjusted"] != p["value"] else ""
    rel = p.get("reliability")
    rel_txt = f", reliability {rel:.2f}" if rel is not None else ""
    return (f"{p['label']} {_fmt_value(p)}{adj} — {_ordinal(min(p['percentile'], 99))} percentile of {cohort_size} {cohort_label}"
            f"{median_txt} (n={p['n']} {p['unit']}{rel_txt}).")


# ----------------------------------------------------------------------------
# Public API: rank, evaluate single players
# ----------------------------------------------------------------------------

@dataclass
class Requirements:
    role: str = "batter"
    nationality: Optional[str] = None
    batting_hand: Optional[str] = None
    bowling_arm: Optional[str] = None
    bowling_styles: Tuple[str, ...] = ()
    bowling_type: Optional[str] = None
    positions: Tuple[int, ...] = ()
    min_matches: int = 0
    min_innings: int = 0
    min_age: Optional[int] = None
    max_age: Optional[int] = None
    bounds: Tuple[Tuple[str, str, float], ...] = ()      # (metric, 'min'|'max', value)
    weights: Optional[Dict[str, float]] = None
    allrounder_batting_weight: float = 0.5
    min_dual_matches: int = 0                              # all-rounders: matches using both disciplines
    min_tier: Optional[str] = None                         # 'Established' | 'Promising – limited evidence'


def _age(dob: Optional[str]) -> Optional[int]:
    try:
        born = date.fromisoformat((dob or "")[:10])
    except ValueError:
        return None
    today = date.today()
    return today.year - born.year - ((today.month, today.day) < (born.month, born.day))


def player_identity(pid: str, data: ScopeData) -> dict:
    a = data.attrs.get(pid, {})
    bat, bowl = data.bat.get(pid), data.bowl.get(pid)
    role_label, role_source, role_conf = classify_player_role(
        bat.get("balls") if bat else 0, bat.get("innings") if bat else 0,
        bowl.get("legal_balls") if bowl else 0, bowl.get("innings") if bowl else 0, None)
    return {
        "player_id": pid, "player_name": a.get("name", "Unknown"),
        "nationality": a.get("nationality"), "batting_hand": a.get("batting_style"),
        "bowling_style": a.get("bowling_style"), "bowling_type": a.get("bowling_type"),
        "bowling_arm": a.get("bowling_arm"), "bowling_speed": a.get("bowling_speed_category"),
        "age": _age(a.get("date_of_birth")), "metadata_role": a.get("primary_role"),
        "observed_role": role_label, "observed_role_basis": role_source,
        "keeper_evidence": {"stumpings": data.keepers.get(pid, 0)},
        "primary_position": primary_positions(bat) if bat else None,
    }


def _passes_identity(pid: str, data: ScopeData, req: Requirements) -> Optional[str]:
    a = data.attrs.get(pid, {})
    if req.nationality and (a.get("nationality") or "").casefold() != req.nationality.casefold():
        return "nationality"
    if req.batting_hand and (a.get("batting_style") or "").casefold() != req.batting_hand.casefold():
        return "batting hand unknown or different"
    if req.bowling_arm and (a.get("bowling_arm") or "").casefold() != req.bowling_arm.casefold():
        return "bowling arm unknown or different"
    if req.bowling_type and bowling_class(a) != req.bowling_type:
        return "pace/spin classification unknown or different"
    if req.bowling_styles and (a.get("bowling_style") or "") not in req.bowling_styles:
        return "detailed bowling style unknown or different"
    if req.min_age is not None or req.max_age is not None:
        age = _age(a.get("date_of_birth"))
        if age is None:
            return "no verified date of birth"
        if (req.min_age is not None and age < req.min_age) or (req.max_age is not None and age > req.max_age):
            return "age"
    return None


def evaluate_candidate(pid: str, data: ScopeData, role: RoleModel, req: Requirements,
                       cohorts: Dict[str, Cohort], weights: Dict[str, Dict[str, float]]) -> dict:
    groups = role.metric_groups(data.scope.match_format)
    out = {"identity": player_identity(pid, data)}
    disc_results = {}
    for disc in ("bat", "bowl"):
        if disc not in cohorts:
            continue
        cohort = cohorts[disc]
        row = (data.bat if disc == "bat" else data.bowl).get(pid)
        if not row:
            disc_results[disc] = None
            continue
        metrics = cohort.evaluated.get(pid) or evaluate_player(row, cohort.priors, disc)
        disc_results[disc] = score_metrics(metrics, weights[disc], cohort, groups)
    if role.disc == "allround":
        bat_s, bowl_s = disc_results.get("bat"), disc_results.get("bowl")
        wb = min(max(req.allrounder_batting_weight, 0.0), 1.0)
        bat_score = bat_s["score"] if bat_s else None
        bowl_score = bowl_s["score"] if bowl_s else None
        if bat_score is not None and bowl_score is not None:
            score = round(wb * bat_score + (1 - wb) * bowl_score, 1)
        else:
            score = None
        rel = st.weighted_mean([((bat_s or {}).get("reliability"), wb), ((bowl_s or {}).get("reliability"), 1 - wb)])
        out.update(score=score, reliability=_r(rel), batting=bat_s, bowling=bowl_s,
                   metrics=(bat_s or {}).get("metrics", []) + (bowl_s or {}).get("metrics", []),
                   allrounder_type=allrounder_type(bat_score, bowl_score),
                   dual_matches=data.dual.get(pid, 0))
    else:
        res = disc_results.get("bat" if role.disc == "bat" else "bowl") or {}
        out.update(score=res.get("score"), reliability=res.get("reliability"), metrics=res.get("metrics", []),
                   weight_coverage=res.get("weight_coverage"))
    out["tier"] = st.tier(out.get("reliability"))
    return out


def allrounder_type(bat_score: Optional[float], bowl_score: Optional[float]) -> str:
    """Quality-based all-rounder label; recorded activity alone never qualifies."""
    if bat_score is None or bowl_score is None:
        return "Insufficient evidence in one discipline"
    if bat_score >= 50 and bowl_score >= 50:
        return "Genuine all-rounder (both disciplines ≥ median of regulars)"
    if bat_score >= 50 and bowl_score >= 35:
        return "Batting all-rounder"
    if bowl_score >= 50 and bat_score >= 35:
        return "Bowling all-rounder"
    if bat_score >= 50:
        return "Batter who bowls (bowling below all-rounder standard)"
    if bowl_score >= 50:
        return "Bowler who bats (batting below all-rounder standard)"
    return "Not an effective all-rounder on this evidence"


def _role_weights(role: RoleModel, fmt: str, user: Optional[Dict[str, float]]) -> Dict[str, Dict[str, float]]:
    bat_keys = [m.key for m in BAT_METRICS if not (m.limited_only and fmt not in LIMITED)]
    bowl_keys = [m.key for m in BOWL_METRICS if not (m.limited_only and fmt not in LIMITED)]
    if role.disc == "allround":
        bat_default = role.default_weights(fmt, role.groups_for(fmt))
        bowl_default = role.default_weights(fmt, role.bowl_groups)
        bat_w = normalise_weights({k: v for k, v in (user or bat_default).items() if k in bat_keys}, bat_keys) or bat_default
        bowl_w = normalise_weights({k: v for k, v in (user or bowl_default).items() if k in bowl_keys}, bowl_keys) or bowl_default
        return {"bat": bat_w, "bowl": bowl_w}
    keys = bat_keys if role.disc == "bat" else bowl_keys
    default = role.default_weights(fmt)
    weights = normalise_weights(user, keys) if user else default
    return {role.disc: weights or default}


def rank(db: Session, scope: Scope, req: Requirements, limit: int = 200) -> dict:
    if req.role not in ROLES:
        raise ValueError(f"Unknown role model '{req.role}'")
    role = ROLES[req.role]
    if role.limited_only and scope.match_format not in LIMITED:
        raise ValueError(f"The {role.label} model needs phase data and is only defined for limited-overs formats")
    data = load_scope(db, scope)
    th = data.thresholds
    positions = tuple(req.positions) or None
    discs = ("bat", "bowl") if role.disc == "allround" else (role.disc,)
    cohorts = {d: build_cohort(data, role, d, positions if d == "bat" else None) for d in discs}
    weights = _role_weights(role, scope.match_format, req.weights)

    # Candidate pool: role-eligible players meeting the user's sample minimums.
    if role.disc == "allround":
        pool = [p for p in set(data.bat) & set(data.bowl)
                if meets_baseline(data.bat[p], "bat", th) and meets_baseline(data.bowl[p], "bowl", th)]
    else:
        source = data.bat if role.disc == "bat" else data.bowl
        pool = [p for p in source if role_eligible(role, p, data, positions)]

    exclusions: Dict[str, int] = {}

    def exclude(reason: str):
        exclusions[reason] = exclusions.get(reason, 0) + 1

    candidates = []
    for pid in pool:
        rows = [r for r in (data.bat.get(pid) if "bat" in discs else None,
                            data.bowl.get(pid) if "bowl" in discs else None) if r]
        matches = max(r["matches"] for r in rows)
        innings = min(r["innings"] for r in rows)
        if matches < req.min_matches:
            exclude("below minimum matches")
            continue
        if innings < req.min_innings:
            exclude("below minimum innings")
            continue
        if role.disc == "allround" and data.dual.get(pid, 0) < req.min_dual_matches:
            exclude("too few matches using both disciplines")
            continue
        reason = _passes_identity(pid, data, req)
        if reason:
            exclude(reason)
            continue
        result = evaluate_candidate(pid, data, role, req, cohorts, weights)
        failed = None
        for metric, op, value in req.bounds:
            part = next((m for m in result["metrics"] if m["metric"] == metric), None)
            observed = part["value"] if part else _observed(metric, pid, data, cohorts)
            if observed is None:
                failed = f"no evidence for {METRICS[metric].label.lower()}"
                break
            if (op == "min" and observed < value) or (op == "max" and observed > value):
                failed = f"{METRICS[metric].label.lower()} requirement"
                break
        if failed:
            exclude(failed)
            continue
        if req.min_tier == "Established" and result["tier"] != "Established":
            exclude("evidence tier below requested")
            continue
        if req.min_tier and req.min_tier.startswith("Promising") and result["tier"] == "Insufficient data":
            exclude("evidence tier below requested")
            continue
        result["sample"] = _sample_summary(pid, data, discs)
        candidates.append(result)

    candidates.sort(key=lambda c: (c["score"] is not None, c["score"] or 0, c.get("reliability") or 0), reverse=True)
    for i, c in enumerate(candidates, start=1):
        c["rank"] = i
        cohort_label = f"{role.label.lower()}s" if role.disc != "allround" else "regulars"
        size = len(cohorts[discs[0]].members)
        c["strengths"], c["weaknesses"] = narrative(c["metrics"], cohort_label, size)

    group_map = role.metric_groups(scope.match_format)
    return {
        "scope": scope.describe(),
        "role": {"key": role.key, "label": role.label, "rationale": role.rationale,
                 "positions": list(positions or role.positions or []) or None},
        "comparison_group": {d: {"size": len(cohorts[d].members), "note": cohorts[d].fallback_note,
                                 "priors": {k: (p.as_dict() if p else None) for k, p in cohorts[d].priors.items()}}
                             for d in discs},
        "weights": {d: [{"metric": k, "label": METRICS[k].label, "group": group_map.get(k, "Custom"), "weight": round(w, 4)}
                        for k, w in weights[d].items()] for d in discs},
        "total_candidates": len(candidates),
        "pool_size": len(pool),
        "exclusions": [{"reason": k, "players": v} for k, v in sorted(exclusions.items(), key=lambda x: -x[1])],
        "candidates": candidates[:limit],
        "thresholds": th,
    }


def _observed(metric: str, pid: str, data: ScopeData, cohorts: Dict[str, Cohort]) -> Optional[float]:
    spec = METRICS[metric]
    cohort = cohorts.get(spec.disc)
    row = (data.bat if spec.disc == "bat" else data.bowl).get(pid)
    if not row:
        return None
    priors = cohort.priors if cohort else {}
    return evaluate_player(row, priors, spec.disc).get(metric, {}).get("value")


def _sample_summary(pid: str, data: ScopeData, discs: Sequence[str]) -> dict:
    out = {}
    bat, bowl = data.bat.get(pid), data.bowl.get(pid)
    if bat and "bat" in discs:
        out["batting"] = {"matches": bat["matches"], "innings": bat["innings"], "runs": bat["runs"], "balls": bat["balls"],
                          "dismissals": bat["outs"], "pace_balls": bat["pace_balls"], "spin_balls": bat["spin_balls"],
                          "classified_share": round((bat["pace_balls"] + bat["spin_balls"]) / bat["balls"], 3) if bat["balls"] else None,
                          "last_date": bat["last_date"].isoformat() if bat.get("last_date") else None}
    if bowl and "bowl" in discs:
        out["bowling"] = {"matches": bowl["matches"], "innings": bowl["innings"], "wickets": bowl["wickets"],
                          "legal_balls": bowl["legal_balls"], "runs": bowl["runs"],
                          "last_date": bowl["last_date"].isoformat() if bowl.get("last_date") else None}
    if "bat" in discs and "bowl" in discs:
        out["dual_matches"] = data.dual.get(pid, 0)
    return out


def role_fit(db: Session, scope: Scope, pid: str) -> List[dict]:
    """Score one player under every applicable role model (shows role-dependence)."""
    data = load_scope(db, scope)
    results = []
    for role in ROLES.values():
        if role.limited_only and scope.match_format not in LIMITED:
            continue
        discs = ("bat", "bowl") if role.disc == "allround" else (role.disc,)
        rows_present = all((data.bat if d == "bat" else data.bowl).get(pid) for d in discs)
        if not rows_present:
            continue
        eligible = role_eligible(role, pid, data) if role.disc != "allround" else True
        cohorts = {d: build_cohort(data, role, d) for d in discs}
        weights = _role_weights(role, scope.match_format, None)
        res = evaluate_candidate(pid, data, role, Requirements(role=role.key), cohorts, weights)
        size = len(cohorts[discs[0]].members)
        results.append({"role": role.key, "label": role.label, "eligible": eligible, "score": res["score"],
                        "reliability": res["reliability"], "tier": res["tier"], "comparison_group": size,
                        "allrounder_type": res.get("allrounder_type"),
                        "eligibility_note": None if eligible else _ineligible_reason(role, pid, data)})
    results.sort(key=lambda r: (r["eligible"], r["score"] or 0), reverse=True)
    return results


def _ineligible_reason(role: RoleModel, pid: str, data: ScopeData) -> str:
    if role.positions:
        share = position_share(data.bat.get(pid), role.positions)
        return f"{share:.0%} of innings at positions {', '.join(map(str, role.positions))} (role needs ≥{POSITION_SHARE:.0%})"
    if role.bowling_type:
        cls = bowling_class(data.attrs.get(pid, {}))
        return f"bowling classification: {cls or 'not sourced'}"
    if role.requires_keeper:
        return "no stumping evidence or wicketkeeper metadata in this scope"
    return "not eligible"
