from types import SimpleNamespace

import pandas as pd

from app.auction_csv import history_row, read_csv_rows
from app.ml.auction_price import prepare_history
from app.api.routes.auction import _matching_player_ids
from app.analytics.auction_scenario import role_needs
from app.analytics.auction_competition import (
    competition_adjusted_price, competition_level, demand_score, percentile_quality,
    team_willingness_lakh,
)
from app.ml.auction_price import predict_team_bids, _fit_form_adjusters, _predict_form_adjustments
from app.analytics.auction_form import FORM_FEATURES, summarize_form, _format_weight
from datetime import date, timedelta


def test_history_csv_converts_crores_and_rupees_to_lakh():
    rows = read_csv_rows("history.csv", b"Player,Year,Team,Amount,Amount_Cr,Role\nA Player,2020,CSK,10000000,1.0,Bowler\n")
    row, errors = history_row("test", *rows[0])
    assert not errors
    assert row["final_price_lakh"] == 100
    assert row["status"] == "SOLD"


def test_history_csv_keeps_unsold_records_without_sale_price():
    rows = read_csv_rows("history.csv", b"Player,Year,Team,Status\nA Player,2020,CSK,UNSOLD\n")
    row, errors = history_row("test", *rows[0])
    assert not errors
    assert row["final_price_lakh"] is None
    assert row["status"] == "UNSOLD"


def test_model_uses_only_sold_auction_rows_and_prior_year_features():
    records = [
        SimpleNamespace(player_id="p1", source_player_name="Player One", auction_year=2020,
                        base_price_lakh=20, final_price_lakh=100, status="SOLD",
                        acquisition_type="auction", role="Batter", nationality="Indian",
                        franchise_name="CSK", source_name="outside-edge/ipl_auction"),
        SimpleNamespace(player_id="p1", source_player_name="Player One", auction_year=2021,
                        base_price_lakh=None, final_price_lakh=200, status="SOLD",
                        acquisition_type="auction", role="Batter", nationality="Indian",
                        franchise_name="MI", source_name="outside-edge/ipl_auction"),
        SimpleNamespace(player_id="p2", source_player_name="Player Two", auction_year=2021,
                        base_price_lakh=None, final_price_lakh=None, status="UNSOLD",
                        acquisition_type="auction", role="Bowler", nationality="Indian",
                        franchise_name="MI", source_name="outside-edge/ipl_auction"),
    ]
    frame = prepare_history(records)
    assert len(frame) == 2
    later = frame[frame.auction_year == 2021].iloc[0]
    assert later.prior_price_lakh == 100
    assert pd.isna(frame[frame.auction_year == 2020].iloc[0].prior_price_lakh)


def test_player_alias_index_resolves_long_name_to_cricsheet_initial_alias():
    index = {"spencer johnson": {"cpi-player-sh-johnson"}, "sh johnson": {"cpi-player-sh-johnson"}}
    assert _matching_player_ids(index, "Spencer Johnson") == {"cpi-player-sh-johnson"}


def test_player_alias_index_does_not_choose_between_ambiguous_initial_matches():
    index = {"sh johnson": {"player-sh"}, "sammy jo johnson": {"player-sj"}}
    assert _matching_player_ids(index, "Spencer Johnson") == {"player-sh", "player-sj"}


def test_scenario_needs_are_based_on_retained_roles_and_targets():
    needs = role_needs({"Batter": 5, "Bowler": 7, "All-Rounder": 2, "Wicketkeeper": 2})
    assert needs == {"Batter": 1, "All-Rounder": 2}


def test_team_bid_prediction_uses_franchise_feature_and_returns_inr_lakh():
    class FixedPipeline:
        def predict(self, frame):
            assert frame.loc[0, "franchise"] == "royal challengers bengaluru"
            return [__import__("numpy").log1p(425.0)]

    model = {"pipeline": FixedPipeline(), "features": [
        "auction_year", "base_price_lakh", "prior_price_lakh", "prior_auction_count",
        "role", "nationality", "franchise",
    ]}
    estimate = predict_team_bids(model, [{
        "auction_year": 2026, "base_price_lakh": 100, "prior_price_lakh": None,
        "prior_auction_count": 0, "role": "Bowler", "nationality": "Indian",
        "franchise": "RCB",
    }])
    assert abs(estimate[0] - 425.0) < 1e-8


def test_competitive_price_rises_with_bidders_and_falls_with_alternatives():
    quiet = competition_adjusted_price(100, 600, [], 0, 0.5, 50)
    bidding_war = competition_adjusted_price(100, 600, [900, 850, 800, 750, 700, 650, 600], 0, 0.5, 50)
    many_alternatives = competition_adjusted_price(100, 600, [900, 850, 800, 750, 700, 650, 600], 4, 0.5, 50)
    assert bidding_war["expected_lakh"] > quiet["expected_lakh"]
    assert bidding_war["expected_lakh"] > many_alternatives["expected_lakh"]
    assert bidding_war["bidder_count"] == 7
    assert bidding_war["competition_level"] == "Extreme"


def test_demand_excludes_franchises_that_cannot_bid():
    assert demand_score(0, 6, 90, 5000, 500, 100, 10)[0] == 0
    assert demand_score(2, 6, 90, 50, 500, 100, 10)[0] == 0
    assert demand_score(2, 6, 90, 5000, 500, 100, 0)[0] == 0
    assert demand_score(2, 6, 90, 5000, 500, 100, 10, overseas_slots=0, is_overseas=True)[0] == 0


def test_role_quality_uses_discipline_features_and_preserves_missing_samples():
    rows = {
        "batter": {"batting_balls": 200, "batting_average": 55, "strike_rate": 150,
                   "boundary_percentage": 25, "batting_dot_percentage": 20},
        "bowler": {"bowling_balls": 240, "wickets_per_match": 2, "economy": 6.5,
                   "bowling_average": 18, "bowling_strike_rate": 15, "dot_percentage": 48},
        "small_sample": {"bowling_balls": 24, "wickets_per_match": 3, "economy": 4,
                         "bowling_average": 10, "bowling_strike_rate": 8, "dot_percentage": 60},
    }
    bowler_scores = percentile_quality(rows, "Specialist Bowler")
    batter_scores = percentile_quality(rows, "Batter")
    assert bowler_scores["bowler"] is not None
    assert bowler_scores["small_sample"] is None
    assert batter_scores["bowler"] is None
    assert batter_scores["batter"] is not None


def test_competition_labels_follow_credible_bidder_counts():
    assert [competition_level(n) for n in (0, 1, 3, 6)] == ["Low", "Moderate", "High", "Extreme"]


def test_team_purse_caps_model_bid_without_becoming_the_bid_estimate():
    # ₹120 cr available is only a ceiling; it is not a ₹120 cr estimate.
    assert team_willingness_lakh(425, 100, 12000) == 425
    assert team_willingness_lakh(12500, 100, 12000) == 12000
    assert team_willingness_lakh(25, 100, 12000) == 100


def _form_rows(count=4):
    today = date.today()
    rows = []
    for i in range(count):
        shared = {"match_id": f"m{i}", "start_date": today - timedelta(days=30 * (i + 1)),
                  "match_format": "T20", "opposition_strength": 0.6}
        rows.append({**shared, "discipline": "bat", "runs": 45 + i, "balls": 30,
                     "dismissals": 1, "high_score": 60 + i})
        rows.append({**shared, "discipline": "bowl", "wickets": 2, "legal_balls": 24,
                     "conceded": 28, "opposition_strength": 0.6})
    return rows


def test_recent_form_features_are_role_separated_and_all_rounders_keep_both():
    rows = _form_rows()
    batter = summarize_form(rows, "Batter")
    bowler = summarize_form(rows, "Bowler")
    all_rounder = summarize_form(rows, "All-Rounder")
    assert batter["form_bat_runs_per_match"] is not None
    assert batter["form_bowl_economy"] is None
    assert bowler["form_bowl_economy"] is not None
    assert bowler["form_bat_strike_rate"] is None
    assert all_rounder["form_bat_strike_rate"] is not None
    assert all_rounder["form_bowl_economy"] is not None


def test_form_weights_prioritise_franchise_t20_and_t20_internationals():
    assert _format_weight("T20", "Indian Premier League") > _format_weight("T20", "Syed Mushtaq Ali Trophy")
    assert _format_weight("T20I") > _format_weight("ODI")


def test_wicketkeeper_form_includes_recorded_stumpings_when_available():
    rows = _form_rows()
    for row in rows:
        row["keeper_stumpings"] = 1 if row["discipline"] == "bat" else 0
    form = summarize_form(rows, "Wicketkeeper")
    assert form["form_keeper_stumpings_per_match"] > 0


def test_learned_form_residual_adjustment_moves_stronger_batter_upward():
    rows = []
    residuals = []
    for i in range(30):
        row = {key: None for key in FORM_FEATURES}
        row.update({"role": "Batter", "form_sample_matches": 8,
                    "form_bat_runs_per_match": float(i + 5),
                    "form_bat_average": float(i + 10),
                    "form_bat_strike_rate": float(80 + i * 2),
                    "form_bat_consistency": float(20 - i * 0.3),
                    "form_bat_high_score": float(30 + i * 3),
                    "form_recent_trend": float(i),
                    "form_opposition_strength": 0.55})
        rows.append(row)
        residuals.append(i * 0.02)
    frame = pd.DataFrame(rows)
    adjusters = _fit_form_adjusters(frame, __import__("numpy").array(residuals))
    low, high = frame.iloc[[0]].copy(), frame.iloc[[-1]].copy()
    adjustment = _predict_form_adjustments(pd.concat([low, high], ignore_index=True), adjusters)
    assert adjustment[1] > adjustment[0]


def test_recent_form_respects_auction_year_cutoff_and_small_samples():
    rows = _form_rows(2)
    for row in rows:
        row["start_date"] = row["start_date"].replace(year=date.today().year - 2)
    rows.append({"match_id": "future", "start_date": date.today(), "match_format": "T20",
                 "discipline": "bat", "runs": 300, "balls": 100, "dismissals": 0,
                 "high_score": 300, "opposition_strength": None})
    form = summarize_form(rows, "Batter", cutoff_year=date.today().year)
    assert form["form_sample_matches"] == 2
    assert form["form_bat_runs_per_match"] is None
    assert form["form_bat_high_score"] is None
    assert set(FORM_FEATURES).issuperset(form)


def test_form_features_are_passed_into_the_existing_price_model():
    class FormPipeline:
        def predict(self, frame):
            assert frame.loc[0, "form_bat_strike_rate"] == 175
            assert frame.loc[0, "form_sample_matches"] == 8
            return [__import__("numpy").log1p(525.0)]

    features = ["auction_year", "base_price_lakh", "prior_price_lakh", "prior_auction_count",
                "role", "nationality", "franchise", *FORM_FEATURES]
    candidate = {"auction_year": 2026, "base_price_lakh": 100, "prior_price_lakh": None,
                 "prior_auction_count": 0, "role": "Batter", "nationality": "Indian",
                 "franchise": "RCB", "form_bat_strike_rate": 175, "form_sample_matches": 8}
    assert abs(predict_team_bids({"pipeline": FormPipeline(), "features": features}, [candidate])[0] - 525.0) < 1e-8
