"""Allow retention imports to preserve unknown prices as NULL."""
from alembic import op
import sqlalchemy as sa

revision = "20261107auc3"
down_revision = "20261107auc2"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column("auction_retentions", "retention_price",
                    existing_type=sa.Numeric(14, 2), nullable=True)


def downgrade():
    op.execute("UPDATE auction_retentions SET retention_price = 0 WHERE retention_price IS NULL")
    op.alter_column("auction_retentions", "retention_price",
                    existing_type=sa.Numeric(14, 2), nullable=False)
