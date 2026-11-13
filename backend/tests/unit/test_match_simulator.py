"""Unit tests for the ball-by-ball match engine (no database).

A synthetic calibration with controllable outcome weights lets each rule be
tested deterministically: strike rotation, over completion, extras, wickets,
over limits, chases, ties/super overs, free hits, Tests, reproducibility and
Monte Carlo arithmetic.
"""
from __future__ import annotations

import random
from collections import Counter, defaultdict

import pytest

from app.api.routes.simulator import parse_scoreboard_text
from app.ml import match_simulator as ms
from app.ml.sim_calibration import CLASSES, PHASES
from app.services import match_simulation as svc

DEFAULT = {"R0": 40, "R1": 35, "R2": 8, "R3": 0.5, "R4": 10, "R6": 4, "W": 5, "RO": 0.5, "WD": 3, "NB": 0.6, "B": 0.3, "LB": 1}
ALL_PHASES = sorted({p for ps in PHASES.values() for p in ps})


def make_calibration(weights=None, details=None):
    w = DEFAULT if weights is None else weights
    vec = [float(w.get(c, 0)) * 1000 for c in CLASSES]
    block = {
        "base": {f"{inn}|{ob}|{wk}": list(vec) for inn in (1, 2, 3, 4) for ob in range(20) for wk in range(10)},
        "pressure": {},
        "ref": {f"{p}|{t}": list(vec) for p in ALL_PHASES for t in ("pace", "spin", "unknown", "*")},
        "ref_year": {f"2024|{p}|{t}": list(vec) for p in ALL_PHASES for t in ("pace", "spin", "unknown", "*")},
        "position": {f"{p}|{b}": list(vec) for p in ALL_PHASES for b in ("open", "top", "middle", "tail")},
        "details": details or {"WD": {"1": 10}, "NB": {"0": 10}, "B": {"1": 10}, "LB": {"1": 10}, "RO": {"0": 5, "1": 5}},
        "runout_striker": [1, 1],
        "dismissal_mix": {"*": {"caught": 6, "bowled": 2, "lbw": 1, "stumped": 1}},
        "toss": {"bat": 1, "field": 1},
        "deliveries": 1, "innings_totals": {},
    }
    return {"version": "test", "genders": {"male": block}}


def setup(fmt="T20", weights=None, details=None, profiles=None, keeper=True):
    rules = ms.rules_for(fmt)
    a = [f"a{i}" for i in range(1, 12)]
    b = [f"b{i}" for i in range(1, 12)]
    positions = {p: i + 1 for i, p in enumerate(a)}
    positions.update({p: i + 1 for i, p in enumerate(b)})
    model = ms.SimModel(make_calibration(weights, details), rules.family, "male", profiles or {}, {}, positions=positions,
                        player_exponent=1.0)
    teams = {"A": ms.TeamSetup("A", "Alpha", a, keeper="a1" if keeper else None),
             "B": ms.TeamSetup("B", "Bravo", b, keeper="b1" if keeper else None)}
    return model, rules, teams


def run(fmt="T20", seed=1, **kw):
    model, rules, teams = setup(fmt, **kw)
    res = ms.simulate_match(model, rules, teams, random.Random(seed), toss_winner="A", toss_decision="bat", detailed=True)
    return model, rules, teams, res


# ---------------------------------------------------------------------------
# Over limits, legal balls and extras
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("fmt,limit", [("T20", 4), ("ODI", 10)])
def test_bowlers_respect_over_limits_and_never_bowl_consecutive_overs(fmt, limit):
    for seed in range(15):
        _, _, _, res = run(fmt, seed)
        for inn in res["innings"]:
            if inn.super_over:
                continue
            overs = defaultdict(set)
            for d in inn.deliveries:
                overs[d["over_index"]].add(d["bowler_id"])
            assert all(len(v) == 1 for v in overs.values()), "one bowler per over"
            sequence = [next(iter(overs[o])) for o in sorted(overs)]
            assert all(x != y for x, y in zip(sequence, sequence[1:])), "no consecutive overs"
            assert max(Counter(sequence).values()) <= limit


def test_each_completed_over_has_six_legal_balls_and_extras_do_not_count():
    _, _, _, res = run("T20", 3, weights={**DEFAULT, "WD": 15, "NB": 5})
    inn = res["innings"][0]
    legal = defaultdict(int)
    for d in inn.deliveries:
        legal[d["over_index"]] += int(d["legal"])
        if d["outcome"] in ("WD", "NB"):
            assert not d["legal"]
    last = max(legal)
    assert all(n == 6 for o, n in legal.items() if o != last)
    assert sum(legal.values()) == inn.legal_balls <= 120
    assert inn.extras["wides"] == sum(d["extras"].get("wides", 0) for d in inn.deliveries) > 0
    assert inn.extras["noballs"] == sum(1 for d in inn.deliveries if d["outcome"] == "NB")


def test_runs_reconcile_between_batters_extras_and_bowlers():
    for seed in range(10):
        _, _, _, res = run("T20", seed)
        for inn in res["innings"]:
            bat = sum(r[0] for r in inn.bat.values())
            extras = sum(inn.extras.values())
            bowl = sum(r[1] for r in inn.bowl.values()) + inn.extras["byes"] + inn.extras["legbyes"]
            assert bat + extras == inn.runs == bowl
            assert sum(r[0] for r in inn.bowl.values()) == inn.legal_balls
            bowler_wkts = sum(r[2] for r in inn.bowl.values())
            run_outs = sum(1 for d in inn.deliveries if d["wicket"] and d["wicket"]["kind"] == "run out")
            assert bowler_wkts + run_outs == inn.wickets


# ---------------------------------------------------------------------------
# Strike rotation, wickets and innings completion
# ---------------------------------------------------------------------------

def test_single_runs_rotate_strike_and_over_end_cancels_the_swap():
    _, _, _, res = run("T20", 1, weights={"R1": 1})
    balls = res["innings"][0].deliveries
    for prev, cur in zip(balls, balls[1:]):
        if prev["over_index"] == cur["over_index"]:
            assert cur["batter_id"] != prev["batter_id"]
        else:  # odd run + change of ends => same batter faces the first ball of the next over
            assert cur["batter_id"] == prev["batter_id"]
    assert res["innings"][0].runs == 120 and res["innings"][0].wickets == 0


def test_dot_balls_keep_strike_until_the_over_ends():
    _, _, _, res = run("T20", 1, weights={"R0": 1})
    balls = res["innings"][0].deliveries
    by_over = defaultdict(set)
    for d in balls:
        by_over[d["over_index"]].add(d["batter_id"])
    assert all(len(v) == 1 for v in by_over.values())
    assert by_over[0] != by_over[1]


def test_wickets_bring_in_batters_in_order_and_ten_wickets_end_the_innings():
    _, _, teams, res = run("T20", 2, weights={"W": 1})
    inn = res["innings"][0]
    assert inn.wickets == 10 and inn.all_out and inn.legal_balls == 10
    assert inn.batting_order_used == teams["A"].order
    outs = [d["wicket"]["player_out"] for d in inn.deliveries]
    assert len(set(outs)) == 10
    for d in inn.deliveries:  # bowler-credited dismissal => incoming batter faces next
        assert d["wicket"]["bowler_credited"]


def test_innings_stops_at_the_over_limit():
    _, _, _, res = run("T20", 4, weights={"R1": 1, "R0": 1})
    assert res["innings"][0].legal_balls == 120 and not res["innings"][0].all_out


def test_chase_ends_as_soon_as_target_is_reached():
    for seed in range(20):
        _, _, _, res = run("T20", seed)
        i1, i2 = res["innings"][:2]
        assert i2.target == i1.runs + 1
        if i2.runs >= i2.target:
            assert res["winner"] == i2.batting and res["method"] == "wickets"
            assert i2.runs - i2.deliveries[-1]["total_runs"] < i2.target  # last ball crossed the line
            assert res["margin_wickets"] == 10 - i2.wickets
        elif i2.runs < i1.runs:
            assert res["winner"] == i1.batting and res["margin_runs"] == i1.runs - i2.runs


def test_tied_match_goes_to_super_overs_and_repeats():
    _, _, teams, res = run("T20", 1, weights={"R0": 1})
    assert res["tie"] is True
    so = [i for i in res["innings"] if i.super_over]
    assert so and len(so) % 2 == 0 and len(so) <= 10
    assert all(i.legal_balls <= 6 and i.wickets <= 2 for i in so)
    assert res["winner"] is None  # 0-0 every time: still tied after the cap
    assert ms.result_text(res, teams) == "Match tied"


def test_super_over_disabled_leaves_a_tie():
    model, _, teams = setup("T20", weights={"R0": 1})
    rules = ms.rules_for("T20", super_over=False)
    res = ms.simulate_match(model, rules, teams, random.Random(1), toss_winner="A", toss_decision="bat")
    assert res["tie"] and not any(i.super_over for i in res["innings"])


def test_free_hit_follows_a_no_ball_and_protects_from_bowler_dismissals():
    _, _, _, res = run("T20", 5, weights={"NB": 3, "W": 3, "R0": 4})
    free = [d for i in res["innings"] for d in i.deliveries if d["free_hit"]]
    assert free, "expected free hits after no-balls"
    for i in res["innings"]:
        for prev, cur in zip(i.deliveries, i.deliveries[1:]):
            if prev["outcome"] == "NB":
                assert cur["free_hit"]
    assert all(not (d["wicket"] and d["wicket"]["bowler_credited"]) for d in free)


def test_shortened_match_scales_bowler_limits():
    rules = ms.rules_for("ODI", overs=20)
    assert rules.overs == 20 and rules.max_bowler_overs == 4
    with pytest.raises(ValueError):
        ms.rules_for("T20", overs=25)
    with pytest.raises(ValueError):
        ms.rules_for("Hundred")


def test_can_cover_checks_quota_and_no_consecutive_overs():
    assert ms.can_cover({"a": 4, "b": 4, "c": 4, "d": 4, "e": 4}, None, 20)
    assert not ms.can_cover({"a": 4, "b": 4, "c": 4, "d": 4}, None, 20)
    assert not ms.can_cover({"a": 10, "b": 0}, None, 3)  # a cannot bowl back-to-back
    assert ms.can_cover({"a": 2, "b": 1}, None, 3)
    assert not ms.can_cover({"a": 2, "b": 1}, "a", 3)


def test_test_match_follows_innings_rules():
    results = Counter()
    for seed in range(12):
        _, rules, teams, res = run("Test", seed)
        main = [i for i in res["innings"] if not i.super_over]
        assert 2 <= len(main) <= 4
        assert res["method"] in {"runs", "wickets", "innings", "draw", "tie"}
        assert sum(-(-i.legal_balls // 6) for i in main) <= rules.match_overs
        results[res["method"]] += 1
        if res["method"] == "innings":
            assert len(main) == 3
    assert sum(results.values()) == 12


# ---------------------------------------------------------------------------
# Calibration maths
# ---------------------------------------------------------------------------

def test_player_ratios_are_shrunk_more_for_small_samples():
    league = [float(DEFAULT.get(c, 0)) for c in CLASSES]
    hitter = list(league)
    hitter[CLASSES.index("R6")] *= 2  # twice the league six rate

    def profile(scale):
        return {"bat": {f"middle|unknown|2024": [x * scale for x in hitter]}, "bowl": {}, "bat_balls": int(sum(hitter) * scale),
                "bowl_balls": 0, "bowl_phase_balls": {}, "dismissals": {}}
    model = ms.SimModel(make_calibration(), "T20", "male", {"small": profile(0.5), "big": profile(50)}, {},
                        positions={"small": 3, "big": 3}, player_exponent=1.0)
    six = CLASSES.index("R6")
    small, big = model.bat_ratio["small"]["middle|unknown"][six], model.bat_ratio["big"]["middle|unknown"][six]
    assert 1.0 < small < big < 2.0
    probs = model.probabilities("big", "small", 1, 10, 2)
    assert abs(sum(probs.values()) - 1) < 1e-9


def test_free_hit_probabilities_have_no_bowler_wicket():
    model, _, _ = setup()
    p = model.probabilities("a1", "b11", 1, 3, 0, free_hit=True)
    assert p["W"] == 0 and abs(sum(p.values()) - 1) < 1e-9


# ---------------------------------------------------------------------------
# Reproducibility and Monte Carlo
# ---------------------------------------------------------------------------

def test_seeded_runs_are_reproducible_and_batch_independent():
    model, rules, teams = setup()
    one = ms.run_batch(model, rules, teams, 99, 0, 20)
    two = ms.run_batch(model, rules, teams, 99, 0, 20)
    split = ms.run_batch(model, rules, teams, 99, 0, 7) + ms.run_batch(model, rules, teams, 99, 7, 13)
    other = ms.run_batch(model, rules, teams, 100, 0, 20)
    assert one == two == split
    assert one != other


def _summary(winner, first, second, tie=False, method="runs", so=False, toss="A"):
    return {"winner": winner, "tie": tie, "method": method, "super_over": so, "toss": {"winner": toss, "decision": "bat"},
            "batting_first": first[0], "margin_runs": None, "margin_wickets": None,
            "innings": [(first[0], first[1], first[2], 120, False), (second[0], second[1], second[2], 100, False)],
            "players": {"a1": (50, 30, 1, 0, 0, 0, 0, 60.0), "b1": (10, 12, 1, 2, 30, 24, 1, 40.0)}, "potm": "a1"}


def test_monte_carlo_aggregation_maths():
    _, rules, teams = setup()
    sims = [
        _summary("A", ("A", 180, 6), ("B", 150, 10)),
        _summary("B", ("A", 160, 7), ("B", 161, 4), method="wickets"),
        _summary("B", ("B", 200, 5), ("A", 170, 9)),
        _summary("A", ("B", 140, 10), ("A", 141, 3), method="wickets"),
        _summary(None, ("A", 150, 8), ("B", 150, 9), tie=True, method="tie"),
    ]
    agg = ms.aggregate_monte_carlo(sims, teams, rules)
    assert agg["simulations"] == 5
    assert agg["win_pct"] == {"A": 40.0, "B": 40.0}
    assert agg["tie_pct"] == 20.0
    assert agg["avg_first_innings"] == round((180 + 160 + 200 + 140 + 150) / 5, 2)
    assert agg["avg_first_innings_by_team"] == {"A": round((180 + 160 + 150) / 3, 2), "B": 170.0}
    assert agg["avg_successful_chase"] == round((161 + 141) / 2, 2) and agg["successful_chases"] == 2
    assert agg["chase_success_pct"] == 40.0
    assert agg["avg_wickets_lost"]["A"] == round((6 + 7 + 9 + 3 + 8) / 5, 2)
    assert sum(b["count"] for b in agg["distributions"]["first_innings"]) == 5
    top = {p["player_id"]: p for p in agg["all_players"]}
    assert top["a1"]["potm_pct"] == 100.0 and top["a1"]["avg_runs"] == 50.0
    assert top["b1"]["economy"] == 7.5


def test_monte_carlo_service_caps_and_reports_actual_outcomes(monkeypatch):
    model, rules, teams = setup()
    ctx = {"model": model, "rules": rules, "teams": teams, "conditions": {}, "meta": {}}
    seen = []
    agg = svc.monte_carlo(ctx, 40, 5, lambda done, total: seen.append((done, total)))
    assert agg["simulations"] == 40 and seen[-1] == (40, 40)
    wins = sum(agg["win_pct"].values())
    # Every match has a winner except ties that survive the super overs (a subset of regulation ties).
    assert wins <= 100 and wins + agg["tie_pct"] >= 99.99
    monkeypatch.setitem(svc.MAX_SIMULATIONS, "T20", 25)
    capped = svc.monte_carlo(ctx, 1000, 5)
    assert capped["simulations"] == 25 and capped["requested"] == 1000 and capped["capped_at"] == 25


# ---------------------------------------------------------------------------
# Detailed match output
# ---------------------------------------------------------------------------

def test_detailed_scorecards_reconcile_and_include_analysis():
    model, rules, teams = setup()
    meta = {p: {"name": p.upper()} for t in teams.values() for p in t.order}
    ctx = {"model": model, "rules": rules, "teams": teams, "meta": meta, "gender": "male",
           "conditions": {"toss_winner": "A", "toss_decision": "bat"}}
    for seed in (1, 2, 3):
        out = svc.detailed_match(ctx, seed, wp_sims=100)
        for inn in out["innings"]:
            card = inn["scorecard"]
            assert card["reconciliation"]["balanced"], card["reconciliation"]
            assert len(card["fall_of_wickets"]) == inn["wickets"]
            assert sum(p["runs"] for p in card["partnerships"]) == inn["runs"]
            assert sum(o["runs"] for o in card["overs_progression"]) == inn["runs"]
            if not inn["super_over"]:
                assert len(card["batting"]) == 11
        assert out["player_of_match"]["player_id"] in meta
        assert out["summary"][0].startswith(out["result"])
        wp = out["win_probability"]
        assert wp["available"] and 0 <= wp["points"][0]["team_a"] <= 1
    assert svc.detailed_match(ctx, 7, wp_sims=100)["innings"][0]["runs"] == svc.detailed_match(ctx, 7, wp_sims=100)["innings"][0]["runs"]


def test_scoreboard_parser_leaves_unknown_values_unset():
    state = parse_scoreboard_text("T20 · India 124/3 · 15.2 overs · Target 180 · Required RR 10.5")
    assert state["format"] == "T20"
    assert state["score"] == 124 and state["wickets"] == 3
    assert state["legal_balls"] == 92 and state["target_runs"] == 180
    assert state["uncertain_fields"] == []
    unknown = parse_scoreboard_text("live cricket")
    assert unknown["score"] is None and "score" in unknown["uncertain_fields"]


# ---------------------------------------------------------------------------
# XI validation (structural; database checks are in the integration tests)
# ---------------------------------------------------------------------------

def _xi(prefix, n=11):
    return [{"id": f"{prefix}{i}", "name": f"{prefix.upper()} {i}"} for i in range(1, n + 1)]


def _payload(a=None, b=None, **extra):
    return {"format": "T20", "teams": {"A": {"name": "Alpha", "players": a if a is not None else _xi("a")},
                                       "B": {"name": "Bravo", "players": b if b is not None else _xi("b")}}, **extra}


def test_valid_xis_pass_structural_validation():
    assert svc.validate_payload_shape(_payload()) == []


def test_xi_must_have_exactly_eleven_players():
    errors = svc.validate_payload_shape(_payload(a=_xi("a", 10)))
    assert any("exactly 11" in e and "Alpha" in e for e in errors)


def test_duplicate_player_in_one_xi_is_rejected():
    a = _xi("a")
    a[10] = dict(a[3])
    errors = svc.validate_payload_shape(_payload(a=a))
    assert any("duplicate" in e for e in errors)


def test_player_in_both_xis_is_rejected():
    b = _xi("b")
    b[0] = {"id": "a1", "name": "A 1"}
    errors = svc.validate_payload_shape(_payload(b=b))
    assert any("both XIs" in e for e in errors)


def test_unmatched_players_are_reported_by_name():
    a = _xi("a")
    a[5] = {"id": None, "input_name": "Not A Real Cricketer"}
    errors = svc.validate_payload_shape(_payload(a=a))
    assert any("Not A Real Cricketer" in e for e in errors)


def test_invalid_conditions_and_formats_are_rejected():
    assert svc.validate_payload_shape(_payload(conditions={"pitch": "lava"}))
    assert svc.validate_payload_shape(_payload(conditions={"toss_winner": "C"}))
    assert svc.validate_payload_shape({**_payload(), "format": "Hundred"})
    same = _payload()
    same["teams"]["B"]["name"] = "alpha"
    assert any("same name" in e for e in svc.validate_payload_shape(same))


# ---------------------------------------------------------------------------
# Shared match conditions, bowling priors and win-probability statistics
# ---------------------------------------------------------------------------

def _with_conditions(scale):
    cal = make_calibration()
    beta = [0.0] * len(CLASSES)
    beta[CLASSES.index("R0")], beta[CLASSES.index("R4")], beta[CLASSES.index("R6")] = -0.1, 0.15, 0.25
    cal["genders"]["male"]["conditions"] = {"rho": 0.3, "beta": beta, "scale": scale}
    return cal


def _innings_correlation(scale, n=600):
    import math as _m
    a = [f"a{i}" for i in range(1, 12)]
    b = [f"b{i}" for i in range(1, 12)]
    model = ms.SimModel(_with_conditions(scale), "T20", "male", {}, {}, positions={**{p: i + 1 for i, p in enumerate(a)}, **{p: i + 1 for i, p in enumerate(b)}})
    teams = {"A": ms.TeamSetup("A", "A", a), "B": ms.TeamSetup("B", "B", b)}
    rules = ms.rules_for("T20")
    x, y = [], []
    for j in range(n):
        r = ms.simulate_match(model, ms.rules_for("T20", super_over=False), teams, random.Random(j), toss_winner="A", toss_decision="bat")
        i1, i2 = r["innings"][:2]
        x.append(i1.runs / max(1, i1.legal_balls))
        y.append(i2.runs / max(1, i2.legal_balls))
    mx, my = sum(x) / n, sum(y) / n
    cov = sum((p - mx) * (q - my) for p, q in zip(x, y))
    return cov / _m.sqrt(sum((p - mx) ** 2 for p in x) * sum((q - my) ** 2 for q in y))


def test_shared_conditions_correlate_the_two_innings():
    assert abs(_innings_correlation(0.0)) < 0.1
    assert _innings_correlation(3.0) > 0.15


def test_conditions_posterior_and_jeffreys_interval():
    assert ms.condition_posterior(None) == pytest.approx([1 / ms.CONDITION_BINS] * ms.CONDITION_BINS)
    post = ms.condition_posterior([0.0] * (ms.CONDITION_BINS - 1) + [5.0])
    assert post[-1] > 0.95 and sum(post) == pytest.approx(1.0)
    lo, hi = ms.jeffreys_interval(0, 160)
    assert lo == 0.0 and 0.0 < hi < 0.03  # zero wins in 160 is consistent with up to ~1.5%
    lo, hi = ms.jeffreys_interval(80, 160)
    assert lo < 0.5 < hi and hi - lo < 0.17
    assert ms.jeffreys_interval(5000, 5000)[1] == 1.0


def test_workload_band_priors_shape_low_volume_bowlers():
    cal = make_calibration()
    vec = [float(DEFAULT.get(c, 0)) * 1000 for c in CLASSES]
    weak = list(vec)
    weak[CLASSES.index("W")] *= 0.5
    weak[CLASSES.index("R6")] *= 1.5
    cal["genders"]["male"]["bowler_bands"] = {f"part_time|{p}": {"counts": weak, "bowlers": 100} for p in ("powerplay", "middle", "death")}
    cal["genders"]["male"]["bowler_bands"].update({f"frontline|{p}": {"counts": vec, "bowlers": 100} for p in ("powerplay", "middle", "death")})
    prof = lambda balls: {"bat": {}, "bowl": {}, "bat_balls": 0, "bowl_balls": balls, "bowl_phase_balls": {}, "dismissals": {}}
    model = ms.SimModel(cal, "T20", "male", {"pt": prof(20), "fl": prof(5000)}, {}, positions={"pt": 5, "fl": 10})
    w = CLASSES.index("W")
    assert model.bowl_ratio["pt"]["middle"][w] < 0.85 < model.bowl_ratio["fl"]["middle"][w]
    assert model.quality["pt"] < model.quality["fl"]


def test_recency_weights_do_not_shrink_a_players_evidence():
    league = [float(DEFAULT.get(c, 0)) for c in CLASSES]
    good = list(league)
    good[CLASSES.index("W")] *= 2.0
    total = sum(good[i] for i in range(len(CLASSES)))
    def prof(weight):  # same 2,000 balls, recorded with different recency weights
        return {"bat": {}, "bowl": {"middle|2018": [x * 2000 / total * weight for x in good]}, "bat_balls": 0,
                "bowl_balls": 2000, "bowl_phase_balls": {"middle": 2000}, "dismissals": {}}
    model = ms.SimModel(make_calibration(), "T20", "male", {"old": prof(0.2), "new": prof(1.0)}, {}, positions={})
    w = CLASSES.index("W")
    assert model.bowl_ratio["old"]["middle"][w] == pytest.approx(model.bowl_ratio["new"]["middle"][w], rel=1e-6)
