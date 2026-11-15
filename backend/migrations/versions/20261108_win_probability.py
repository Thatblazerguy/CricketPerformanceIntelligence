"""Store precomputed match win probability curves and player WPA."""
from alembic import op
from app.models.models import MatchWinProbability, PlayerWinProbabilityImpact

revision = "20261108wp1"
down_revision = "20261107teamcountry"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    MatchWinProbability.__table__.create(bind=bind, checkfirst=True)
    PlayerWinProbabilityImpact.__table__.create(bind=bind, checkfirst=True)


def downgrade():
    bind = op.get_bind()
    PlayerWinProbabilityImpact.__table__.drop(bind=bind, checkfirst=True)
    MatchWinProbability.__table__.drop(bind=bind, checkfirst=True)
