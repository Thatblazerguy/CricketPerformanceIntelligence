"""Run the AI auction room on the existing auction session tables.

Adds ``context_key`` and ``state`` to ``auction_sessions`` and drops the
short-lived ``auction_sim_runs`` table introduced by 20261117auc3 (it only ever
held test simulations; rooms now persist as AuctionSession rows with ordinary
AuctionEvent / AuctionBid / AuctionPurchase records).

Revision ID: 20261118auc4
Revises: 20261117auc3
"""
from alembic import op
import sqlalchemy as sa

revision = "20261118auc4"
down_revision = "20261117auc3"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("auction_sessions")}
    if "context_key" not in cols:
        op.add_column("auction_sessions", sa.Column("context_key", sa.String(64), nullable=True))
    if "state" not in cols:
        op.add_column("auction_sessions", sa.Column("state", sa.JSON(), nullable=True))
    op.execute("DROP TABLE IF EXISTS auction_sim_runs")


def downgrade():
    op.drop_column("auction_sessions", "state")
    op.drop_column("auction_sessions", "context_key")
