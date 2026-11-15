"""Hybrid data engine: pure-logic tests (no database).

Covers duplicate detection, cross-source matching, reconciliation, career
aggregation, dismissals/not-outs, format separation, missing innings and
incomplete deliveries, provenance and metric eligibility. Player names in the
fixtures are invented; nothing here encodes a real player's totals.
"""
from datetime import date

import pytest

from app.hybrid import coverage as cov
from app.hybrid import eligibility as el
from app.hybrid import formats
from app.hybrid.career import batting_metrics, bowling_metrics, merge
from app.hybrid.identity import AMBIGUOUS, MATCHED, NEW, MatchKey, decide, venue_similarity
from app.hybrid.people import scheme_of
from app.hybrid.reconcile import BAT_FIELDS, BOWL_FIELDS
from app.hybrid.sources.cricsheet_inventory import parse_readme
from app.hybrid.sources.scorecard_file import is_out_from, overs_to_balls, validate_innings

D = date(1998, 4, 22)


def key(**kw):
    base = dict(start_date=D, gender="male", format_class="ODI", teams=["India", "Australia"],
                venue="Sharjah Cricket Association Stadium", competition="Coca-Cola Cup", canonical_id="c1")
    base.update(kw)
    return MatchKey(**base)


# 1. duplicate match detection / 2. cross-source matching ---------------------------------

class TestMatchIdentity:
    def test_same_match_from_two_sources_is_matched(self):
        rec = key(teams=["Australia", "India"], venue="Sharjah Stadium", canonical_id=None, innings_totals={1: 284})
        d = decide(rec, [key(innings_totals={1: 284, 2: 250})])
        assert d.status == MATCHED and d.canonical_id == "c1" and d.confidence > 0.5

    def test_teams_and_date_alone_do_not_merge_a_doubleheader(self):
        a = key(canonical_id="a", innings_totals={1: 150, 2: 151})
        b = key(canonical_id="b", innings_totals={1: 98, 2: 99})
        rec = key(canonical_id=None)              # no totals: cannot tell the two fixtures apart
        assert decide(rec, [a, b]).status == AMBIGUOUS

    def test_innings_totals_pick_the_right_fixture_of_a_doubleheader(self):
        a = key(canonical_id="a", innings_totals={1: 150, 2: 151})
        b = key(canonical_id="b", innings_totals={1: 98, 2: 99})
        d = decide(key(canonical_id=None, innings_totals={1: 98, 2: 99}), [a, b])
        assert d.status == MATCHED and d.canonical_id == "b"

    def test_contradicting_totals_mean_a_different_match(self):
        d = decide(key(canonical_id=None, innings_totals={1: 300, 2: 120}), [key(innings_totals={1: 150, 2: 151})])
        assert d.status == NEW

    @pytest.mark.parametrize("change", [
        {"gender": "female"}, {"format_class": "TEST"}, {"teams": ["India", "Pakistan"]},
        {"start_date": date(1998, 4, 25)},
    ])
    def test_hard_constraints(self, change):
        assert decide(key(canonical_id=None, **change), [key()]).status == NEW

    def test_first_class_and_cricsheet_multi_day_are_compatible(self):
        rec = key(format_class="FIRST_CLASS", canonical_id=None, start_date=date(1998, 4, 23))
        assert decide(rec, [key(format_class="MULTI_DAY")]).status == MATCHED

    def test_result_contradiction_is_held_for_review_not_merged(self):
        rec = key(canonical_id=None, result_type="win", winner="India")
        assert decide(rec, [key(result_type="win", winner="Australia")]).status == AMBIGUOUS

    def test_same_day_no_results_with_different_totals_are_different_fixtures(self):
        a = key(format_class="T20I", result_type="no result", innings_totals={1: 64}, canonical_id="a")
        b = key(format_class="T20I", result_type="no result", innings_totals={1: 120}, canonical_id=None)
        assert decide(b, [a]).status == NEW

    def test_venue_similarity(self):
        assert venue_similarity("Wankhede Stadium, Mumbai", "Wankhede Stadium") >= 0.5
        assert venue_similarity("Eden Gardens", "Wankhede Stadium") == 0


# 7. missing innings / 8. incomplete deliveries ------------------------------------------

class TestCoverage:
    def inn(self, n, dels=300, overs=50, max_over=49, **kw):
        return cov.InningsEvidence(n, dels, overs, max_over, **kw)

    def test_complete_limited_overs_match_is_full(self):
        s, _ = cov.classify([self.inn(1), self.inn(2)], has_ball_by_ball_source=True, has_scorecard=False,
                            expected=cov.expected_innings("ODI", "win"))
        assert s == cov.FULL

    def test_missing_innings_is_partial(self):
        s, notes = cov.classify([self.inn(1)], has_ball_by_ball_source=True, has_scorecard=False,
                                expected=cov.expected_innings("ODI", "win"))
        assert s == cov.PARTIAL and "1 of 2" in notes[0]

    def test_over_gap_is_partial(self):
        s, notes = cov.classify([self.inn(1, overs=47), self.inn(2)], has_ball_by_ball_source=True,
                                has_scorecard=False, expected=2)
        assert s == cov.PARTIAL and "missing 3 over" in notes[0]

    def test_empty_innings_is_partial_unless_forfeited(self):
        empty = self.inn(2, dels=0, overs=0, max_over=None)
        assert cov.classify([self.inn(1), empty], has_ball_by_ball_source=True, has_scorecard=False,
                            expected=None)[0] == cov.PARTIAL
        empty.forfeited = True
        assert cov.classify([self.inn(1), empty], has_ball_by_ball_source=True, has_scorecard=False,
                            expected=None)[0] == cov.FULL

    def test_scorecard_can_never_be_full(self):
        assert cov.classify([], has_ball_by_ball_source=False, has_scorecard=True, expected=2)[0] == cov.SCORECARD

    def test_awarded_match_with_one_innings_is_complete(self):
        expected = cov.expected_innings("T20I", "win", "Awarded")
        s, notes = cov.classify([self.inn(1, dels=75, overs=12, max_over=11)], has_ball_by_ball_source=True,
                                has_scorecard=False, expected=expected)
        assert expected is None and s == cov.FULL and "no further innings" in notes[0]

    def test_multi_day_draw_implies_no_innings_count(self):
        assert cov.expected_innings("TEST", "draw") is None
        assert cov.expected_innings("ODI", "no result") is None

    def test_labels(self):
        assert cov.LABELS[cov.FULL] == "FULL MATCH DATA"
        assert cov.LABELS[cov.SCORECARD] == "SCORECARD DATA"
        assert cov.LABELS[cov.PARTIAL] == "PARTIAL MATCH DATA"
        assert cov.LABELS[cov.UNKNOWN] == "COVERAGE UNVERIFIED"


# 3. reconciliation / 4. aggregation / 5. dismissals / 10. provenance ---------------------

def bb(cid, n, fc="ODI", status=cov.FULL, **v):
    return {"cid": cid, "innings_number": n, "format_class": fc, "start_date": D, "coverage_status": status, **v}


def sc(cid, n, fc="ODI", src="licensed_archive", vs="validated", **v):
    return {"cid": cid, "innings_number": n, "format_class": fc, "start_date": D, "coverage_status": cov.FULL,
            "source_key": src, "validation_status": vs, **v}


class TestReconciliation:
    def test_same_innings_in_both_layers_counts_once(self):
        recs, conflicts, _ = merge([bb("m1", 1, runs=82, balls=90, fours=8, sixes=1, is_out=True)],
                                   [sc("m1", 1, runs=82, balls=90, fours=8, sixes=1, is_out=True)], BAT_FIELDS)
        assert len(recs) == 1 and recs[0]["runs"] == 82 and not conflicts
        assert recs[0]["provenance"] == "both_agree"
        assert batting_metrics(recs)["runs"]["value"] == 82

    def test_scorecard_only_runs_count(self):
        recs, _, _ = merge([], [sc("m2", 1, runs=45, balls=None, fours=None, sixes=None, is_out=True)], BAT_FIELDS)
        m = batting_metrics(recs)
        assert m["runs"]["value"] == 45 and m["runs"]["status"] == el.VERIFIED
        assert recs[0]["provenance"] == "scorecard"

    def test_disagreement_is_flagged_with_both_values(self):
        recs, conflicts, _ = merge([bb("m1", 1, runs=82, balls=90, fours=8, sixes=1, is_out=True)],
                                   [sc("m1", 1, runs=84, balls=90, fours=8, sixes=1, is_out=True)], BAT_FIELDS)
        (cid, n, metric, values, used, rule), = conflicts
        assert metric == "runs" and values == {"cricsheet": 82, "licensed_archive": 84}
        assert used == 82 and rule == "complete_ball_by_ball_precedence"
        assert recs[0]["provenance"] == "reconciled"

    def test_partial_deliveries_defer_to_scorecard(self):
        _, conflicts, _ = merge([bb("m1", 1, status=cov.PARTIAL, runs=60, balls=70, fours=5, sixes=0, is_out=True)],
                                [sc("m1", 1, runs=82, balls=90, fours=8, sixes=1, is_out=True)], BAT_FIELDS)
        assert {c[2]: c[4] for c in conflicts}["runs"] == 82

    def test_disagreeing_scorecards_stay_unresolved(self):
        recs, conflicts, _ = merge([], [sc("m3", 1, src="a", runs=10, balls=None, fours=None, sixes=None, is_out=True),
                                        sc("m3", 1, src="b", runs=12, balls=None, fours=None, sixes=None, is_out=True),
                                        sc("m5", 1, src="a", runs=40, balls=None, fours=None, sixes=None, is_out=True)],
                                   BAT_FIELDS)
        disputed = next(r for r in recs if r["cid"] == "m3")
        assert disputed["runs"] is None and conflicts[0][5] == "unresolved_scorecard_disagreement"
        runs = batting_metrics(recs)["runs"]
        assert runs["status"] == el.INCOMPLETE and runs["value"] == 40 and runs["basis"] == {"innings": 1, "of": 2}

    def test_inconsistent_scorecard_innings_are_excluded(self):
        recs, _, excluded = merge([], [sc("m4", 1, vs="inconsistent", runs=99, balls=None, fours=None, sixes=None,
                                          is_out=True)], BAT_FIELDS)
        assert recs == [] and excluded == 1


class TestCareerAggregation:
    def test_average_and_not_outs(self):
        recs = [{"runs": 100, "balls": 120, "fours": 10, "sixes": 2, "is_out": True},
                {"runs": 50, "balls": 40, "fours": 5, "sixes": 1, "is_out": False},
                {"runs": 0, "balls": 3, "fours": 0, "sixes": 0, "is_out": True}]
        m = batting_metrics(recs)
        assert m["runs"]["value"] == 150 and m["not_outs"]["value"] == 1
        assert m["batting_average"]["value"] == 75.0 and m["batting_average"]["status"] == el.DERIVED
        assert m["hundreds"]["value"] == 1 and m["fifties"]["value"] == 1
        assert m["highest_score"]["value"] == "100"

    def test_highest_score_not_out_marker(self):
        assert batting_metrics([{"runs": 120, "balls": None, "fours": None, "sixes": None, "is_out": False}])[
            "highest_score"]["value"] == "120*"

    def test_strike_rate_without_balls_is_incomplete_not_estimated(self):
        recs = [{"runs": 100, "balls": 100, "fours": None, "sixes": None, "is_out": True},
                {"runs": 80, "balls": None, "fours": None, "sixes": None, "is_out": True}]
        sr = batting_metrics(recs)["strike_rate"]
        assert sr["value"] == 100.0 and sr["status"] == el.INCOMPLETE and sr["basis"] == {"innings": 1, "of": 2}

    def test_unknown_dismissal_makes_average_incomplete(self):
        recs = [{"runs": 40, "balls": None, "fours": None, "sixes": None, "is_out": None},
                {"runs": 60, "balls": None, "fours": None, "sixes": None, "is_out": True}]
        avg = batting_metrics(recs)["batting_average"]
        assert avg["status"] == el.INCOMPLETE and avg["value"] == 60.0

    def test_economy_needs_legal_balls(self):
        recs = [{"legal_balls": 60, "runs_conceded": 40, "wickets": 2, "maidens": 1},
                {"legal_balls": None, "runs_conceded": 30, "wickets": 1, "maidens": None}]
        m = bowling_metrics(recs)
        assert m["wickets"]["value"] == 3 and m["wickets"]["status"] == el.VERIFIED
        assert m["economy"]["value"] == 4.0 and m["economy"]["status"] == el.INCOMPLETE
        assert m["bowling_average"]["value"] == round(70 / 3, 2)
        assert m["best_innings"]["value"] == "2/40"

    def test_format_separation(self):
        recs, _, _ = merge([bb("t1", 1, fc="TEST", runs=10, balls=20, fours=1, sixes=0, is_out=True),
                            bb("o1", 1, fc="ODI", runs=30, balls=25, fours=3, sixes=1, is_out=True)], [], BAT_FIELDS)
        by = {r["format_class"]: r["runs"] for r in recs}
        assert by == {"TEST": 10, "ODI": 30}

    def test_bowling_merge(self):
        recs, conflicts, _ = merge([bb("m1", 2, legal_balls=60, runs_conceded=45, wickets=3, maidens=0)],
                                   [sc("m1", 2, legal_balls=60, runs_conceded=45, wickets=3, maidens=0)], BOWL_FIELDS)
        assert len(recs) == 1 and not conflicts and recs[0]["wickets"] == 3


# 11. metric eligibility ------------------------------------------------------------------

class TestEligibility:
    def test_delivery_metrics_reject_scorecards(self):
        for metric in ("bowler_batter_matchup", "phase_analysis", "boundary_distribution", "dismissal_patterns",
                       "delivery_strike_rate", "predictive_features"):
            assert not el.layer_allowed(metric, "scorecard", cov.SCORECARD)
            assert not el.layer_allowed(metric, "ball_by_ball", cov.PARTIAL)
            assert el.layer_allowed(metric, "ball_by_ball", cov.FULL)

    def test_aggregates_accept_both_layers(self):
        assert el.layer_allowed("runs", "scorecard") and el.layer_allowed("runs", "ball_by_ball")

    def test_wagon_wheel_unavailable(self):
        assert not el.layer_allowed("wagon_wheel", "ball_by_ball", cov.FULL)
        assert el.status_for("wagon_wheel", 10, 10) == el.UNAVAILABLE

    def test_statuses(self):
        assert el.status_for("runs", 5, 5) == el.VERIFIED
        assert el.status_for("strike_rate", 5, 5) == el.DERIVED
        assert el.status_for("strike_rate", 3, 5) == el.INCOMPLETE
        assert el.status_for("strike_rate", 0, 5) == el.UNAVAILABLE


# scorecard validation and source parsing --------------------------------------------------

class TestScorecardValidation:
    INN = {"number": 1, "team": "A", "total": 105, "wickets": 2,
           "extras": {"byes": 1, "leg_byes": 2, "wides": 1, "no_balls": 1},
           "batting": [{"name": "P1", "runs": 60, "out": True}, {"name": "P2", "runs": 30, "dismissal": "caught"},
                       {"name": "P3", "runs": 10, "dismissal": "not out"}, {"name": "P4", "dnb": True}],
           "bowling": [{"name": "B1", "runs": 52, "wickets": 1}, {"name": "B2", "runs": 50, "wickets": 1}]}

    def test_consistent_innings(self):
        assert validate_innings(self.INN) == []

    def test_total_mismatch_detected(self):
        bad = {**self.INN, "total": 110}
        issues = validate_innings(bad)
        assert any("innings total" in i for i in issues)

    def test_dismissals(self):
        assert is_out_from({"dismissal": "retired hurt"}) is False
        assert is_out_from({"dismissal": "lbw"}) is True
        assert is_out_from({"dismissal": "retired out"}) is True
        assert is_out_from({}) is None and is_out_from({"dnb": True}) is None

    def test_overs_to_balls_needs_balls_per_over(self):
        assert overs_to_balls("10.3", 6) == 63
        assert overs_to_balls("10.3", 8) == 83
        assert overs_to_balls("10.3", None) is None
        assert overs_to_balls("10.7", 6) is None

    def test_readme_parse(self):
        text = ("archive contains 3 matches. A further 386 matches have been withheld due\nto policy\n\n"
                "2026-11-03 - club - NPL - male - 1558594 - Pokhara Avengers vs Lumbini Lions\n"
                "2001-12-19 - international - Test - male - 64012 - India vs England\n"
                "2022-06-07 - club - BLZ - female - wi_211824 - Leeward Islands vs Windward Islands\n")
        items, withheld = parse_readme(text)
        assert withheld == 386 and [i["source_match_id"] for i in items] == ["1558594", "64012", "wi_211824"]
        assert items[1]["start_date"] == date(2001, 12, 19)

    def test_people_scheme(self):
        assert scheme_of("key_cricinfo_2") == "cricinfo" and scheme_of("key_cricketarchive") == "cricketarchive"

    def test_format_mapping(self):
        assert formats.from_cricsheet("MDM") == formats.MULTI_DAY
        assert formats.normalise("fc") == formats.FIRST_CLASS and formats.normalise("List A") == formats.LIST_A
        assert formats.normalise("nonsense") is None
