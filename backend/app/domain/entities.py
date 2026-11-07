"""
CPI Canonical Domain Entities
Dataclasses representing normalised cricket data, independent of any provider's JSON format.
These are the intermediate representation between the parsed source and the database.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date
from typing import Optional, List, Dict
from .enums import MatchFormat, Gender, TossDecision, ResultType, Phase


@dataclass
class CanonicalPlayer:
    source_player_id: str          # Cricsheet people registry ID
    name: str                      # Canonical name from registry
    provider_name: str             # Provider name (e.g., "cricsheet")


@dataclass
class CanonicalTeam:
    name: str                      # Team name as appears in source
    provider_name: str


@dataclass
class CanonicalVenue:
    name: str                      # Full venue name
    source_venue_id: Optional[str] # Cricsheet registry venue ID
    city: Optional[str]
    country: Optional[str]


@dataclass
class CanonicalExtra:
    extra_type: str                # e.g., "wides", "noballs", "byes", "legbyes", "penalty"
    runs: int


@dataclass
class CanonicalWicket:
    player_out: str                # Name of dismissed batter (registry name)
    player_out_source_id: Optional[str]
    kind: str                      # Dismissal kind string
    is_bowler_wicket: bool         # Whether the bowler gets credit
    is_batter_dismissed: bool      # Whether counts for batting average
    fielder_name: Optional[str]    # Name of fielder (if applicable)
    fielder_source_id: Optional[str]


@dataclass
class CanonicalDelivery:
    over_number: int               # Zero-based over index
    delivery_sequence: int         # Position within the over (0-based index in deliveries list)
    source_delivery_label: str     # Raw "actual_delivery" string e.g., "0.1"
    batter: str                    # Facing batter name
    batter_source_id: Optional[str]
    bowler: str                    # Bowler name
    bowler_source_id: Optional[str]
    non_striker: str
    non_striker_source_id: Optional[str]
    batter_runs: int
    extras_runs: int
    total_runs: int
    is_legal_ball: bool
    is_ball_faced_by_batter: bool
    bowling_runs: int              # Runs charged to the bowler
    phase: Phase
    extras: List[CanonicalExtra] = field(default_factory=list)
    wickets: List[CanonicalWicket] = field(default_factory=list)
    has_replacement: bool = False  # Impact player replacement
    is_boundary_four: bool = False
    is_boundary_six: bool = False


@dataclass
class CanonicalInnings:
    innings_number: int            # 1-based innings number
    batting_team: str
    is_super_over: bool
    target_runs: Optional[int]
    target_overs: Optional[int]
    absent_hurt: List[str] = field(default_factory=list)
    deliveries: List[CanonicalDelivery] = field(default_factory=list)


@dataclass
class CanonicalMatch:
    source_match_id: str           # Cricsheet filename stem (e.g., "1082591")
    provider_name: str             # "cricsheet"
    source_file_name: str
    checksum: str
    data_version: str
    source_revision: int
    match_format: MatchFormat
    gender: Gender
    start_date: date
    season: str
    competition_name: Optional[str]
    match_number: Optional[int]
    venue_name: str
    venue_source_id: Optional[str]
    city: Optional[str]
    teams: List[str]               # Exactly two team names
    toss_winner: str
    toss_decision: TossDecision
    winner: Optional[str]
    result_type: Optional[ResultType]
    result_margin_runs: Optional[int]
    result_margin_wickets: Optional[int]
    player_of_match: List[str] = field(default_factory=list)
    registry: Dict[str, str] = field(default_factory=dict)  # {name: source_id}
    venue_registry: Dict[str, str] = field(default_factory=dict)
    innings: List[CanonicalInnings] = field(default_factory=list)
    players: Dict[str, List[str]] = field(default_factory=dict)  # {team: [player_names]}

