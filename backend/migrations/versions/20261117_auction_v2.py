"""Auction Intelligence v2: season rules, reconciled lots, franchise purse state,
point-in-time feature snapshots and backtest predictions.
Also extends auction_history_records with set/lot/RTM/provenance columns.

Revision ID: 20261117auc3
Revises: 20261116teaminn1
"""
from alembic import op
import sqlalchemy as sa

from app.models.models import (
    AuctionSeason, AuctionLot, AuctionFranchiseSeason, AuctionFeatureSnapshot,
    AuctionBacktestPrediction,
)

revision = "20261117auc3"
down_revision = "20261116teaminn1"
branch_labels = None
depends_on = None

TABLES = [AuctionSeason.__table__, AuctionLot.__table__, AuctionFranchiseSeason.__table__,
          AuctionFeatureSnapshot.__table__, AuctionBacktestPrediction.__table__]

HISTORY_COLUMNS = [
    ("set_code", sa.String(16)), ("lot_number", sa.Integer()), ("capped_status", sa.String(32)),
    ("is_rtm", sa.Boolean()), ("previous_franchise", sa.String(16)), ("country", sa.String(64)),
    ("bowling_style", sa.String(64)), ("ipl_matches_before", sa.Integer()),
    ("age_at_auction", sa.SmallInteger()), ("date_of_birth", sa.Date()),
    ("source_revision", sa.String(64)), ("source_tier", sa.String(32)),
]


def upgrade():
    bind = op.get_bind()
    existing = {c["name"] for c in sa.inspect(bind).get_columns("auction_history_records")}
    for name, type_ in HISTORY_COLUMNS:
        if name not in existing:
            op.add_column("auction_history_records", sa.Column(name, type_, nullable=True))
    for table in TABLES:
        table.create(bind=bind, checkfirst=True)


def downgrade():
    bind = op.get_bind()
    for table in reversed(TABLES):
        table.drop(bind=bind, checkfirst=True)
    for name, _ in HISTORY_COLUMNS:
        op.drop_column("auction_history_records", name)
