"""Unit tests for Playing XI upload and name cleaning logic."""
from app.api.routes.xi import clean_player_name, TeamBalance


def test_clean_player_name_strips_numbering_and_detects_tags():
    name, is_capt, is_wk = clean_player_name("1. Rohit Sharma (c)")
    assert name == "Rohit Sharma"
    assert is_capt is True
    assert is_wk is False


def test_clean_player_name_detects_wicketkeeper_variants():
    name, is_capt, is_wk = clean_player_name("3) Rishabh Pant [wk]")
    assert name == "Rishabh Pant"
    assert is_capt is False
    assert is_wk is True

    name2, is_capt2, is_wk2 = clean_player_name("MS Dhoni (c/wk)")
    assert name2 == "MS Dhoni"
    assert is_capt2 is True
    assert is_wk2 is True


def test_clean_player_name_plain_strings():
    name, is_capt, is_wk = clean_player_name("Virat Kohli")
    assert name == "Virat Kohli"
    assert is_capt is False
    assert is_wk is False


def test_team_balance_initialization():
    tb = TeamBalance(
        batters=4,
        all_rounders=3,
        bowlers=4,
        wicketkeepers=1,
        pace_bowlers=3,
        spin_bowlers=2,
        left_hand_batters=3,
        right_hand_batters=8,
    )
    assert tb.batters == 4
    assert tb.wicketkeepers == 1
    assert tb.pace_bowlers == 3



def test_names_starting_with_c_or_w_are_not_mistaken_for_tags():
    for raw in ("Chris Woakes", "Chris Jordan", "Will Jacks", "Wanindu Hasaranga", "Corbin Bosch"):
        name, is_capt, is_wk = clean_player_name(raw)
        assert (name, is_capt, is_wk) == (raw, False, False)


def test_scorecard_symbols_and_bracket_variants_are_detected():
    assert clean_player_name("Quinton de Kock†") == ("Quinton de Kock", False, True)
    assert clean_player_name("Temba Bavuma*") == ("Temba Bavuma", True, False)
    assert clean_player_name("Shai Hope (w/k)") == ("Shai Hope", False, True)
    assert clean_player_name("Dhoni [C, WK]") == ("Dhoni", True, True)
    assert clean_player_name("Mitchell Marsh (vc)") == ("Mitchell Marsh", False, False)
