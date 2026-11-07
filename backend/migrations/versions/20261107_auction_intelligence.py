"""Add scenario-scoped auction data and append-only session events.

Auction entities reference CPI's canonical players and remain separate from
the match-performance schema.
"""
from alembic import op
from app.models.models import (
    AuctionScenario, AuctionRule, AuctionTeam, AuctionPlayer, AuctionRetention,
    AuctionImport, AuctionSession, AuctionEvent, AuctionBid, AuctionPurchase,
)

revision = "20261107auc"
down_revision = "8721c1a3"
branch_labels = None
depends_on = None

TABLES = [
    AuctionScenario.__table__, AuctionRule.__table__, AuctionTeam.__table__,
    AuctionPlayer.__table__, AuctionRetention.__table__, AuctionImport.__table__,
    AuctionSession.__table__, AuctionEvent.__table__, AuctionBid.__table__,
    AuctionPurchase.__table__,
]


def upgrade():
    bind = op.get_bind()
    for table in TABLES:
        table.create(bind=bind, checkfirst=True)


def downgrade():
    bind = op.get_bind()
    for table in reversed(TABLES):
        table.drop(bind=bind, checkfirst=True)
