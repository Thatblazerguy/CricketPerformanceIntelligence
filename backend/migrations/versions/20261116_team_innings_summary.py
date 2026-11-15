"""Team innings summary pre-aggregation table.

Creates ``team_innings_summary`` (see ``app.analytics.team_innings_aggregates``).
Populate it with ``scripts/build_team_innings_summary.py``; afterwards it is kept
in step with imports by ``app.ingestion.dependent_refresh``.

Revision ID: 20261116teaminn1
Revises: 20261115scout1
"""
from alembic import op

from app.analytics.team_innings_aggregates import DDL, TABLE

revision = "20261116teaminn1"
down_revision = "20261115scout1"
branch_labels = None
depends_on = None


def upgrade():
    for statement in DDL:
        op.execute(statement)


def downgrade():
    op.execute(f"DROP TABLE IF EXISTS {TABLE}")
