"""
CPI Domain Enums
Canonical enumerations for cricket domain concepts.
"""
from enum import Enum


class MatchFormat(str, Enum):
    T20 = "T20"
    T20I = "T20I"
    ODI = "ODI"
    TEST = "Test"
    MDM = "MDM"
    ODM = "ODM"
    OTHER = "Other"


class Gender(str, Enum):
    MALE = "male"
    FEMALE = "female"


class TeamType(str, Enum):
    CLUB = "club"
    INTERNATIONAL = "international"


class TossDecision(str, Enum):
    BAT = "bat"
    FIELD = "field"


class ResultType(str, Enum):
    WIN = "win"
    TIE = "tie"
    DRAW = "draw"
    NO_RESULT = "no result"


class ExtraType(str, Enum):
    WIDES = "wides"
    NOBALLS = "noballs"
    BYES = "byes"
    LEGBYES = "legbyes"
    PENALTY = "penalty"


class DismissalKind(str, Enum):
    BOWLED = "bowled"
    CAUGHT = "caught"
    CAUGHT_AND_BOWLED = "caught and bowled"
    LBW = "lbw"
    STUMPED = "stumped"
    HIT_WICKET = "hit wicket"
    RUN_OUT = "run out"
    OBSTRUCTING_THE_FIELD = "obstructing the field"
    RETIRED_HURT = "retired hurt"
    RETIRED_OUT = "retired out"
    UNKNOWN = "unknown"


class Phase(str, Enum):
    POWERPLAY = "powerplay"
    MIDDLE = "middle"
    DEATH = "death"
    SUPER_OVER = "super_over"
    UNKNOWN = "unknown"


class IngestionStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"


class PlayerRole(str, Enum):
    BATTER = "batter"
    BOWLER = "bowler"
    ALL_ROUNDER = "all_rounder"
    WICKET_KEEPER = "wicket_keeper"
    UNKNOWN = "unknown"


# Dismissals that credit the bowler
BOWLER_CREDITED_DISMISSALS = {
    DismissalKind.BOWLED,
    DismissalKind.CAUGHT,
    DismissalKind.CAUGHT_AND_BOWLED,
    DismissalKind.LBW,
    DismissalKind.STUMPED,
    DismissalKind.HIT_WICKET,
}

# Dismissals that count for batting average (batter is out)
BATTER_DISMISSED_KINDS = {
    DismissalKind.BOWLED,
    DismissalKind.CAUGHT,
    DismissalKind.CAUGHT_AND_BOWLED,
    DismissalKind.LBW,
    DismissalKind.STUMPED,
    DismissalKind.HIT_WICKET,
    DismissalKind.RUN_OUT,
    DismissalKind.OBSTRUCTING_THE_FIELD,
    DismissalKind.RETIRED_OUT,
}

# Extras that negate legal-ball status
NON_LEGAL_EXTRAS = {ExtraType.WIDES, ExtraType.NOBALLS}

# Extras excluded from bowling runs conceded
BOWLING_EXCLUDED_EXTRAS = {ExtraType.BYES, ExtraType.LEGBYES}

# Phase over-index boundaries (zero-based, standard 20-over T20)
PHASE_BOUNDARIES = {
    Phase.POWERPLAY: (0, 5),
    Phase.MIDDLE: (6, 14),
    Phase.DEATH: (15, 19),
}
