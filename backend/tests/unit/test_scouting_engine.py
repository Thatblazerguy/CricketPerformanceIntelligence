"""Role models, ranking, reliability and evidence generation on synthetic cohorts (no DB)."""
import itertools
import random

import pytest

from app.analytics import scouting_engine as eng
from app.analytics.scouting_roles import BAT_METRICS, BOWL_METRICS, METRICS, ROLES, thresholds

_counter = itertools.count()

BAT_FIELDS = {"innings", "matches", "runs", "balls", "runs_sq", "outs", "fours", "sixes", "boundaries", "dots", "rotations",
              "exp_runs", "exp_pp_runs", "exp_mid_runs", "exp_death_runs", "pos_1_2", "pos_3", "pos_4", "pos_5", "pos_6",
              "pos_7", "pos_8_plus"}
for _m in BAT_METRICS:
    BAT_FIELDS |= {f for f in (_m.num, _m.den, _m.sumsq) if f}
BOWL_FIELDS = {"innings", "matches", "legal_balls", "runs", "runs_sq", "wickets", "exp_runs", "par_rpb", "wides", "noballs"}
for _m in BOWL_METRICS:
    BOWL_FIELDS |= {f for f in (_m.num, _m.den, _m.sumsq) if f}


def bat_row(innings, balls, sr, avg, *, pos="pos_3", boundary=0.15, dot=0.33, phase_share=(0.3, 0.5, 0.2),
            phase_sr=None, pace_share=0.5, env_rpb=1.25, sig=0.25, **extra):
    row = {f: 0 for f in BAT_FIELDS}
    runs = round(balls * sr / 100)
    outs = max(1, round(runs / avg)) if avg else 0
    row.update(innings=innings, matches=innings, balls=balls, runs=runs, outs=outs, runs_sq=round(balls * 4.2),
               boundaries=round(balls * boundary), fours=round(balls * boundary * 0.7), sixes=round(balls * boundary * 0.3),
               dots=round(balls * dot), rotations=round(balls * (1 - boundary - dot)), exp_runs=balls * env_rpb)
    row[pos] = innings
    for share, ph, psr in zip(phase_share, ("pp", "mid", "death"), phase_sr or (sr, sr, sr)):
        b = round(balls * share)
        row[f"{ph}_balls"], row[f"{ph}_runs"] = b, round(b * psr / 100)
        row[f"{ph}_outs"] = round(outs * share)
        row[f"exp_{ph}_runs"] = b * env_rpb
    for style, share in (("pace", pace_share), ("spin", 1 - pace_share)):
        row[f"{style}_balls"] = round(balls * share)
        row[f"{style}_runs"] = round(runs * share)
        row[f"{style}_outs"] = round(outs * share)
    row["sig_innings"] = round(innings * sig)
    rng = random.Random(innings * 7919 + balls)
    row["fail_innings"] = round(innings * rng.uniform(0.2, 0.4))
    row["early_outs"], row["early_eligible"] = round(innings * rng.uniform(0.1, 0.3)), innings
    row.update(extra)
    return row


def bowl_row(innings, balls, econ, sr, *, env_rpb=1.3):
    row = {f: 0 for f in BOWL_FIELDS}
    runs = round(balls * econ / 6)
    row.update(innings=innings, matches=innings, legal_balls=balls, runs=runs, runs_sq=round(balls * 4.5),
               wickets=round(balls / sr), dots=round(balls * 0.38), boundaries=round(balls * 0.12),
               exp_runs=balls * env_rpb, par_rpb=env_rpb, spells=innings, good_spells=round(innings * 0.5),
               wicketless=round(innings * 0.3), hauls=round(innings * 0.1))
    for share, ph in zip((0.3, 0.45, 0.25), ("pp", "mid", "death")):
        b = round(balls * share)
        row[f"{ph}_balls"], row[f"{ph}_runs"], row[f"{ph}_wkts"] = b, round(b * econ / 6), round(b / sr)
        row[f"{ph}_dots"] = round(b * 0.38)
    return row


def make_scope_data(bat=None, bowl=None, attrs=None, keepers=None, dual=None, fmt="T20"):
    # A unique gender keeps synthetic cohorts out of each other's cache entries.
    scope = eng.Scope(fmt, f"synthetic-{next(_counter)}")
    return eng.ScopeData(scope, bat or {}, bowl or {}, attrs or {}, keepers or {}, dual or {}, thresholds(fmt))


def random_batters(n=80, seed=3, **kw):
    rng = random.Random(seed)
    return {f"b{i}": bat_row(rng.randint(15, 90), rng.randint(300, 2500), rng.gauss(128, 12), rng.gauss(26, 6),
                             boundary=rng.gauss(0.15, 0.03), dot=rng.gauss(0.34, 0.04), sig=rng.gauss(0.25, 0.07),
                             pace_share=rng.uniform(0.4, 0.6), **kw)
            for i in range(n)}


def rank_ids(data, role_key, **req):
    role = ROLES[role_key]
    discs = ("bat", "bowl") if role.disc == "allround" else (role.disc,)
    cohorts = {d: eng.build_cohort(data, role, d) for d in discs}
    weights = eng._role_weights(role, data.scope.match_format, req.pop("weights", None))
    out = {}
    pool = data.bat if role.disc == "bat" else data.bowl
    for pid in pool:
        if role.disc != "allround" and not eng.role_eligible(role, pid, data):
            continue
        out[pid] = eng.evaluate_candidate(pid, data, role, eng.Requirements(role=role_key, **req), cohorts, weights)
    return out


def test_default_weights_are_equal_per_group_and_sum_to_one():
    for role in ROLES.values():
        for fmt in ("T20", "Test"):
            if role.limited_only and fmt == "Test":
                continue
            weights = role.default_weights(fmt, role.groups_for(fmt))
            assert sum(weights.values()) == pytest.approx(1.0)
            if fmt == "Test":
                assert not any(METRICS[k].limited_only for k in weights), role.key
    w = ROLES["middle_order"].default_weights("T20")
    assert w["spin_sr"] == pytest.approx(w["spin_avg"]) == pytest.approx(w["pressure_avg"] / 2)


def test_three_innings_cameo_does_not_outrank_sustained_quality():
    bat = random_batters()
    bat["cameo"] = bat_row(3, 90, 167, 50)       # 150 runs in 3 innings
    bat["proven"] = bat_row(40, 1100, 136, 37)   # 1,500 runs across 40 innings
    data = make_scope_data(bat=bat)
    res = rank_ids(data, "batter")
    assert res["proven"]["score"] > res["cameo"]["score"]
    assert res["proven"]["tier"] == "Established"
    assert res["cameo"]["tier"] == "Insufficient data"
    # Low sample is not penalised as poor performance: the cameo stays near the middle, not the bottom.
    scores = sorted(r["score"] for r in res.values())
    assert res["cameo"]["score"] > scores[len(scores) // 4]


def test_missing_metrics_are_omitted_not_zeroed():
    bat = random_batters()
    no_spin = bat_row(30, 900, 140, 32, pace_share=1.0)
    no_spin.update(spin_balls=0, spin_runs=0, spin_outs=0)
    bat["pace_only"] = no_spin
    data = make_scope_data(bat=bat)
    res = rank_ids(data, "middle_order")["pace_only"]
    spin = next(m for m in res["metrics"] if m["metric"] == "spin_sr")
    assert spin["value"] is None and spin["percentile"] is None and spin["contribution"] is None
    assert res["score"] is not None


def test_player_can_rank_high_for_one_profile_and_low_for_another():
    bat = random_batters(pos="pos_1_2")
    # Explosive at the death, poor and slow in the powerplay.
    bat["finisher"] = bat_row(60, 1500, 150, 30, pos="pos_1_2", phase_share=(0.25, 0.4, 0.35),
                              phase_sr=(95, 140, 205), boundary=0.22)
    data = make_scope_data(bat=bat)
    opener_scores = {k: v["score"] for k, v in rank_ids(data, "opener").items()}
    pp = sorted(opener_scores.values(), reverse=True).index(opener_scores["finisher"])
    custom = rank_ids(data, "opener", weights={"death_sr_index": 1, "acceleration": 1})
    death_rank = sorted((v["score"] for v in custom.values()), reverse=True).index(custom["finisher"]["score"])
    assert death_rank < pp
    assert death_rank <= 2


def test_role_eligibility_rules():
    bat = random_batters(n=40)
    bat["opener"] = bat_row(40, 900, 130, 30, pos="pos_1_2")
    bat["keeper"] = bat_row(40, 900, 130, 30, pos="pos_6")
    bowl = {"pacer": bowl_row(40, 900, 7.5, 18), "spinner": bowl_row(40, 900, 7.0, 20), "unknown": bowl_row(40, 900, 7, 20)}
    attrs = {"pacer": {"bowling_type": "Pace"}, "spinner": {"bowling_type": "Spin"}}
    data = make_scope_data(bat=bat, bowl=bowl, attrs=attrs, keepers={"keeper": 4})
    assert eng.role_eligible(ROLES["opener"], "opener", data)
    assert not eng.role_eligible(ROLES["middle_order"], "opener", data)
    assert eng.role_eligible(ROLES["wicketkeeper_batter"], "keeper", data)
    assert not eng.role_eligible(ROLES["wicketkeeper_batter"], "opener", data)
    assert eng.role_eligible(ROLES["pace_bowler"], "pacer", data)
    assert not eng.role_eligible(ROLES["spin_bowler"], "pacer", data)
    assert not eng.role_eligible(ROLES["pace_bowler"], "unknown", data)  # unclassified never guessed
    assert eng.role_eligible(ROLES["bowler"], "unknown", data)


def test_lower_is_better_metrics_rank_economical_bowlers_higher():
    rng = random.Random(5)
    bowl = {f"w{i}": bowl_row(30, rng.randint(400, 1500), rng.gauss(8, 0.7), rng.gauss(20, 3)) for i in range(60)}
    bowl["miser"] = bowl_row(50, 1200, 6.1, 19)
    bowl["leaky"] = bowl_row(50, 1200, 9.9, 19)
    data = make_scope_data(bowl=bowl)
    res = rank_ids(data, "bowler")
    econ = lambda pid: next(m for m in res[pid]["metrics"] if m["metric"] == "econ_index")
    assert econ("miser")["percentile"] > 90 > 10 > econ("leaky")["percentile"]
    assert res["miser"]["score"] > res["leaky"]["score"]


def test_allrounder_needs_quality_in_both_disciplines():
    assert eng.allrounder_type(70, 65).startswith("Genuine")
    assert eng.allrounder_type(70, 40) == "Batting all-rounder"
    assert eng.allrounder_type(38, 72) == "Bowling all-rounder"
    assert eng.allrounder_type(70, 10).startswith("Batter who bowls")
    assert eng.allrounder_type(20, 20).startswith("Not an effective")
    assert eng.allrounder_type(None, 80).startswith("Insufficient")


def test_strengths_and_weaknesses_cite_numbers_and_comparison_group():
    bat = random_batters()
    bat["star"] = bat_row(80, 2500, 165, 45, boundary=0.24, dot=0.25, sig=0.5)
    data = make_scope_data(bat=bat)
    star = rank_ids(data, "batter")["star"]
    strengths, _ = eng.narrative(star["metrics"], "batters", 81)
    assert strengths
    for line in strengths:
        assert "percentile of 81 batters" in line and "n=" in line and any(ch.isdigit() for ch in line)


def test_requirement_bounds_and_identity_filters():
    req = eng.Requirements(role="batter", nationality="India", bowling_styles=("Left-arm Orthodox",), min_age=20)
    data = make_scope_data(attrs={"a": {"nationality": "India", "bowling_style": "Left-arm Orthodox"},
                                  "b": {"nationality": "India", "bowling_style": "Left-arm Orthodox", "date_of_birth": "1995-01-01"},
                                  "c": {"nationality": "England"}})
    assert eng._passes_identity("a", data, req) == "no verified date of birth"
    assert eng._passes_identity("b", data, req) is None
    assert eng._passes_identity("c", data, req) == "nationality"


def test_position_share_and_weight_normalisation():
    row = bat_row(10, 300, 130, 30, pos="pos_4")
    row["pos_4"], row["pos_5"] = 6, 4
    assert eng.position_share(row, (3, 4, 5)) == 1.0
    assert eng.position_share(row, (1, 2)) == 0.0
    assert eng.normalise_weights({"average": 2, "strike_rate": 2, "bogus": 5}, {"average", "strike_rate"}) == {
        "average": 0.5, "strike_rate": 0.5}
    assert eng.normalise_weights({"average": 0}, {"average"}) == {}
