"""
SQLAlchemy Database Models for CPI.

All tables use UUID primary keys except where noted.
Provider IDs (source identifiers) are stored separately from internal IDs.
"""
from __future__ import annotations

import uuid
from datetime import datetime, date
from typing import Optional, List

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    Index,
    JSON,
    LargeBinary,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, relationship, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def _uuid():
    return str(uuid.uuid4())


# ============================================================
#  Providers
# ============================================================

class Provider(Base):
    __tablename__ = "providers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    base_url: Mapped[Optional[str]] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())


# ============================================================
#  Tournaments / Competitions
# ============================================================

class Tournament(Base):
    __tablename__ = "tournaments"
    __table_args__ = (
        UniqueConstraint("provider_id", "source_tournament_id", name="uq_tournament_provider_source"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    provider_id: Mapped[str] = mapped_column(String(36), ForeignKey("providers.id"))
    source_tournament_id: Mapped[Optional[str]] = mapped_column(String(256))
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    format: Mapped[Optional[str]] = mapped_column(String(32))
    gender: Mapped[Optional[str]] = mapped_column(String(16))
    country: Mapped[Optional[str]] = mapped_column(String(128))


# ============================================================
#  Teams
# ============================================================

class Team(Base):
    __tablename__ = "teams"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(256), unique=True, nullable=False)
    canonical_name: Mapped[str] = mapped_column(String(256), nullable=False)
    country: Mapped[Optional[str]] = mapped_column(String(128))
    country_source: Mapped[Optional[str]] = mapped_column(String(128))
    country_confidence: Mapped[Optional[str]] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    aliases: Mapped[List["TeamAlias"]] = relationship("TeamAlias", back_populates="team")


class TeamAlias(Base):
    __tablename__ = "team_aliases"
    __table_args__ = (
        UniqueConstraint("provider_id", "source_name", name="uq_team_alias_provider_source"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    team_id: Mapped[str] = mapped_column(String(36), ForeignKey("teams.id"), nullable=False)
    provider_id: Mapped[str] = mapped_column(String(36), ForeignKey("providers.id"))
    source_name: Mapped[str] = mapped_column(String(256), nullable=False)

    team: Mapped["Team"] = relationship("Team", back_populates="aliases")


# ============================================================
#  Players
# ============================================================

class Player(Base):
    __tablename__ = "players"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    canonical_name: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    aliases: Mapped[List["PlayerAlias"]] = relationship("PlayerAlias", back_populates="player")
    attributes: Mapped[List["PlayerAttribute"]] = relationship("PlayerAttribute", back_populates="player")


class PlayerAlias(Base):
    __tablename__ = "player_aliases"
    __table_args__ = (
        UniqueConstraint("provider_id", "source_player_id", name="uq_player_alias_provider_source"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    player_id: Mapped[str] = mapped_column(String(36), ForeignKey("players.id"), nullable=False)
    provider_id: Mapped[str] = mapped_column(String(36), ForeignKey("providers.id"))
    source_player_id: Mapped[str] = mapped_column(String(64), nullable=False)  # e.g., Cricsheet 8-char hex
    source_name: Mapped[str] = mapped_column(String(256), nullable=False)

    player: Mapped["Player"] = relationship("Player", back_populates="aliases")


class PlayerNameAlias(Base):
    __tablename__ = "player_name_aliases"
    __table_args__ = (UniqueConstraint("player_id", "alias", name="uq_player_name_alias"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    player_id: Mapped[str] = mapped_column(String(36), ForeignKey("players.id"), nullable=False)
    alias: Mapped[str] = mapped_column(String(256), nullable=False)
    source: Mapped[str] = mapped_column(String(128), nullable=False, default="Cricsheet names.csv")


class PlayerAttribute(Base):
    """
    Time-varying player attributes with provenance (batting hand, bowling style, nationality, etc.)
    Not assumed to be complete or accurate — stored with source and confidence.
    """
    __tablename__ = "player_attributes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    player_id: Mapped[str] = mapped_column(String(36), ForeignKey("players.id"), nullable=False)
    attribute_type: Mapped[str] = mapped_column(String(64), nullable=False)
    attribute_value: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[Optional[str]] = mapped_column(String(128))
    confidence: Mapped[Optional[str]] = mapped_column(String(32))  # "high", "medium", "low"
    valid_from: Mapped[Optional[date]] = mapped_column(Date)
    valid_to: Mapped[Optional[date]] = mapped_column(Date)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())

    player: Mapped["Player"] = relationship("Player", back_populates="attributes")

    __table_args__ = (
        Index("ix_player_attr_player_type", "player_id", "attribute_type"),
    )


class PlayerNationalityEvidence(Base):
    """Auditable nationality/playing-affiliation evidence; never inferred from franchise teams."""
    __tablename__ = "player_nationality_evidence"
    __table_args__ = (
        Index("ix_nationality_evidence_player", "player_id"),
        Index("ix_nationality_evidence_value", "nationality"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    player_id: Mapped[str] = mapped_column(String(36), ForeignKey("players.id", ondelete="CASCADE"), nullable=False)
    nationality: Mapped[str] = mapped_column(String(128), nullable=False)
    source: Mapped[str] = mapped_column(String(128), nullable=False)
    verification_status: Mapped[str] = mapped_column(String(24), nullable=False)
    confidence: Mapped[str] = mapped_column(String(16), nullable=False)
    evidence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    valid_from: Mapped[Optional[date]] = mapped_column(Date)
    valid_to: Mapped[Optional[date]] = mapped_column(Date)
    details: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)


class PlayerExternalProfile(Base):
    """Cached provider identity and basic stats; never replaces CPI delivery analytics."""
    __tablename__ = "player_external_profiles"
    __table_args__ = (UniqueConstraint("provider_id", "provider_player_id", name="uq_player_external_provider_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    player_id: Mapped[str] = mapped_column(String(36), ForeignKey("players.id", ondelete="CASCADE"), nullable=False, index=True)
    provider_id: Mapped[str] = mapped_column(String(36), ForeignKey("providers.id"), nullable=False)
    provider_player_id: Mapped[str] = mapped_column(String(128), nullable=False)
    basic_stats: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())


class AuctionPredictedXI(Base):
    __tablename__ = "auction_predicted_xis"
    __table_args__ = (Index("ix_auction_predicted_xi_scenario_team", "scenario_id", "team_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    scenario_id: Mapped[str] = mapped_column(String(36), ForeignKey("auction_scenarios.id", ondelete="CASCADE"), nullable=False)
    team_id: Mapped[str] = mapped_column(String(36), ForeignKey("auction_teams.id", ondelete="CASCADE"), nullable=False)
    style: Mapped[str] = mapped_column(String(32), nullable=False, default="balanced")
    rules_version: Mapped[int] = mapped_column(Integer, nullable=False)
    result_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())


# ============================================================
#  Venues
# ============================================================

class Venue(Base):
    __tablename__ = "venues"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(512), unique=True, nullable=False)
    canonical_name: Mapped[str] = mapped_column(String(512), nullable=False)
    source_venue_id: Mapped[Optional[str]] = mapped_column(String(64))
    city: Mapped[Optional[str]] = mapped_column(String(128))
    country: Mapped[Optional[str]] = mapped_column(String(128))


class VenueAlias(Base):
    __tablename__ = "venue_aliases"
    __table_args__ = (UniqueConstraint("source_venue_id", "source_name", name="uq_venue_alias_source_name"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    venue_id: Mapped[str] = mapped_column(String(36), ForeignKey("venues.id"), nullable=False)
    source_venue_id: Mapped[str] = mapped_column(String(64), nullable=False)
    source_name: Mapped[str] = mapped_column(String(512), nullable=False)


# ============================================================
#  Matches
# ============================================================

class Match(Base):
    __tablename__ = "matches"
    __table_args__ = (
        UniqueConstraint("provider_id", "source_match_id", name="uq_match_provider_source"),
        Index("ix_match_season", "season"),
        Index("ix_match_start_date", "start_date"),
        Index("ix_match_format", "match_format"),
        Index("ix_match_tournament_date", "tournament_id", "start_date"),
        Index("ix_match_venue_date", "venue_id", "start_date"),
        Index("ix_match_team1_date", "team1_id", "start_date"),
        Index("ix_match_team2_date", "team2_id", "start_date"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    provider_id: Mapped[str] = mapped_column(String(36), ForeignKey("providers.id"), nullable=False)
    source_match_id: Mapped[str] = mapped_column(String(256), nullable=False)
    tournament_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("tournaments.id"))
    venue_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("venues.id"))
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    gender: Mapped[str] = mapped_column(String(16), nullable=False)
    match_format: Mapped[str] = mapped_column(String(32), nullable=False)
    season: Mapped[str] = mapped_column(String(16), nullable=False)
    team1_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("teams.id"))
    team2_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("teams.id"))
    toss_winner_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("teams.id"))
    toss_decision: Mapped[Optional[str]] = mapped_column(String(16))
    winner_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("teams.id"))
    result_type: Mapped[Optional[str]] = mapped_column(String(32))
    result_margin_runs: Mapped[Optional[int]] = mapped_column(Integer)
    result_margin_wickets: Mapped[Optional[int]] = mapped_column(SmallInteger)
    raw_source_checksum: Mapped[Optional[str]] = mapped_column(String(64))
    source_revision: Mapped[int] = mapped_column(Integer, default=0)
    source_data_version: Mapped[Optional[str]] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())

    innings: Mapped[List["MatchInnings"]] = relationship("MatchInnings", back_populates="match")


# ============================================================
#  Match Innings
# ============================================================

class MatchInnings(Base):
    __tablename__ = "match_innings"
    __table_args__ = (
        UniqueConstraint("match_id", "innings_number", name="uq_innings_match_number"),
        Index("ix_innings_match_id", "match_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    match_id: Mapped[str] = mapped_column(String(36), ForeignKey("matches.id"), nullable=False)
    innings_number: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    batting_team_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("teams.id"))
    target_runs: Mapped[Optional[int]] = mapped_column(Integer)
    target_overs: Mapped[Optional[int]] = mapped_column(SmallInteger)
    is_super_over: Mapped[bool] = mapped_column(Boolean, default=False)

    match: Mapped["Match"] = relationship("Match", back_populates="innings")
    deliveries: Mapped[List["Delivery"]] = relationship("Delivery", back_populates="innings")


# ============================================================
#  Deliveries
# ============================================================

class Delivery(Base):
    __tablename__ = "deliveries"
    __table_args__ = (
        UniqueConstraint("innings_id", "over_number", "delivery_sequence", name="uq_delivery_innings_over_seq"),
        Index("ix_delivery_innings_id", "innings_id"),
        Index("ix_delivery_batter_id", "batter_id"),
        Index("ix_delivery_bowler_id", "bowler_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    innings_id: Mapped[str] = mapped_column(String(36), ForeignKey("match_innings.id"), nullable=False)
    over_number: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    delivery_sequence: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    source_delivery_label: Mapped[Optional[str]] = mapped_column(String(16))
    batter_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("players.id"))
    bowler_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("players.id"))
    non_striker_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("players.id"))
    batter_runs: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    extras_runs: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    total_runs: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    bowling_runs: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    is_legal_ball: Mapped[bool] = mapped_column(Boolean, nullable=False)
    is_ball_faced_by_batter: Mapped[bool] = mapped_column(Boolean, nullable=False)
    is_boundary_four: Mapped[bool] = mapped_column(Boolean, default=False)
    is_boundary_six: Mapped[bool] = mapped_column(Boolean, default=False)
    phase: Mapped[Optional[str]] = mapped_column(String(16))
    has_replacement: Mapped[bool] = mapped_column(Boolean, default=False)

    innings: Mapped["MatchInnings"] = relationship("MatchInnings", back_populates="deliveries")
    extras: Mapped[List["DeliveryExtra"]] = relationship("DeliveryExtra", back_populates="delivery")
    wickets: Mapped[List["Wicket"]] = relationship("Wicket", back_populates="delivery")


# ============================================================
#  Delivery Extras
# ============================================================

class DeliveryExtra(Base):
    __tablename__ = "delivery_extras"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    delivery_id: Mapped[str] = mapped_column(String(36), ForeignKey("deliveries.id"), nullable=False)
    extra_type: Mapped[str] = mapped_column(String(16), nullable=False)
    runs: Mapped[int] = mapped_column(SmallInteger, nullable=False)

    delivery: Mapped["Delivery"] = relationship("Delivery", back_populates="extras")

    __table_args__ = (
        Index("ix_extra_delivery_id", "delivery_id"),
    )


# ============================================================
#  Wickets
# ============================================================

class Wicket(Base):
    __tablename__ = "wickets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    delivery_id: Mapped[str] = mapped_column(String(36), ForeignKey("deliveries.id"), nullable=False)
    player_out_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("players.id"))
    dismissal_type: Mapped[str] = mapped_column(String(64), nullable=False)
    is_bowler_wicket: Mapped[bool] = mapped_column(Boolean, nullable=False)
    is_batter_dismissed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    fielder_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("players.id"))

    delivery: Mapped["Delivery"] = relationship("Delivery", back_populates="wickets")

    __table_args__ = (
        Index("ix_wicket_delivery_id", "delivery_id"),
        Index("ix_wicket_player_out_id", "player_out_id"),
    )


# ============================================================
#  Raw Match Archive (for idempotent reprocessing)
# ============================================================

class RawMatch(Base):
    __tablename__ = "raw_matches"
    __table_args__ = (
        UniqueConstraint("provider_id", "source_match_id", name="uq_raw_match_provider_source"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    provider_id: Mapped[str] = mapped_column(String(36), ForeignKey("providers.id"), nullable=False)
    source_match_id: Mapped[str] = mapped_column(String(256), nullable=False)
    source_file_name: Mapped[str] = mapped_column(String(512), nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    source_revision: Mapped[int] = mapped_column(Integer, default=0)
    raw_json: Mapped[Optional[dict]] = mapped_column(JSON)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())


# ============================================================
#  Ingestion Run Log
# ============================================================

class IngestionRun(Base):
    __tablename__ = "ingestion_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    provider_id: Mapped[str] = mapped_column(String(36), ForeignKey("providers.id"), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(32), default="running")
    matches_discovered: Mapped[int] = mapped_column(Integer, default=0)
    matches_inserted: Mapped[int] = mapped_column(Integer, default=0)
    matches_updated: Mapped[int] = mapped_column(Integer, default=0)
    matches_skipped: Mapped[int] = mapped_column(Integer, default=0)
    matches_failed: Mapped[int] = mapped_column(Integer, default=0)
    error_summary: Mapped[Optional[str]] = mapped_column(Text)


# ============================================================
#  Auction Intelligence (auction records stay separate from match data)
# ============================================================

class AuctionScenario(Base):
    __tablename__ = "auction_scenarios"
    __table_args__ = (Index("ix_auction_scenario_status_season", "status", "season"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    season: Mapped[str] = mapped_column(String(16), nullable=False)
    auction_type: Mapped[str] = mapped_column(String(16), nullable=False, default="CUSTOM")
    competition: Mapped[str] = mapped_column(String(128), nullable=False, default="Indian Premier League")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="DRAFT")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())


class AuctionRule(Base):
    __tablename__ = "auction_rules"
    __table_args__ = (UniqueConstraint("scenario_id", "version", name="uq_auction_rule_scenario_version"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    scenario_id: Mapped[str] = mapped_column(String(36), ForeignKey("auction_scenarios.id", ondelete="CASCADE"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    rules_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    effective_from: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())


class AuctionTeam(Base):
    __tablename__ = "auction_teams"
    __table_args__ = (UniqueConstraint("scenario_id", "franchise_code", name="uq_auction_team_scenario_code"),
                      Index("ix_auction_team_scenario", "scenario_id"))

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    scenario_id: Mapped[str] = mapped_column(String(36), ForeignKey("auction_scenarios.id", ondelete="CASCADE"), nullable=False)
    franchise_name: Mapped[str] = mapped_column(String(128), nullable=False)
    franchise_code: Mapped[str] = mapped_column(String(32), nullable=False)
    initial_purse: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    remaining_purse: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    minimum_squad_size: Mapped[int] = mapped_column(Integer, nullable=False, default=18)
    maximum_squad_size: Mapped[int] = mapped_column(Integer, nullable=False, default=25)
    overseas_squad_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=8)


class AuctionPlayer(Base):
    __tablename__ = "auction_players"
    __table_args__ = (UniqueConstraint("scenario_id", "player_id", name="uq_auction_player_scenario_player"),
                      Index("ix_auction_player_scenario_status", "scenario_id", "availability_status"))

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    scenario_id: Mapped[str] = mapped_column(String(36), ForeignKey("auction_scenarios.id", ondelete="CASCADE"), nullable=False)
    player_id: Mapped[str] = mapped_column(String(36), ForeignKey("players.id"), nullable=False)
    base_price: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    auction_category: Mapped[Optional[str]] = mapped_column(String(64))
    availability_status: Mapped[str] = mapped_column(String(16), nullable=False, default="AVAILABLE")
    auction_order: Mapped[Optional[int]] = mapped_column(Integer)
    primary_role: Mapped[Optional[str]] = mapped_column(String(64))
    secondary_role: Mapped[Optional[str]] = mapped_column(String(64))
    nationality: Mapped[Optional[str]] = mapped_column(String(128))
    overseas_eligible: Mapped[Optional[bool]] = mapped_column(Boolean)
    wicketkeeper: Mapped[Optional[bool]] = mapped_column(Boolean)
    identity_match_status: Mapped[str] = mapped_column(String(16), nullable=False, default="MATCHED")


class AuctionRetention(Base):
    __tablename__ = "auction_retentions"
    __table_args__ = (UniqueConstraint("scenario_id", "player_id", name="uq_auction_retention_scenario_player"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    scenario_id: Mapped[str] = mapped_column(String(36), ForeignKey("auction_scenarios.id", ondelete="CASCADE"), nullable=False)
    team_id: Mapped[str] = mapped_column(String(36), ForeignKey("auction_teams.id", ondelete="CASCADE"), nullable=False)
    player_id: Mapped[str] = mapped_column(String(36), ForeignKey("players.id"), nullable=False)
    retention_price: Mapped[Optional[float]] = mapped_column(Numeric(14, 2))
    retention_category: Mapped[Optional[str]] = mapped_column(String(64))
    retention_order: Mapped[Optional[int]] = mapped_column(Integer)


class AuctionImport(Base):
    __tablename__ = "auction_imports"
    __table_args__ = (Index("ix_auction_import_scenario_created", "scenario_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    scenario_id: Mapped[str] = mapped_column(String(36), ForeignKey("auction_scenarios.id", ondelete="CASCADE"), nullable=False)
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    data_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    accepted_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rejected_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    report_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())


class AuctionSession(Base):
    __tablename__ = "auction_sessions"
    __table_args__ = (Index("ix_auction_session_scenario_status", "scenario_id", "session_status"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    scenario_id: Mapped[str] = mapped_column(String(36), ForeignKey("auction_scenarios.id", ondelete="CASCADE"), nullable=False)
    session_status: Mapped[str] = mapped_column(String(16), nullable=False, default="READY")
    active_player_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("players.id"))
    current_team_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("auction_teams.id"))
    current_bid: Mapped[Optional[float]] = mapped_column(Numeric(14, 2))
    simulation_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="INTERACTIVE")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())


class AuctionEvent(Base):
    __tablename__ = "auction_events"
    __table_args__ = (UniqueConstraint("session_id", "sequence_number", name="uq_auction_event_session_sequence"),
                      Index("ix_auction_event_session", "session_id", "sequence_number"))

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(String(36), ForeignKey("auction_sessions.id", ondelete="CASCADE"), nullable=False)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    player_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("players.id"))
    team_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("auction_teams.id"))
    bid_amount: Mapped[Optional[float]] = mapped_column(Numeric(14, 2))
    event_payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())


class AuctionBid(Base):
    __tablename__ = "auction_bids"
    __table_args__ = (Index("ix_auction_bid_session_player", "session_id", "player_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(String(36), ForeignKey("auction_sessions.id", ondelete="CASCADE"), nullable=False)
    player_id: Mapped[str] = mapped_column(String(36), ForeignKey("players.id"), nullable=False)
    team_id: Mapped[str] = mapped_column(String(36), ForeignKey("auction_teams.id"), nullable=False)
    bid_amount: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    bid_source: Mapped[str] = mapped_column(String(8), nullable=False, default="USER")
    accepted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())


class AuctionPurchase(Base):
    __tablename__ = "auction_purchases"
    __table_args__ = (UniqueConstraint("session_id", "player_id", name="uq_auction_purchase_session_player"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(String(36), ForeignKey("auction_sessions.id", ondelete="CASCADE"), nullable=False)
    player_id: Mapped[str] = mapped_column(String(36), ForeignKey("players.id"), nullable=False)
    team_id: Mapped[str] = mapped_column(String(36), ForeignKey("auction_teams.id"), nullable=False)
    purchase_price: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    acquisition_type: Mapped[str] = mapped_column(String(16), nullable=False, default="AUCTION")
    auction_event_id: Mapped[str] = mapped_column(String(36), ForeignKey("auction_events.id"), nullable=False)


class AuctionHistoryRecord(Base):
    """Imported historical outcomes with original source fields preserved."""
    __tablename__ = "auction_history_records"
    __table_args__ = (
        UniqueConstraint("source_name", "source_record_key", name="uq_auction_history_source_key"),
        Index("ix_auction_history_year_status", "auction_year", "status"),
        Index("ix_auction_history_player_year", "player_id", "auction_year"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    player_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("players.id"))
    source_player_id: Mapped[Optional[str]] = mapped_column(String(64))
    source_player_name: Mapped[str] = mapped_column(String(256), nullable=False)
    identity_match_status: Mapped[str] = mapped_column(String(16), nullable=False, default="UNRESOLVED")
    auction_year: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    franchise_name: Mapped[Optional[str]] = mapped_column(String(128))
    role: Mapped[Optional[str]] = mapped_column(String(64))
    nationality: Mapped[Optional[str]] = mapped_column(String(64))
    base_price_lakh: Mapped[Optional[float]] = mapped_column(Numeric(14, 2))
    final_price_lakh: Mapped[Optional[float]] = mapped_column(Numeric(14, 2))
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    acquisition_type: Mapped[str] = mapped_column(String(16), nullable=False, default="auction")
    source_name: Mapped[str] = mapped_column(String(256), nullable=False)
    source_url: Mapped[Optional[str]] = mapped_column(String(512))
    source_record_key: Mapped[str] = mapped_column(String(128), nullable=False)
    imported_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())


class AuctionModelRun(Base):
    __tablename__ = "auction_model_runs"
    __table_args__ = (Index("ix_auction_model_run_task_created", "task", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    task: Mapped[str] = mapped_column(String(32), nullable=False)
    model_version: Mapped[str] = mapped_column(String(64), nullable=False)
    training_rows: Mapped[int] = mapped_column(Integer, nullable=False)
    validation_rows: Mapped[int] = mapped_column(Integer, nullable=False)
    evaluation_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    feature_schema_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    artifact_path: Mapped[str] = mapped_column(String(512), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())


class AuctionHistoryImport(Base):
    __tablename__ = "auction_history_imports"
    __table_args__ = (Index("ix_auction_history_import_created", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    source_name: Mapped[str] = mapped_column(String(256), nullable=False)
    source_url: Mapped[Optional[str]] = mapped_column(String(512))
    accepted_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duplicate_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rejected_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    report_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())


# ============================================================
#  Win Probability (precomputed per-match curves and player WPA)
# ============================================================

class MatchWinProbability(Base):
    __tablename__ = "match_win_probabilities"
    __table_args__ = (Index("ix_match_wp_family_version", "format_family", "model_version"),)

    match_id: Mapped[str] = mapped_column(String(36), ForeignKey("matches.id", ondelete="CASCADE"), primary_key=True)
    match_format: Mapped[str] = mapped_column(String(32), nullable=False)
    format_family: Mapped[str] = mapped_column(String(16), nullable=False)
    model_version: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    delivery_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    predictions_gzip: Mapped[Optional[bytes]] = mapped_column(LargeBinary)
    exclusion_reason: Mapped[Optional[str]] = mapped_column(Text)
    built_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now())


class PlayerWinProbabilityImpact(Base):
    __tablename__ = "player_win_probability_impact"
    __table_args__ = (
        UniqueConstraint("player_id", "match_format", name="uq_player_wpa_format"),
        Index("ix_player_wpa_player", "player_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    player_id: Mapped[str] = mapped_column(String(36), ForeignKey("players.id", ondelete="CASCADE"), nullable=False)
    match_format: Mapped[str] = mapped_column(String(32), nullable=False)
    matches: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    batting_wpa: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    bowling_wpa: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    peak_delivery_impact: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    peak_match_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("matches.id", ondelete="SET NULL"))


# ============================================================
#  Cricsheet Auto-Sync
# ============================================================

class SyncSource(Base):
    """One monitored Cricsheet archive (e.g. all_json.zip) and its last-seen HTTP/checksum state."""
    __tablename__ = "sync_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_key: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    label: Mapped[Optional[str]] = mapped_column(String(128))
    archive_url: Mapped[str] = mapped_column(String(512), nullable=False)
    latest_checksum: Mapped[Optional[str]] = mapped_column(String(64))   # sha256 of last fully imported archive
    etag: Mapped[Optional[str]] = mapped_column(String(256))
    last_modified: Mapped[Optional[str]] = mapped_column(String(256))
    archive_size_bytes: Mapped[Optional[int]] = mapped_column(BigInteger)
    last_checked_at: Mapped[Optional[datetime]] = mapped_column(DateTime)   # last *successful* upstream check
    last_imported_at: Mapped[Optional[datetime]] = mapped_column(DateTime)  # last fully successful import
    last_error: Mapped[Optional[str]] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now(), onupdate=func.now())


class SyncHistory(Base):
    """One synchronisation attempt for one source. Rows from the same cycle share run_id."""
    __tablename__ = "sync_history"
    __table_args__ = (
        Index("ix_sync_history_started", "started_at"),
        Index("ix_sync_history_run", "run_id"),
        Index("ix_sync_history_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(String(36), nullable=False)
    source_key: Mapped[str] = mapped_column(String(80), nullable=False)
    triggered_by: Mapped[str] = mapped_column(String(32), nullable=False, default="scheduler")  # scheduler | manual | startup
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now())
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    # running | completed | no_changes | partial | failed | interrupted
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="running")
    # checking_source | downloading | extracting | validating | importing | refreshing_statistics | completed | failed
    phase: Mapped[str] = mapped_column(String(32), nullable=False, default="checking_source")
    progress_current: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    progress_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    archive_changed: Mapped[Optional[bool]] = mapped_column(Boolean)
    archive_checksum: Mapped[Optional[str]] = mapped_column(String(64))
    matches_discovered: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    new_matches: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_matches: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unchanged_matches: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_records: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_detail: Mapped[Optional[str]] = mapped_column(Text)
    failed_files: Mapped[Optional[list]] = mapped_column(JSON)
    stats_refresh: Mapped[Optional[dict]] = mapped_column(JSON)
    duration_seconds: Mapped[Optional[float]] = mapped_column(Float)


class SyncMatchRevision(Base):
    """Audit row written whenever an already-imported match's source JSON checksum changes."""
    __tablename__ = "sync_match_revisions"
    __table_args__ = (
        Index("ix_sync_revision_source_match", "source_match_id"),
        Index("ix_sync_revision_revised_at", "revised_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    match_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("matches.id", ondelete="SET NULL"))
    source_match_id: Mapped[str] = mapped_column(String(256), nullable=False)
    source_key: Mapped[str] = mapped_column(String(80), nullable=False)
    sync_history_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("sync_history.id", ondelete="SET NULL"))
    previous_checksum: Mapped[Optional[str]] = mapped_column(String(64))
    new_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    revised_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now())


class SyncSettings(Base):
    """Singleton row (id=1) holding user-editable scheduler settings and the manual-sync request flag."""
    __tablename__ = "sync_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    auto_sync_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    interval_hours: Mapped[float] = mapped_column(Float, nullable=False, default=6.0)
    check_on_start: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    manual_requested_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    # Set explicitly (UTC) only when a user edits settings; the worker treats a change as "reschedule".
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class SyncWorkerState(Base):
    """Singleton row (id=1) with the background worker's heartbeat and schedule."""
    __tablename__ = "sync_worker_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="stopped")  # idle | syncing | stopped
    pid: Mapped[Optional[int]] = mapped_column(Integer)
    hostname: Mapped[Optional[str]] = mapped_column(String(256))
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    heartbeat_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    last_run_started_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    last_success_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    next_check_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    last_error: Mapped[Optional[str]] = mapped_column(Text)
