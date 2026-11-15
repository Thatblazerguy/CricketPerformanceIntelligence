"""Scouting per-innings pre-aggregation tables.

Creates ``scouting_bat_innings``, ``scouting_bat_vs_style`` and
``scouting_bowl_innings`` (see ``app.analytics.scouting_aggregates``). Populate
them with ``scripts/build_scouting_aggregates.py``; afterwards they are kept in
step with imports by ``app.ingestion.dependent_refresh``.

Revision ID: 20261115scout1
Revises: 20261114nsidx1
"""
from alembic import op

from app.analytics.scouting_aggregates import DDL, TABLES

revision = "20261115scout1"
down_revision = "20261114nsidx1"
branch_labels = None
depends_on = None


def upgrade():
    for statement in DDL:
        op.execute(statement)


def downgrade():
    for table in TABLES:
        op.execute(f"DROP TABLE IF EXISTS {table}")
