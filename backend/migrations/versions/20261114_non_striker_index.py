"""Index deliveries.non_striker_id for innings-level player analytics.

The player innings log needs every innings a batter appeared in, including
innings where they were only ever the non-striker. Without this index that
lookup is a sequential scan of the deliveries table.

Revision ID: 20261114nsidx1
Revises: 20261112autosync1
"""
from alembic import op

revision = "20261114nsidx1"
down_revision = "20261112autosync1"
branch_labels = None
depends_on = None


def upgrade():
    with op.get_context().autocommit_block():
        op.execute("CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_delivery_non_striker_id ON deliveries (non_striker_id)")


def downgrade():
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_delivery_non_striker_id")
