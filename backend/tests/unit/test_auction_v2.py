"""Pure-logic tests for Auction Intelligence v2 (no database)."""
import json
import math

import numpy as np
import pytest

from app.auction import sources as src
from app.auction.identity import _edit_distance
from app.auction.ingest import _similar_names, _strongly_similar
from app.auction.market import Rules, _lognorm_exceed, best_xi, overall_quality, purse_constraints, quality_scores
from app.ml.auction_price import classification_metrics, price_metrics, sale_probabilities
from app.auction.simulator import _noise


# ---------------------------------------------------------------- sources

def test_inr_convert_handles_crore_and_lakh():
    assert src.inr_convert_lakh("{{INRConvert|16|c|lk=on}}") == 1600
    assert src.inr_convert_lakh("{{INRConvert|4.8|c}}") == 480
    assert src.inr_convert_lakh("{{INRConvert|70|l|lk=on}}") == 70
    assert src.inr_convert_lakh("no template") is None


def test_clean_cell_extracts_names_country_rtm_and_strips_refs():
    text, hints = src.clean_cell("{{sortname|Arshdeep|Singh|dab=cricketer}} {{dagger}}<ref>x</ref>")
    assert text == "Arshdeep Singh" and hints["rtm"]
    text, hints = src.clean_cell("{{cr|ENG}}")
    assert hints["country_code"] == "ENG"
    assert src.clean_cell("[[Daryl Mitchell (New Zealand cricketer)|Daryl Mitchell]]")[0] == "Daryl Mitchell"


def test_franchise_codes_merge_renamed_franchises_only():
    assert src.franchise_code("Delhi Daredevils") == src.franchise_code("Delhi Capitals") == "DC"
    assert src.franchise_code("Kings XI Punjab") == "PBKS"
    assert src.franchise_code("Royal Challengers Bangalore") == "RCB"
    assert src.franchise_code("Deccan Chargers") == "DCH" != src.franchise_code("Sunrisers Hyderabad")
    assert src.franchise_code("N/A") is None and src.franchise_code("Unsold") is None


@pytest.mark.parametrize("raw,expected", [("AR", "AR"), ("BAT", "BAT"), ("WK", "WK"), ("BOWL", "BOWL"),
                                          ("All-Rounder", "AR"), ("Wicket-Keeper", "WK"), ("BATSMAN", "BAT"),
                                          ("Bowler", "BOWL"), ("Unknown", None), (None, None)])
def test_normalize_role_is_idempotent(raw, expected):
    assert src.normalize_role(raw) == expected
    assert src.normalize_role(src.normalize_role(raw)) == expected


def test_set_codes_encode_role_and_bowling_kind():
    assert src.role_from_set("UFA1") == "BOWL" and src.bowling_kind(None, "UFA1") == "pace"
    assert src.role_from_set("SP2") == "BOWL" and src.bowling_kind(None, "SP2") == "spin"
    assert src.role_from_set("WK1") == "WK" and src.role_from_set("M1") is None
    assert src.bowling_kind("RIGHT ARM Leg Spin") == "spin"
    assert src.bowling_kind("LEFT ARM Fast Medium") == "pace"
    assert src.bowling_kind("nan") is None


def test_wikitable_parser_handles_row_headers_and_missing_set_number(tmp_path):
    wikitext = """=== Retained players ===
{| class="wikitable"
|+ [[Chennai Super Kings]]
! scope="col" | No.
! scope="col" | Player
! scope="col" | Nationality
! scope="col" | Salary
|-
| 1
! scope="row" | {{sortname|MS|Dhoni}}
| {{cr|IND}} || {{INRConvert|4|c|lk=on}}
|}
== Auction ==
{| class="wikitable"
|+ Set 4: capped fast bowlers (FA1)
! scope="col" | No.
! scope="col" | Name
! scope="col" | Country
! scope="col" | No. of IPL matches
! scope="col" | Base price
! scope="col" | 2025 IPL team
! scope="col" | Auctioned price
! scope="col" | 2024 IPL team
|-
| 34
! scope="row" | {{sortname|Trent|Boult}}
| {{cr|NZ}} || 104 || 200 || [[Mumbai Indians]] || 1250 || [[Rajasthan Royals]]
|-
| 35
! scope="row" | {{sortname|Josh|Inglis}} {{dagger}}
| {{cr|AUS}} || {{N/A}} || 200 || [[Punjab Kings]] || 260 || {{N/A}}
|}
"""
    path = tmp_path / "wiki_2025.json"
    path.write_text(json.dumps({"parse": {"title": "List of 2025 Indian Premier League personnel changes",
                                          "revid": 1, "wikitext": wikitext}}))
    out = src.parse_wikipedia_page(path, 2025)
    assert [r["player_name"] for r in out["retained"]] == ["MS Dhoni"]
    assert out["retained"][0]["final_price_lakh"] == 400 and out["retained"][0]["franchise"] == "CSK"
    boult, inglis = out["sold"]
    assert boult["final_price_lakh"] == 1250 and boult["franchise"] == "MI" and boult["previous_franchise"] == "RR"
    assert boult["set_code"] == "FA1" and boult["role"] == "BOWL" and boult["lot_number"] == 34
    assert inglis["is_rtm"] and inglis["ipl_matches_before"] == 0 and inglis["country"] == "Australia"


# ---------------------------------------------------------------- identity / reconciliation

def test_edit_distance():
    assert _edit_distance("sooryavanshi", "suryavanshi") == 2
    assert _edit_distance("patel", "patel") == 0


def test_spelling_variant_similarity():
    assert _similar_names("C.Hari Nishaanth", "C Hari Nishaanth")
    assert _similar_names("K Gowtham", "Krishnappa Gowtham")
    assert _strongly_similar("Gurkeerat Singh", "Gurkeerat Singh Mann")
    assert not _strongly_similar("Arshdeep Singh", "Anmolpreet Singh")


# ---------------------------------------------------------------- metrics & calibration

def test_price_metrics_and_coverage():
    m = price_metrics(np.array([100, 200, 400.0]), np.array([100, 100, 400.0]), np.array([50, 150, 300.0]), np.array([150, 250, 500.0]))
    assert m["mae_lakh"] == pytest.approx(33.33, abs=0.01)
    assert m["coverage_80"] == 1.0 and m["bias_lakh"] == pytest.approx(-33.33, abs=0.01)


def test_classification_metrics_confusion():
    m = classification_metrics(np.array([1, 1, 0, 0]), np.array([0.9, 0.2, 0.8, 0.1]))
    assert m["confusion"] == {"tp": 1, "fp": 1, "fn": 1, "tn": 1}
    assert m["sold_precision"] == 0.5 and m["accuracy"] == 0.5


class _Const:
    def __init__(self, p): self.p = np.asarray(p)
    def predict_proba(self, X): return np.vstack([1 - self.p, self.p]).T


def test_prior_shift_matches_expected_rate_and_preserves_ranking():
    import pandas as pd
    from app.ml.auction_price import ALL_FEATURES
    frame = pd.DataFrame({k: [0.0] * 5 for k in ALL_FEATURES})
    raw = [0.9, 0.8, 0.6, 0.4, 0.2]
    shifted = sale_probabilities(_Const(raw), frame, 0.3)
    assert np.mean(shifted) == pytest.approx(0.3, abs=1e-3)
    assert list(np.argsort(-shifted)) == list(np.argsort(-np.array(raw)))


# ---------------------------------------------------------------- squad / purse / rules

def _m(name, bat, bowl, overseas=False, keeper=False):
    return {"player_id": name, "name": name, "bat": bat, "bowl": bowl, "overseas": overseas, "keeper": keeper}


def test_best_xi_respects_overseas_cap_and_keeper():
    members = [_m(f"OS{i}", 90, 90, overseas=True) for i in range(6)] + \
              [_m(f"IN{i}", 50, 40 if i < 6 else None) for i in range(10)] + [_m("WK", 30, None, keeper=True)]
    xi = best_xi(members, max_overseas=4)
    assert xi["feasible"] and len(xi["xi"]) == 11
    assert sum(1 for p in xi["xi"] if p.startswith("OS")) == 4
    assert "WK" in xi["xi"]


def test_duplicate_strength_adds_less_than_filling_a_gap():
    squad = [_m(f"B{i}", 70, None) for i in range(8)] + [_m(f"W{i}", 10, 60) for i in range(3)] + [_m("K", 50, None, keeper=True)]
    base = best_xi(squad, 4)["score"]
    another_batter = best_xi(squad + [_m("NB", 72, None)], 4)["score"] - base
    a_bowler = best_xi(squad + [_m("NW", 10, 72)], 4)["score"] - base
    assert a_bowler > another_batter


def test_purse_constraints_reserve_for_minimum_squad():
    rules = Rules(2025, "MEGA", 12000, 18, 25, 8, 4, 30, True, [[0, 5], [100, 10], [200, 20], [300, 25]])
    c = purse_constraints(4500, 5, 1, rules)
    assert c["slots_left"] == 20 and c["min_slots_to_fill"] == 13
    assert c["minimum_reserve_lakh"] == 12 * 30 and c["max_theoretical_bid_lakh"] == 4500 - 360
    assert purse_constraints(None, 5, 1, rules) == {"known": False}


def test_bid_increment_ladder():
    rules = Rules(2025, "MEGA", 12000, 18, 25, 8, 4, 30, True, [[0, 5], [100, 10], [200, 20], [300, 25]])
    assert [rules.increment(v) for v in (30, 95, 100, 150, 250, 900)] == [5, 5, 10, 10, 20, 25]


def test_quality_scores_leave_thin_samples_missing():
    feats = {"a": {"bat_evidence_balls": 500, "bat_sr_eq": 150, "bat_avg_eq": 35, "bat_boundary_pct": 18, "bat_dot_pct": 30},
             "b": {"bat_evidence_balls": 500, "bat_sr_eq": 120, "bat_avg_eq": 20, "bat_boundary_pct": 10, "bat_dot_pct": 40},
             "c": {"bat_evidence_balls": 10, "bat_sr_eq": 200}}
    q = quality_scores(feats)
    assert q["a"]["bat"] > q["b"]["bat"] and q["c"]["bat"] is None and q["a"]["bowl"] is None


def test_all_rounder_quality_penalises_weak_second_skill():
    balanced = overall_quality({"role": "AR", "bat_quality": 60, "bowl_quality": 60})
    lopsided = overall_quality({"role": "AR", "bat_quality": 90, "bowl_quality": 30})
    assert balanced > lopsided


def test_bidding_war_probability_from_quantiles():
    assert _lognorm_exceed(100, 50, 100, 200) == pytest.approx(0.5, abs=1e-6)
    assert _lognorm_exceed(400, 50, 100, 200) < 0.1


def test_private_valuation_noise_is_deterministic():
    assert _noise(42, "CSK", "p1", 0.2) == _noise(42, "CSK", "p1", 0.2)
    assert _noise(42, "CSK", "p1", 0.2) != _noise(42, "MI", "p1", 0.2)
    draws = [math.log(_noise(1, "X", str(i), 0.2)) for i in range(2000)]
    assert abs(np.mean(draws)) < 0.02 and abs(np.std(draws) - 0.2) < 0.02
