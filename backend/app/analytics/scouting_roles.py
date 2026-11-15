"""Scouting metric catalogue and role-specific evaluation models.

Each metric is a ratio of stored per-innings sums (see ``scouting_aggregates``)
with an explicit sample unit, direction and shrinkage family. Role models pick
the metrics that describe a role and arrange them into *groups*.

Default weighting rule (documented, not hand-tuned)
--------------------------------------------------
CPI has no outcome-validated evidence that one dimension of a role matters more
than another, so the neutral default is **equal weight per group, split equally
among the metrics in the group**. Grouping stops correlated metrics (e.g. strike
rate and boundary %) from double-counting one skill. Recruiters can override
any weight; the response always reports the effective normalised weights.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

LIMITED = {"T20", "T20I", "ODI", "ODM"}
SHORT = {"T20", "T20I"}


@dataclass(frozen=True)
class MetricSpec:
    key: str
    label: str
    disc: str                    # 'bat' | 'bowl'
    num: Optional[str] = None
    den: Optional[str] = None
    kind: str = "proportion"     # proportion | per_unit | exponential | derived
    scale: float = 1.0           # display multiplier (100 for SR/%, 6 for economy)
    higher: bool = True
    unit: str = "balls"
    sumsq: Optional[str] = None  # per-unit sum of squares field (exact unit variance)
    inverse: bool = False        # display 1/rate*scale (balls per wicket)
    limited_only: bool = False   # undefined for Test/MDM (no phases)
    description: str = ""
    decimals: int = 1


def _m(*args, **kwargs) -> MetricSpec:
    return MetricSpec(*args, **kwargs)


BAT_METRICS: List[MetricSpec] = [
    _m("average", "Batting average", "bat", "runs", "outs", "exponential", unit="dismissals",
       description="Runs per dismissal."),
    _m("strike_rate", "Strike rate", "bat", "runs", "balls", "per_unit", 100, sumsq="runs_sq",
       description="Runs per 100 balls faced (wides excluded, no-balls included)."),
    _m("sr_index", "Strike rate (context-adjusted)", "bat", kind="derived",
       description="Shrunk strike rate ÷ the strike rate all batters achieved in the same competition-season "
                   "and phase mix the player batted in, ×100. 100 = environment average."),
    _m("boundary_pct", "Boundary %", "bat", "boundaries", "balls", "proportion", 100,
       description="Share of balls faced hit for four or six."),
    _m("dot_pct", "Dot-ball %", "bat", "dots", "balls", "proportion", 100, higher=False,
       description="Share of balls faced that produced no batter runs."),
    _m("rotation_pct", "Strike rotation %", "bat", "rotations", "balls", "proportion", 100,
       description="Share of balls faced scored as 1, 2 or 3 (non-boundary) runs."),
    _m("balls_per_dismissal", "Balls per dismissal", "bat", "balls", "outs", "exponential", unit="dismissals",
       description="Survival: balls faced per dismissal."),
    _m("pp_sr", "Powerplay strike rate", "bat", "pp_runs", "pp_balls", "per_unit", 100, limited_only=True,
       description="Strike rate in the powerplay (T20 overs 1–6, ODI 1–10)."),
    _m("pp_sr_index", "Powerplay SR (context-adjusted)", "bat", kind="derived", limited_only=True,
       description="Powerplay SR relative to powerplay scoring in the same competition-seasons (100 = average)."),
    _m("pp_avg", "Powerplay average", "bat", "pp_runs", "pp_outs", "exponential", unit="dismissals", limited_only=True),
    _m("mid_sr", "Middle-overs strike rate", "bat", "mid_runs", "mid_balls", "per_unit", 100, limited_only=True,
       description="Strike rate in the middle overs (T20 overs 7–15, ODI 11–40)."),
    _m("mid_sr_index", "Middle-overs SR (context-adjusted)", "bat", kind="derived", limited_only=True),
    _m("mid_avg", "Middle-overs average", "bat", "mid_runs", "mid_outs", "exponential", unit="dismissals", limited_only=True),
    _m("death_sr", "Death-overs strike rate", "bat", "death_runs", "death_balls", "per_unit", 100, limited_only=True,
       description="Strike rate in the death overs (T20 overs 16–20, ODI 41–50)."),
    _m("death_sr_index", "Death-overs SR (context-adjusted)", "bat", kind="derived", limited_only=True),
    _m("death_avg", "Death-overs average", "bat", "death_runs", "death_outs", "exponential", unit="dismissals", limited_only=True),
    _m("pace_sr", "Strike rate vs pace", "bat", "pace_runs", "pace_balls", "per_unit", 100,
       description="Only deliveries from bowlers with a sourced pace classification."),
    _m("pace_avg", "Average vs pace", "bat", "pace_runs", "pace_outs", "exponential", unit="dismissals"),
    _m("spin_sr", "Strike rate vs spin", "bat", "spin_runs", "spin_balls", "per_unit", 100,
       description="Only deliveries from bowlers with a sourced spin classification."),
    _m("spin_avg", "Average vs spin", "bat", "spin_runs", "spin_outs", "exponential", unit="dismissals"),
    _m("weaker_style_sr", "Strike rate vs weaker style", "bat", kind="derived",
       description="The lower of shrunk SR vs pace and vs spin: rewards no obvious matchup weakness."),
    _m("early_out_pct", "Early dismissal %", "bat", "early_outs", "early_eligible", "proportion", 100, higher=False,
       unit="innings", description="Share of innings ending in dismissal within the first 10 balls faced "
                                   "(denominator: innings that were either dismissed or lasted beyond 10 balls)."),
    _m("significant_pct", "Significant-contribution %", "bat", "sig_innings", "innings", "proportion", 100, unit="innings",
       description="Share of innings reaching the format's significant score (T20 30+, ODI/Test 50+)."),
    _m("failure_pct", "Failure %", "bat", "fail_innings", "innings", "proportion", 100, higher=False, unit="innings",
       description="Share of innings dismissed below the format's failure line (T20 <10, ODI <15, Test <10)."),
    _m("pressure_avg", "Average after early collapse", "bat", "pressure_runs", "pressure_outs", "exponential",
       unit="dismissals", limited_only=True,
       description="Runs per dismissal in innings begun with 2+ wickets down inside the powerplay."),
    _m("chase_avg", "Average when chasing", "bat", "chase_runs", "chase_outs", "exponential", unit="dismissals",
       limited_only=True),
    _m("chase_sr", "Strike rate when chasing", "bat", "chase_runs", "chase_balls", "per_unit", 100, limited_only=True),
    _m("chase_finish_pct", "Unbeaten in successful chases %", "bat", "chase_won_notouts", "chase_won_innings",
       "proportion", 100, unit="innings", limited_only=True,
       description="Share of innings in chases the team won in which the batter was not out at the finish."),
    _m("acceleration", "Death-over acceleration", "bat", kind="derived", limited_only=True,
       description="Shrunk death-overs SR minus shrunk SR before the death overs."),
]

BOWL_METRICS: List[MetricSpec] = [
    _m("economy", "Economy", "bowl", "runs", "legal_balls", "per_unit", 6, higher=False, sumsq="runs_sq",
       description="Runs conceded (incl. wides/no-balls, excl. byes/leg-byes) per six legal balls.", decimals=2),
    _m("econ_index", "Economy (context-adjusted)", "bowl", kind="derived", higher=False,
       description="Shrunk economy ÷ economy of all bowlers in the same competition-season and phase mix, ×100. "
                   "Below 100 is better than the environment."),
    _m("bowling_average", "Bowling average", "bowl", "runs", "wickets", "exponential", higher=False, unit="wickets",
       description="Runs conceded per wicket."),
    _m("bowling_strike_rate", "Bowling strike rate", "bowl", "wickets", "legal_balls", "proportion", 1, higher=True,
       inverse=True, description="Legal balls per wicket (ranked on wicket rate per ball)."),
    _m("bowl_dot_pct", "Dot-ball %", "bowl", "dots", "legal_balls", "proportion", 100,
       description="Share of legal balls with no runs charged to the bowler."),
    _m("boundary_pct_conceded", "Boundary % conceded", "bowl", "boundaries", "legal_balls", "proportion", 100, higher=False),
    _m("pp_economy", "Powerplay economy", "bowl", "pp_runs", "pp_balls", "per_unit", 6, higher=False, limited_only=True, decimals=2),
    _m("pp_strike_rate", "Powerplay balls per wicket", "bowl", "pp_wkts", "pp_balls", "proportion", 1, inverse=True,
       limited_only=True),
    _m("mid_economy", "Middle-overs economy", "bowl", "mid_runs", "mid_balls", "per_unit", 6, higher=False, limited_only=True, decimals=2),
    _m("mid_strike_rate", "Middle-overs balls per wicket", "bowl", "mid_wkts", "mid_balls", "proportion", 1, inverse=True,
       limited_only=True),
    _m("death_economy", "Death-overs economy", "bowl", "death_runs", "death_balls", "per_unit", 6, higher=False, limited_only=True, decimals=2),
    _m("death_strike_rate", "Death-overs balls per wicket", "bowl", "death_wkts", "death_balls", "proportion", 1, inverse=True,
       limited_only=True),
    _m("death_dot_pct", "Death-overs dot %", "bowl", "death_dots", "death_balls", "proportion", 100, limited_only=True),
    _m("good_spell_pct", "Economical-spell %", "bowl", "good_spells", "spells", "proportion", 100, unit="spells",
       description="Share of qualifying spells (T20 ≥12, ODI ≥30, Test ≥60 legal balls) at or below the cohort's "
                   "overall economy."),
    _m("haul_pct", "Haul %", "bowl", "hauls", "innings", "proportion", 100, unit="innings",
       description="Share of bowling innings with a haul (T20 3+, ODI 4+, Test 5+ wickets)."),
    _m("wicketless_pct", "Wicketless-spell %", "bowl", "wicketless", "spells", "proportion", 100, higher=False, unit="spells"),
]

METRICS: Dict[str, MetricSpec] = {m.key: m for m in BAT_METRICS + BOWL_METRICS}


def thresholds(match_format: str) -> dict:
    """Format-specific sample and contribution thresholds (documented in methodology)."""
    if match_format in SHORT:
        return dict(sig=30, poor=10, pp_end=6, bat_innings=10, bat_balls=100, bowl_innings=10, bowl_balls=120,
                    spell_min=12, haul=3, dual_bat_balls=10, dual_bowl_balls=12)
    if match_format in LIMITED:
        return dict(sig=50, poor=15, pp_end=10, bat_innings=10, bat_balls=200, bowl_innings=10, bowl_balls=300,
                    spell_min=30, haul=4, dual_bat_balls=20, dual_bowl_balls=30)
    return dict(sig=50, poor=10, pp_end=0, bat_innings=10, bat_balls=500, bowl_innings=10, bowl_balls=600,
                spell_min=60, haul=5, dual_bat_balls=30, dual_bowl_balls=60)


@dataclass(frozen=True)
class RoleModel:
    key: str
    label: str
    disc: str                                   # 'bat' | 'bowl' | 'allround'
    groups: Tuple[Tuple[str, Tuple[str, ...]], ...]
    positions: Optional[Tuple[int, ...]] = None  # batting-position eligibility (≥50% of innings)
    bowling_type: Optional[str] = None            # 'pace' | 'spin'
    requires_keeper: bool = False
    rationale: str = ""
    bowl_groups: Tuple[Tuple[str, Tuple[str, ...]], ...] = field(default_factory=tuple)
    multi_day_groups: Tuple[Tuple[str, Tuple[str, ...]], ...] = field(default_factory=tuple)
    limited_only: bool = False                    # role not meaningful in Test / multi-day cricket

    def groups_for(self, match_format: str):
        return self.multi_day_groups if (self.multi_day_groups and match_format not in LIMITED) else self.groups

    def default_weights(self, match_format: str, groups=None) -> Dict[str, float]:
        groups = self.groups_for(match_format) if groups is None else groups
        usable = []
        for name, keys in groups:
            keep = tuple(k for k in keys if not (METRICS[k].limited_only and match_format not in LIMITED))
            if keep:
                usable.append((name, keep))
        weights: Dict[str, float] = {}
        for _, keys in usable:
            for key in keys:
                weights[key] = weights.get(key, 0.0) + 1.0 / len(usable) / len(keys)
        return weights

    def metric_groups(self, match_format: str = "T20") -> Dict[str, str]:
        return {k: name for name, keys in self.groups_for(match_format) + self.bowl_groups for k in keys}


ROLES: Dict[str, RoleModel] = {r.key: r for r in [
    RoleModel("opener", "Opening batter", "bat", (
        ("Powerplay scoring", ("pp_sr_index", "boundary_pct")),
        ("Powerplay survival", ("pp_avg", "early_out_pct")),
        ("Scoring pressure", ("dot_pct",)),
        ("Against pace", ("pace_sr", "pace_avg")),
        ("Innings building & consistency", ("balls_per_dismissal", "significant_pct")),
    ), multi_day_groups=(
        ("New-ball survival", ("early_out_pct", "pace_avg")),
        ("Innings building", ("balls_per_dismissal", "average")),
        ("Scoring", ("sr_index", "pace_sr")),
        ("Consistency", ("significant_pct", "failure_pct")),
    ), positions=(1, 2), rationale="Openers face the new ball and fielding restrictions: powerplay scoring and survival, "
                                   "pace matchup and the ability to bat deep define the role."),
    RoleModel("middle_order", "Middle-order batter", "bat", (
        ("Middle-overs scoring", ("mid_sr_index", "rotation_pct")),
        ("Against spin", ("spin_sr", "spin_avg")),
        ("Run accumulation", ("average", "boundary_pct")),
        ("Pressure", ("pressure_avg",)),
        ("Dismissal risk", ("balls_per_dismissal",)),
        ("Consistency", ("significant_pct",)),
    ), multi_day_groups=(
        ("Run accumulation", ("average", "balls_per_dismissal")),
        ("Against spin", ("spin_avg", "spin_sr")),
        ("Scoring", ("sr_index", "rotation_pct")),
        ("Consistency", ("significant_pct", "failure_pct")),
    ), positions=(3, 4, 5), rationale="Middle-order batters mostly face overs 7–15 and spin; rotation, boundary conversion, "
                                      "rebuilding after early wickets and low dismissal risk define the role."),
    RoleModel("finisher", "Finisher", "bat", (
        ("Death hitting", ("death_sr_index", "boundary_pct")),
        ("Death survival", ("death_avg",)),
        ("Scoring pressure", ("dot_pct",)),
        ("Acceleration", ("acceleration",)),
        ("Closing chases", ("chase_finish_pct",)),
        ("Against all bowling", ("weaker_style_sr",)),
    ), positions=(5, 6, 7), limited_only=True, rationale="Finishers must score fast at the death without being dismissed, accelerate late "
                                      "and see successful chases through."),
    RoleModel("wicketkeeper_batter", "Wicketkeeper-batter", "bat", (
        ("Scoring rate", ("sr_index", "boundary_pct")),
        ("Run accumulation", ("average",)),
        ("Strike rotation", ("rotation_pct", "dot_pct")),
        ("Consistency", ("significant_pct", "failure_pct")),
    ), requires_keeper=True, rationale="Keeper identity requires stumping evidence or verified metadata. Wicketkeeping "
                                       "quality itself is not scored: the data cannot attribute catches to the keeper."),
    RoleModel("batter", "Batter (any position)", "bat", (
        ("Scoring rate", ("sr_index", "boundary_pct")),
        ("Run accumulation", ("average",)),
        ("Scoring pressure", ("dot_pct",)),
        ("Matchups", ("pace_sr", "spin_sr")),
        ("Consistency", ("significant_pct", "failure_pct")),
    ), rationale="General batting quality profile for comparisons that should not assume a position."),
    RoleModel("pace_bowler", "Fast / seam bowler", "bowl", (
        ("Control", ("econ_index", "bowl_dot_pct", "boundary_pct_conceded")),
        ("Wicket-taking", ("bowling_strike_rate", "bowling_average")),
        ("Powerplay", ("pp_strike_rate", "pp_economy")),
        ("Death overs", ("death_economy",)),
        ("Consistency", ("good_spell_pct",)),
    ), bowling_type="pace", rationale="Pace bowlers are judged on control, wicket-taking, new-ball and death-overs "
                                      "effectiveness and spell-to-spell consistency."),
    RoleModel("spin_bowler", "Spin bowler", "bowl", (
        ("Control", ("econ_index", "bowl_dot_pct", "boundary_pct_conceded")),
        ("Wicket-taking", ("bowling_strike_rate", "bowling_average")),
        ("Middle overs", ("mid_economy", "mid_strike_rate")),
        ("Consistency", ("good_spell_pct",)),
    ), bowling_type="spin", rationale="Spinners mostly bowl the middle overs: control, wicket-taking and middle-overs "
                                      "effectiveness define the role."),
    RoleModel("bowler", "Bowler (any type)", "bowl", (
        ("Control", ("econ_index", "bowl_dot_pct")),
        ("Wicket-taking", ("bowling_strike_rate", "bowling_average")),
        ("Consistency", ("good_spell_pct",)),
    ), rationale="General bowling profile, including bowlers without a sourced pace/spin classification."),
    RoleModel("all_rounder", "All-rounder", "allround", (
        ("Batting scoring", ("sr_index", "boundary_pct")),
        ("Batting accumulation", ("average",)),
        ("Batting consistency", ("significant_pct",)),
    ), bowl_groups=(
        ("Bowling control", ("econ_index", "bowl_dot_pct")),
        ("Bowling wicket-taking", ("bowling_strike_rate",)),
        ("Bowling consistency", ("good_spell_pct",)),
    ), rationale="Batting and bowling are each scored against regular batters and regular bowlers, then combined. "
                 "Recorded activity in both disciplines is not enough: each contribution must be of measurable quality."),
]}

POSITION_SHARE = 0.5   # role position eligibility: at least half of innings in the role's positions
KEEPER_MIN_STUMPINGS = 1


def role_catalog() -> List[dict]:
    out = []
    for role in ROLES.values():
        out.append({
            "key": role.key, "label": role.label, "discipline": role.disc,
            "positions": list(role.positions) if role.positions else None,
            "bowling_type": role.bowling_type, "requires_keeper": role.requires_keeper,
            "rationale": role.rationale,
            "groups": [{"name": n, "metrics": list(k)} for n, k in role.groups],
            "multi_day_groups": [{"name": n, "metrics": list(k)} for n, k in role.multi_day_groups],
            "limited_overs_only": role.limited_only,
            "bowl_groups": [{"name": n, "metrics": list(k)} for n, k in role.bowl_groups],
        })
    return out


def metric_catalog() -> List[dict]:
    return [{"key": m.key, "label": m.label, "discipline": m.disc, "higher_is_better": m.higher,
             "unit": m.unit, "limited_overs_only": m.limited_only, "description": m.description,
             "kind": m.kind} for m in METRICS.values()]
