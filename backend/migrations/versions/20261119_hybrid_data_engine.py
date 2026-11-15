"""Hybrid data engine: canonical match identity, scorecard layer, coverage, inventory.

Purely additive: no existing table or column is altered, so every current
analytics query is unaffected. Downgrade drops only the new tables.

Revision ID: 20261119hyb1
Revises: 20261118auc4
"""
from alembic import op
import sqlalchemy as sa

revision = "20261119hyb1"
down_revision = "20261118auc4"
branch_labels = None
depends_on = None

NEW_TABLES = [
    "match_appearances", "hybrid_ingestion_events", "reconciliation_flags", "source_inventory",
    "scorecard_bowling", "scorecard_batting", "scorecard_innings",
    "player_external_ids", "match_source_refs", "canonical_matches",
]


def upgrade():
    from app.models.models import Base
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())
    tables = [Base.metadata.tables[name] for name in reversed(NEW_TABLES) if name not in existing]
    # Create from the ORM definitions so model and migration cannot drift.
    Base.metadata.create_all(bind, tables=tables)


def downgrade():
    for name in NEW_TABLES:
        op.execute(f"DROP TABLE IF EXISTS {name} CASCADE")
