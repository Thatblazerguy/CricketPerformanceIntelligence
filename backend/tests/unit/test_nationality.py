from datetime import date

from app.services.nationality import resolve_affiliations, INTERNATIONAL_APPEARANCES_SQL


def test_single_international_affiliation_resolves():
    nationality, history = resolve_affiliations([{"nationality": "India", "first_seen": date(2012, 1, 1),
        "last_seen": date(2024, 1, 1), "match_count": 80}])
    assert nationality == "India"
    assert len(history) == 1


def test_sequential_national_affiliations_keep_latest_and_history():
    nationality, history = resolve_affiliations([
        {"nationality": "Country A", "first_seen": date(2010, 1, 1), "last_seen": date(2015, 1, 1)},
        {"nationality": "Country B", "first_seen": date(2018, 1, 1), "last_seen": date(2023, 1, 1)},
    ])
    assert nationality == "Country B"
    assert len(history) == 2


def test_overlapping_affiliations_are_not_guessed():
    nationality, _ = resolve_affiliations([
        {"nationality": "Country A", "first_seen": date(2015, 1, 1), "last_seen": date(2020, 1, 1)},
        {"nationality": "Country B", "first_seen": date(2018, 1, 1), "last_seen": date(2022, 1, 1)},
    ])
    assert nationality == "Unknown"


def test_no_evidence_remains_unknown():
    assert resolve_affiliations([]) == ("Unknown", [])


def test_composite_xi_is_not_nationality_evidence():
    nationality, history = resolve_affiliations([
        {"nationality": "ICC World XI", "first_seen": date(2018, 1, 1), "last_seen": date(2018, 1, 1)},
        {"nationality": "India", "first_seen": date(2010, 1, 1), "last_seen": date(2020, 1, 1)},
    ])
    assert nationality == "India"
    assert [item["nationality"] for item in history] == ["India"]


def test_only_international_formats_are_used_as_evidence():
    sql = str(INTERNATIONAL_APPEARANCES_SQL)
    assert "'TEST','ODI','T20I'" in sql
    assert "'T20'" not in sql
