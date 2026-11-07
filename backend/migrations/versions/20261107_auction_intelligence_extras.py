"""Persist external player profile cache and generated auction XIs."""
from alembic import op
from app.models.models import PlayerExternalProfile, AuctionPredictedXI

revision = "20261107auc4"
down_revision = "20261107auc3"
branch_labels = None
depends_on = None

def upgrade():
    bind = op.get_bind()
    PlayerExternalProfile.__table__.create(bind=bind, checkfirst=True)
    AuctionPredictedXI.__table__.create(bind=bind, checkfirst=True)

def downgrade():
    bind = op.get_bind()
    AuctionPredictedXI.__table__.drop(bind=bind, checkfirst=True)
    PlayerExternalProfile.__table__.drop(bind=bind, checkfirst=True)
