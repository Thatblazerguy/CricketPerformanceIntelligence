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
        Index("ix_delivery_non_striker_id", "non_striker_id"),
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
    # AI auction room (simulation_mode="AI_ROOM"): engine state and the market
    # context it runs on. Bids, calls and sales are still written as ordinary
    # AuctionEvent / AuctionBid / AuctionPurchase rows.
    context_key: Mapped[Optional[str]] = mapped_column(String(64))
    state: Mapped[Optional[dict]] = mapped_column(JSON)


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
    # Extended provenance and auction-context fields (all optional; NULL = not in source).
    set_code: Mapped[Optional[str]] = mapped_column(String(16))
    lot_number: Mapped[Optional[int]] = mapped_column(Integer)
    capped_status: Mapped[Optional[str]] = mapped_column(String(32))
    is_rtm: Mapped[Optional[bool]] = mapped_column(Boolean)
    previous_franchise: Mapped[Optional[str]] = mapped_column(String(16))
    country: Mapped[Optional[str]] = mapped_column(String(64))
    bowling_style: Mapped[Optional[str]] = mapped_column(String(64))
    ipl_matches_before: Mapped[Optional[int]] = mapped_column(Integer)
    age_at_auction: Mapped[Optional[int]] = mapped_column(SmallInteger)
    date_of_birth: Mapped[Optional[date]] = mapped_column(Date)
    source_revision: Mapped[Optional[str]] = mapped_column(String(64))
    source_tier: Mapped[Optional[str]] = mapped_column(String(32))


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
#  Auction Intelligence v2: season rules, reconciled lots, models, simulation
# ============================================================

class AuctionSeason(Base):
    """Season-specific auction regulations. Each rule carries its own provenance in ``rule_sources``."""
    __tablename__ = "auction_seasons"

    season: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    auction_date: Mapped[Optional[date]] = mapped_column(Date)
    auction_type: Mapped[str] = mapped_column(String(8), nullable=False)  # MEGA / MINI
    location: Mapped[Optional[str]] = mapped_column(String(128))
    purse_lakh: Mapped[Optional[float]] = mapped_column(Numeric(10, 2))
    min_squad: Mapped[Optional[int]] = mapped_column(SmallInteger)
    max_squad: Mapped[Optional[int]] = mapped_column(SmallInteger)
    max_overseas_squad: Mapped[Optional[int]] = mapped_column(SmallInteger)
    max_overseas_xi: Mapped[Optional[int]] = mapped_column(SmallInteger)
    min_base_price_lakh: Mapped[Optional[float]] = mapped_column(Numeric(10, 2))
    rtm_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    max_retentions: Mapped[Optional[int]] = mapped_column(SmallInteger)
    bid_increments: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    rule_sources: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    pool_completeness: Mapped[str] = mapped_column(String(16), nullable=False, default="none")
    notes: Mapped[Optional[str]] = mapped_column(Text)


class AuctionLot(Base):
    """Reconciled player-season auction outcome built from one or more source records."""
    __tablename__ = "auction_lots"
    __table_args__ = (
        UniqueConstraint("season", "player_key", "acquisition_type", name="uq_auction_lot_season_player"),
        Index("ix_auction_lot_season_status", "season", "status"),
        Index("ix_auction_lot_player", "player_id"),
        Index("ix_auction_lot_franchise", "franchise", "season"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    season: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    player_key: Mapped[str] = mapped_column(String(64), nullable=False)
    player_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("players.id"))
    player_name: Mapped[str] = mapped_column(String(256), nullable=False)
    identity_status: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)          # SOLD / UNSOLD / RETAINED
    acquisition_type: Mapped[str] = mapped_column(String(16), nullable=False)  # auction / retained
    franchise: Mapped[Optional[str]] = mapped_column(String(8))
    previous_franchise: Mapped[Optional[str]] = mapped_column(String(8))
    base_price_lakh: Mapped[Optional[float]] = mapped_column(Numeric(10, 2))
    final_price_lakh: Mapped[Optional[float]] = mapped_column(Numeric(10, 2))
    set_code: Mapped[Optional[str]] = mapped_column(String(16))
    lot_number: Mapped[Optional[int]] = mapped_column(Integer)
    role: Mapped[Optional[str]] = mapped_column(String(8))
    bowling_kind: Mapped[Optional[str]] = mapped_column(String(8))
    overseas: Mapped[Optional[bool]] = mapped_column(Boolean)
    capped: Mapped[Optional[bool]] = mapped_column(Boolean)
    is_rtm: Mapped[Optional[bool]] = mapped_column(Boolean)
    age_at_auction: Mapped[Optional[int]] = mapped_column(SmallInteger)
    ipl_matches_before: Mapped[Optional[int]] = mapped_column(Integer)
    verification: Mapped[str] = mapped_column(String(16), nullable=False)  # corroborated / single_source / conflict
    source_count: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    sources: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    conflict_note: Mapped[Optional[str]] = mapped_column(Text)
    built_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())


class AuctionFranchiseSeason(Base):
    __tablename__ = "auction_franchise_seasons"
    __table_args__ = (UniqueConstraint("season", "franchise", name="uq_auction_franchise_season"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    season: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    franchise: Mapped[str] = mapped_column(String(8), nullable=False)
    purse_before_auction_lakh: Mapped[Optional[float]] = mapped_column(Numeric(10, 2))
    purse_basis: Mapped[str] = mapped_column(String(24), nullable=False)  # sourced / derived_from_retentions / unknown
    retained_count: Mapped[Optional[int]] = mapped_column(SmallInteger)
    retained_overseas: Mapped[Optional[int]] = mapped_column(SmallInteger)
    retained_spend_lakh: Mapped[Optional[float]] = mapped_column(Numeric(10, 2))
    slots_left: Mapped[Optional[int]] = mapped_column(SmallInteger)
    overseas_slots_left: Mapped[Optional[int]] = mapped_column(SmallInteger)
    source: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class AuctionFeatureSnapshot(Base):
    """Point-in-time player features computed only from matches before ``as_of``."""
    __tablename__ = "auction_feature_snapshots"
    __table_args__ = (UniqueConstraint("player_id", "as_of", "feature_version", name="uq_auction_feature_snapshot"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    player_id: Mapped[str] = mapped_column(String(36), ForeignKey("players.id", ondelete="CASCADE"), nullable=False)
    as_of: Mapped[date] = mapped_column(Date, nullable=False)
    feature_version: Mapped[str] = mapped_column(String(16), nullable=False)
    features: Mapped[dict] = mapped_column(JSON, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())


class AuctionBacktestPrediction(Base):
    __tablename__ = "auction_backtest_predictions"
    __table_args__ = (Index("ix_auction_backtest_model_season", "model_version", "season"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    model_version: Mapped[str] = mapped_column(String(64), nullable=False)
    season: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    lot_id: Mapped[str] = mapped_column(String(36), ForeignKey("auction_lots.id", ondelete="CASCADE"), nullable=False)
    player_id: Mapped[Optional[str]] = mapped_column(String(36))
    actual_status: Mapped[str] = mapped_column(String(16), nullable=False)
    actual_price_lakh: Mapped[Optional[float]] = mapped_column(Numeric(10, 2))
    actual_franchise: Mapped[Optional[str]] = mapped_column(String(8))
    p10_lakh: Mapped[Optional[float]] = mapped_column(Numeric(10, 2))
    p50_lakh: Mapped[Optional[float]] = mapped_column(Numeric(10, 2))
    p90_lakh: Mapped[Optional[float]] = mapped_column(Numeric(10, 2))
    sold_probability: Mapped[Optional[float]] = mapped_column(Float)
    baselines: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    details: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


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


# ============================================================
#  Hybrid data engine: canonical match identity, scorecard layer, coverage
# ============================================================
#
# Design rule: the ball-by-ball layer (matches / match_innings / deliveries) is
# untouched. Every existing analytics module keeps reading only those tables, so
# scorecard-only data physically cannot leak into delivery-level metrics.
# canonical_matches gives every real-world match exactly one CPI identity; it
# links to a ``matches`` row when (and only when) delivery data exists.

class CanonicalMatchRecord(Base):
    __tablename__ = "canonical_matches"
    __table_args__ = (
        Index("ix_canonical_match_date", "start_date"),
        Index("ix_canonical_match_scope", "format_class", "gender", "start_date"),
        Index("ix_canonical_match_coverage", "coverage_status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    # Ball-by-ball layer link; NULL for scorecard-only / metadata-only matches.
    match_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("matches.id", ondelete="SET NULL"), unique=True)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[Optional[date]] = mapped_column(Date)
    gender: Mapped[str] = mapped_column(String(16), nullable=False)
    match_format: Mapped[str] = mapped_column(String(32), nullable=False)   # source format (Test, ODI, MDM, ...)
    format_class: Mapped[str] = mapped_column(String(24), nullable=False)   # TEST/ODI/T20I/FIRST_CLASS/LIST_A/T20_DOMESTIC/MULTI_DAY/ONE_DAY
    season: Mapped[Optional[str]] = mapped_column(String(16))
    competition_name: Mapped[Optional[str]] = mapped_column(String(256))
    tournament_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("tournaments.id"))
    venue_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("venues.id"))
    venue_name: Mapped[Optional[str]] = mapped_column(String(512))
    country: Mapped[Optional[str]] = mapped_column(String(128))
    team1_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("teams.id"))
    team2_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("teams.id"))
    team1_name: Mapped[str] = mapped_column(String(256), nullable=False)
    team2_name: Mapped[str] = mapped_column(String(256), nullable=False)
    toss_winner_name: Mapped[Optional[str]] = mapped_column(String(256))
    toss_decision: Mapped[Optional[str]] = mapped_column(String(16))
    winner_name: Mapped[Optional[str]] = mapped_column(String(256))
    result_type: Mapped[Optional[str]] = mapped_column(String(32))
    # Coverage (FULL_BALL_BY_BALL / PARTIAL_BALL_BY_BALL / SCORECARD_ONLY / METADATA_ONLY / UNKNOWN)
    coverage_status: Mapped[str] = mapped_column(String(24), nullable=False, default="UNKNOWN")
    innings_available: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    innings_expected: Mapped[Optional[int]] = mapped_column(SmallInteger)
    deliveries_imported: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_count: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    missing_fields: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    coverage_notes: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    validation_status: Mapped[str] = mapped_column(String(24), nullable=False, default="unvalidated")
    last_ingested_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())


class MatchSourceRef(Base):
    """One external source's record of a canonical match (many per match, never merged blindly)."""
    __tablename__ = "match_source_refs"
    __table_args__ = (
        UniqueConstraint("source_key", "source_match_id", name="uq_match_source_ref"),
        Index("ix_match_source_ref_canonical", "canonical_match_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    canonical_match_id: Mapped[str] = mapped_column(String(36), ForeignKey("canonical_matches.id", ondelete="CASCADE"), nullable=False)
    source_key: Mapped[str] = mapped_column(String(64), nullable=False)
    source_match_id: Mapped[str] = mapped_column(String(256), nullable=False)
    data_level: Mapped[str] = mapped_column(String(16), nullable=False)  # ball_by_ball / scorecard / metadata
    match_method: Mapped[str] = mapped_column(String(32), nullable=False, default="primary")  # primary / matched / manual
    match_confidence: Mapped[Optional[float]] = mapped_column(Float)
    match_evidence: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    source_url: Mapped[Optional[str]] = mapped_column(String(512))
    attribution: Mapped[Optional[str]] = mapped_column(String(512))
    checksum: Mapped[Optional[str]] = mapped_column(String(64))
    retrieved_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())


class PlayerExternalId(Base):
    """Cross-provider person identifiers (Cricsheet people.csv keys). Kept apart from player_aliases on purpose."""
    __tablename__ = "player_external_ids"
    __table_args__ = (
        UniqueConstraint("id_scheme", "external_id", name="uq_player_external_id"),
        Index("ix_player_external_id_player", "player_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    player_id: Mapped[str] = mapped_column(String(36), ForeignKey("players.id", ondelete="CASCADE"), nullable=False)
    id_scheme: Mapped[str] = mapped_column(String(32), nullable=False)   # cricinfo / cricketarchive / bcci / cricbuzz ...
    external_id: Mapped[str] = mapped_column(String(128), nullable=False)
    source: Mapped[str] = mapped_column(String(128), nullable=False, default="Cricsheet people.csv")


class ScorecardInnings(Base):
    __tablename__ = "scorecard_innings"
    __table_args__ = (
        UniqueConstraint("source_ref_id", "innings_number", name="uq_scorecard_innings_ref_number"),
        Index("ix_scorecard_innings_canonical", "canonical_match_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    canonical_match_id: Mapped[str] = mapped_column(String(36), ForeignKey("canonical_matches.id", ondelete="CASCADE"), nullable=False)
    source_ref_id: Mapped[str] = mapped_column(String(36), ForeignKey("match_source_refs.id", ondelete="CASCADE"), nullable=False)
    innings_number: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    batting_team_name: Mapped[str] = mapped_column(String(256), nullable=False)
    batting_team_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("teams.id"))
    total_runs: Mapped[Optional[int]] = mapped_column(Integer)
    wickets: Mapped[Optional[int]] = mapped_column(SmallInteger)
    overs: Mapped[Optional[str]] = mapped_column(String(16))          # as printed, e.g. "49.3"
    balls_per_over: Mapped[Optional[int]] = mapped_column(SmallInteger)  # NULL when the source does not say
    extras_total: Mapped[Optional[int]] = mapped_column(SmallInteger)
    byes: Mapped[Optional[int]] = mapped_column(SmallInteger)
    leg_byes: Mapped[Optional[int]] = mapped_column(SmallInteger)
    wides: Mapped[Optional[int]] = mapped_column(SmallInteger)
    no_balls: Mapped[Optional[int]] = mapped_column(SmallInteger)
    penalty_runs: Mapped[Optional[int]] = mapped_column(SmallInteger)
    declared: Mapped[Optional[bool]] = mapped_column(Boolean)
    forfeited: Mapped[Optional[bool]] = mapped_column(Boolean)
    validation_status: Mapped[str] = mapped_column(String(24), nullable=False, default="unvalidated")
    validation_issues: Mapped[list] = mapped_column(JSON, nullable=False, default=list)


class ScorecardBatting(Base):
    __tablename__ = "scorecard_batting"
    __table_args__ = (
        Index("ix_scorecard_batting_player", "player_id"),
        Index("ix_scorecard_batting_innings", "scorecard_innings_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    scorecard_innings_id: Mapped[str] = mapped_column(String(36), ForeignKey("scorecard_innings.id", ondelete="CASCADE"), nullable=False)
    canonical_match_id: Mapped[str] = mapped_column(String(36), ForeignKey("canonical_matches.id", ondelete="CASCADE"), nullable=False)
    player_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("players.id"))
    identity_status: Mapped[str] = mapped_column(String(16), nullable=False, default="unresolved")
    source_player_name: Mapped[str] = mapped_column(String(256), nullable=False)
    source_player_id: Mapped[Optional[str]] = mapped_column(String(128))
    batting_position: Mapped[Optional[int]] = mapped_column(SmallInteger)
    did_not_bat: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    runs: Mapped[Optional[int]] = mapped_column(SmallInteger)
    balls_faced: Mapped[Optional[int]] = mapped_column(SmallInteger)
    minutes: Mapped[Optional[int]] = mapped_column(SmallInteger)
    fours: Mapped[Optional[int]] = mapped_column(SmallInteger)
    sixes: Mapped[Optional[int]] = mapped_column(SmallInteger)
    is_out: Mapped[Optional[bool]] = mapped_column(Boolean)           # NULL = source does not say
    dismissal_type: Mapped[Optional[str]] = mapped_column(String(64))
    dismissal_text: Mapped[Optional[str]] = mapped_column(String(256))


class ScorecardBowling(Base):
    __tablename__ = "scorecard_bowling"
    __table_args__ = (
        Index("ix_scorecard_bowling_player", "player_id"),
        Index("ix_scorecard_bowling_innings", "scorecard_innings_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    scorecard_innings_id: Mapped[str] = mapped_column(String(36), ForeignKey("scorecard_innings.id", ondelete="CASCADE"), nullable=False)
    canonical_match_id: Mapped[str] = mapped_column(String(36), ForeignKey("canonical_matches.id", ondelete="CASCADE"), nullable=False)
    player_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("players.id"))
    identity_status: Mapped[str] = mapped_column(String(16), nullable=False, default="unresolved")
    source_player_name: Mapped[str] = mapped_column(String(256), nullable=False)
    source_player_id: Mapped[Optional[str]] = mapped_column(String(128))
    overs: Mapped[Optional[str]] = mapped_column(String(16))
    legal_balls: Mapped[Optional[int]] = mapped_column(SmallInteger)  # only when balls-per-over is known
    maidens: Mapped[Optional[int]] = mapped_column(SmallInteger)
    runs_conceded: Mapped[Optional[int]] = mapped_column(SmallInteger)
    wickets: Mapped[Optional[int]] = mapped_column(SmallInteger)
    wides: Mapped[Optional[int]] = mapped_column(SmallInteger)
    no_balls: Mapped[Optional[int]] = mapped_column(SmallInteger)
    economy_reported: Mapped[Optional[float]] = mapped_column(Float)


class SourceInventoryItem(Base):
    """What an external source says exists, compared against what CPI holds."""
    __tablename__ = "source_inventory"
    __table_args__ = (
        UniqueConstraint("source_key", "source_match_id", name="uq_source_inventory"),
        Index("ix_source_inventory_status", "source_key", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    source_key: Mapped[str] = mapped_column(String(64), nullable=False)
    source_match_id: Mapped[str] = mapped_column(String(256), nullable=False)
    start_date: Mapped[Optional[date]] = mapped_column(Date)
    match_type: Mapped[Optional[str]] = mapped_column(String(32))
    team_type: Mapped[Optional[str]] = mapped_column(String(32))
    gender: Mapped[Optional[str]] = mapped_column(String(16))
    teams: Mapped[Optional[str]] = mapped_column(String(512))
    # available (listed, not yet compared) / imported / missing / failed
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="available")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[Optional[str]] = mapped_column(Text)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    last_attempt_at: Mapped[Optional[datetime]] = mapped_column(DateTime)


class ReconciliationFlag(Base):
    """A disagreement between sources for one player/innings/metric. Both values are kept."""
    __tablename__ = "reconciliation_flags"
    __table_args__ = (
        UniqueConstraint("canonical_match_id", "innings_number", "player_id", "metric", name="uq_reconciliation_flag"),
        Index("ix_reconciliation_flag_status", "status"),
        Index("ix_reconciliation_flag_player", "player_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    canonical_match_id: Mapped[str] = mapped_column(String(36), ForeignKey("canonical_matches.id", ondelete="CASCADE"), nullable=False)
    innings_number: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    player_id: Mapped[str] = mapped_column(String(36), ForeignKey("players.id", ondelete="CASCADE"), nullable=False)
    metric: Mapped[str] = mapped_column(String(32), nullable=False)
    values: Mapped[dict] = mapped_column(JSON, nullable=False)        # {source_key: value}
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")  # open / resolved
    resolution: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())


class HybridIngestionEvent(Base):
    """Ingestion log for the hybrid engine (inventory refreshes, scorecard imports, retries, reconciliation)."""
    __tablename__ = "hybrid_ingestion_events"
    __table_args__ = (Index("ix_hybrid_ingestion_event_created", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_key: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(48), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    detail: Mapped[Optional[str]] = mapped_column(Text)
    counts: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())


class MatchAppearance(Base):
    """A player's selection in a canonical match (playing XI), from any source.

    Deliveries only show players who batted, bowled or took a dismissal; this
    table records everyone who played, so match counts are not under-stated.
    """
    __tablename__ = "match_appearances"
    __table_args__ = (
        UniqueConstraint("canonical_match_id", "player_id", name="uq_match_appearance"),
        Index("ix_match_appearance_player", "player_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    canonical_match_id: Mapped[str] = mapped_column(String(36), ForeignKey("canonical_matches.id", ondelete="CASCADE"), nullable=False)
    player_id: Mapped[str] = mapped_column(String(36), ForeignKey("players.id", ondelete="CASCADE"), nullable=False)
    team_name: Mapped[Optional[str]] = mapped_column(String(256))
    source_key: Mapped[str] = mapped_column(String(64), nullable=False)
