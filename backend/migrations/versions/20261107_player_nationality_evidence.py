"""Store provenance and history for player nationality evidence."""
from alembic import op
from app.models.models import PlayerNationalityEvidence

revision = "20261107nat1"
down_revision = "20261107auc4"
branch_labels = None
depends_on = None


def upgrade():
    PlayerNationalityEvidence.__table__.create(bind=op.get_bind(), checkfirst=True)


def downgrade():
    PlayerNationalityEvidence.__table__.drop(bind=op.get_bind(), checkfirst=True)
