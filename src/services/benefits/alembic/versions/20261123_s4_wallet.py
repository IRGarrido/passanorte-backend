"""Add wallet identities used to serialize ledger postings."""

from alembic import op

from services.benefits.app.models.ledger import Wallet

revision = "20261123_benefits_s4"
down_revision = "20261123_benefits_s3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    Wallet.__table__.create(op.get_bind())
    op.execute("INSERT INTO benefits.wallets SELECT DISTINCT tourist_id FROM benefits.ledger")


def downgrade() -> None:
    Wallet.__table__.drop(op.get_bind())
