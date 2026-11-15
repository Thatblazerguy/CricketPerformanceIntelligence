"""Persist historical auction outcomes and model training runs."""
from alembic import op
from app.models.models import AuctionHistoryImport, AuctionHistoryRecord, AuctionModelRun

revision = "20261107auc2"
down_revision = "20261107auc"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    AuctionHistoryRecord.__table__.create(bind=bind, checkfirst=True)
    AuctionModelRun.__table__.create(bind=bind, checkfirst=True)
    AuctionHistoryImport.__table__.create(bind=bind, checkfirst=True)


def downgrade():
    bind = op.get_bind()
    AuctionHistoryImport.__table__.drop(bind=bind, checkfirst=True)
    AuctionModelRun.__table__.drop(bind=bind, checkfirst=True)
    AuctionHistoryRecord.__table__.drop(bind=bind, checkfirst=True)
