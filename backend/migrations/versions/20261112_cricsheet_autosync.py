"""Cricsheet automatic synchronisation metadata.

Creates sync_sources, sync_history, sync_match_revisions, sync_settings and
sync_worker_state. Purely additive: no existing CPI table is touched.

Revision ID: 20261112autosync1
Revises: 20261108wp1
"""
import sqlalchemy as sa
from alembic import op

revision = "20261112autosync1"
down_revision = "20261108wp1"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "sync_sources",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("source_key", sa.String(80), nullable=False, unique=True),
        sa.Column("label", sa.String(128)),
        sa.Column("archive_url", sa.String(512), nullable=False),
        sa.Column("latest_checksum", sa.String(64)),
        sa.Column("etag", sa.String(256)),
        sa.Column("last_modified", sa.String(256)),
        sa.Column("archive_size_bytes", sa.BigInteger),
        sa.Column("last_checked_at", sa.DateTime),
        sa.Column("last_imported_at", sa.DateTime),
        sa.Column("last_error", sa.Text),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "sync_history",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("source_key", sa.String(80), nullable=False),
        sa.Column("triggered_by", sa.String(32), nullable=False, server_default="scheduler"),
        sa.Column("started_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime),
        sa.Column("status", sa.String(32), nullable=False, server_default="running"),
        sa.Column("phase", sa.String(32), nullable=False, server_default="checking_source"),
        sa.Column("progress_current", sa.Integer, nullable=False, server_default="0"),
        sa.Column("progress_total", sa.Integer, nullable=False, server_default="0"),
        sa.Column("archive_changed", sa.Boolean),
        sa.Column("archive_checksum", sa.String(64)),
        sa.Column("matches_discovered", sa.Integer, nullable=False, server_default="0"),
        sa.Column("new_matches", sa.Integer, nullable=False, server_default="0"),
        sa.Column("updated_matches", sa.Integer, nullable=False, server_default="0"),
        sa.Column("unchanged_matches", sa.Integer, nullable=False, server_default="0"),
        sa.Column("failed_records", sa.Integer, nullable=False, server_default="0"),
        sa.Column("error_detail", sa.Text),
        sa.Column("failed_files", sa.JSON),
        sa.Column("stats_refresh", sa.JSON),
        sa.Column("duration_seconds", sa.Float),
    )
    op.create_index("ix_sync_history_started", "sync_history", ["started_at"])
    op.create_index("ix_sync_history_run", "sync_history", ["run_id"])
    op.create_index("ix_sync_history_status", "sync_history", ["status"])

    op.create_table(
        "sync_match_revisions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("match_id", sa.String(36), sa.ForeignKey("matches.id", ondelete="SET NULL")),
        sa.Column("source_match_id", sa.String(256), nullable=False),
        sa.Column("source_key", sa.String(80), nullable=False),
        sa.Column("sync_history_id", sa.Integer, sa.ForeignKey("sync_history.id", ondelete="SET NULL")),
        sa.Column("previous_checksum", sa.String(64)),
        sa.Column("new_checksum", sa.String(64), nullable=False),
        sa.Column("revised_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_sync_revision_source_match", "sync_match_revisions", ["source_match_id"])
    op.create_index("ix_sync_revision_revised_at", "sync_match_revisions", ["revised_at"])

    op.create_table(
        "sync_settings",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("auto_sync_enabled", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("interval_hours", sa.Float, nullable=False, server_default="6"),
        sa.Column("check_on_start", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("manual_requested_at", sa.DateTime),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "sync_worker_state",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("state", sa.String(32), nullable=False, server_default="stopped"),
        sa.Column("pid", sa.Integer),
        sa.Column("hostname", sa.String(256)),
        sa.Column("started_at", sa.DateTime),
        sa.Column("heartbeat_at", sa.DateTime),
        sa.Column("last_run_started_at", sa.DateTime),
        sa.Column("last_success_at", sa.DateTime),
        sa.Column("next_check_at", sa.DateTime),
        sa.Column("last_error", sa.Text),
    )


def downgrade():
    op.drop_table("sync_worker_state")
    op.drop_table("sync_settings")
    op.drop_index("ix_sync_revision_revised_at", table_name="sync_match_revisions")
    op.drop_index("ix_sync_revision_source_match", table_name="sync_match_revisions")
    op.drop_table("sync_match_revisions")
    op.drop_index("ix_sync_history_status", table_name="sync_history")
    op.drop_index("ix_sync_history_run", table_name="sync_history")
    op.drop_index("ix_sync_history_started", table_name="sync_history")
    op.drop_table("sync_history")
    op.drop_table("sync_sources")
