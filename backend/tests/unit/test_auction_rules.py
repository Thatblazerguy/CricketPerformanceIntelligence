from decimal import Decimal

import pytest

from app.auction_rules import validate_bid, validate_squad_size


def test_bid_requires_minimum_increment_and_accepts_decimal_precision():
    assert validate_bid(current_bid="10.0", offered_bid="10.2", minimum_increment="0.2",
                        remaining_purse="20", squad_count=3, maximum_squad_size=25) == Decimal("10.2")
    with pytest.raises(ValueError, match="minimum increment"):
        validate_bid(current_bid="10", offered_bid="10.19", minimum_increment="0.2",
                     remaining_purse="20", squad_count=3, maximum_squad_size=25)


def test_bid_cannot_exceed_purse_or_squad_size():
    with pytest.raises(ValueError, match="remaining purse"):
        validate_bid(current_bid="10", offered_bid="21", minimum_increment="1",
                     remaining_purse="20", squad_count=2, maximum_squad_size=25)
    with pytest.raises(ValueError, match="squad limit"):
        validate_bid(current_bid=None, offered_bid="1", minimum_increment="1",
                     remaining_purse="20", squad_count=25, maximum_squad_size=25)


def test_squad_size_validation_does_not_adjust_constraints():
    assert validate_squad_size(squad_size=20, minimum_size=18, maximum_size=25)
    with pytest.raises(ValueError, match="outside configured limits"):
        validate_squad_size(squad_size=26, minimum_size=18, maximum_size=25)
