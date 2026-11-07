from datetime import date

import pytest

from app.api.routes.teams import result_bucket, resolve_formats, validate_date_range, validate_gender, classify_ground_sides, _bump, _serialize
from scripts.backfill_team_countries import is_composite_team


def test_result_classification_keeps_tie_no_result_and_unknown_separate():
    assert result_bucket("tie", None, "a") == "ties"
    assert result_bucket("no result", None, "a") == "no_results"
    assert result_bucket("abandoned", None, "a") == "no_results"
    assert result_bucket(None, None, "a") == "unresolved"
    assert result_bucket("win", "a", "a") == "wins"
    assert result_bucket("win", "b", "a") == "losses"


def test_format_groups_keep_short_formats_compatible_but_distinct():
    assert resolve_formats("T20") == ("T20", "T20I")
    assert resolve_formats("ODI") == ("ODI", "ODM")
    assert resolve_formats("Test") == ("Test", "MDM")
    assert resolve_formats("T20I") == ("T20I",)


def test_custom_date_range_rejects_reverse_order():
    validate_date_range(date(2020, 1, 1), date(2024, 12, 31))
    with pytest.raises(ValueError, match="start_date"):
        validate_date_range(date(2025, 1, 1), date(2024, 12, 31))


@pytest.mark.parametrize("gender", ["all", "male", "female"])
def test_gender_filter_accepts_separate_mens_and_womens_records(gender):
    validate_gender(gender)


def test_gender_filter_rejects_merged_or_unknown_category_names():
    with pytest.raises(ValueError, match="gender"):
        validate_gender("mixed")


def test_composite_xi_is_not_assigned_a_single_country():
    assert is_composite_team("Africa XI")
    assert is_composite_team("World XI")
    assert not is_composite_team("South Africa")
    assert not is_composite_team("India")


def test_grouped_records_count_wins_and_keep_small_samples():
    records = {}
    _bump(records, "Ground A", "wins", True)
    _bump(records, "Ground A", "losses", False)
    row = _serialize(records)[0]
    assert (row["matches"], row["wins"], row["losses"], row["win_percentage"]) == (2, 1, 1, 50.0)


@pytest.mark.parametrize(("ground", "home", "opponent", "expected"), [
    ("India", "India", "Australia", ("home", "away")),
    ("Australia", "India", "Australia", ("away", "home")),
    ("England", "India", "Australia", ("neutral", "neutral")),
    ("India", "India", None, ("home", "away")),
    (None, "India", "Australia", ("unknown", "unknown")),
    ("India", " india ", "INDIA", ("home", "home")),
])
def test_home_away_neutral_and_missing_country_scenarios(ground, home, opponent, expected):
    assert classify_ground_sides(ground, home, opponent) == expected
