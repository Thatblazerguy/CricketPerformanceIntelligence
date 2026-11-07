"""Deterministic, testable checks for auction rule invariants."""
from decimal import Decimal


def validate_bid(*, current_bid, offered_bid, minimum_increment, remaining_purse,
                 squad_count, maximum_squad_size):
    offered = Decimal(str(offered_bid))
    purse = Decimal(str(remaining_purse))
    if current_bid is not None and offered < Decimal(str(current_bid)) + Decimal(str(minimum_increment)):
        raise ValueError("Bid is below the minimum increment")
    if offered > purse:
        raise ValueError("Bid exceeds the remaining purse")
    if squad_count >= maximum_squad_size:
        raise ValueError("Franchise squad limit has been reached")
    return offered


def validate_squad_size(*, squad_size, minimum_size, maximum_size):
    if squad_size < minimum_size or squad_size > maximum_size:
        raise ValueError("Squad size is outside configured limits")
    return True
