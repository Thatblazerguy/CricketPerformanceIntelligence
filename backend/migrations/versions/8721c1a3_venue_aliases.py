"""Add Cricsheet venue alias registry."""
from alembic import op
import sqlalchemy as sa

revision = "8721c1a3"
down_revision = "52035044457b"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "player_name_aliases",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("player_id", sa.String(36), sa.ForeignKey("players.id"), nullable=False),
        sa.Column("alias", sa.String(256), nullable=False),
        sa.Column("source", sa.String(128), nullable=False),
        sa.UniqueConstraint("player_id", "alias", name="uq_player_name_alias"),
    )
    op.create_index("ix_match_tournament_date", "matches", ["tournament_id", "start_date"])
    op.create_index("ix_match_venue_date", "matches", ["venue_id", "start_date"])
    op.create_index("ix_match_team1_date", "matches", ["team1_id", "start_date"])
    op.create_index("ix_match_team2_date", "matches", ["team2_id", "start_date"])
    op.create_table(
        "venue_aliases",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("venue_id", sa.String(36), sa.ForeignKey("venues.id"), nullable=False),
        sa.Column("source_venue_id", sa.String(64), nullable=False),
        sa.Column("source_name", sa.String(512), nullable=False),
        sa.UniqueConstraint("source_venue_id", "source_name", name="uq_venue_alias_source_name"),
    )


def downgrade():
    op.drop_index("ix_match_team2_date", table_name="matches")
    op.drop_index("ix_match_team1_date", table_name="matches")
    op.drop_index("ix_match_venue_date", table_name="matches")
    op.drop_index("ix_match_tournament_date", table_name="matches")
    op.drop_table("venue_aliases")
    op.drop_table("player_name_aliases")
