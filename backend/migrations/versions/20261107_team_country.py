"""Add provenance-aware team country for home/away classification."""
from alembic import op
import sqlalchemy as sa

revision = "20261107teamcountry"
down_revision = "20261107nat1"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("teams", sa.Column("country", sa.String(length=128), nullable=True))
    op.add_column("teams", sa.Column("country_source", sa.String(length=128), nullable=True))
    op.add_column("teams", sa.Column("country_confidence", sa.String(length=16), nullable=True))


def downgrade():
    op.drop_column("teams", "country_confidence")
    op.drop_column("teams", "country_source")
    op.drop_column("teams", "country")
