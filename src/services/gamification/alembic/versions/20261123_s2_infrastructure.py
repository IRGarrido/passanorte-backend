"""Install durable messaging tables for gamification."""
import sqlalchemy as sa
from alembic import op

from shared.delivery import inbox_table, outbox_table

revision = "20261123_gamification_s2"
down_revision = 'f3a4b1c2d5e6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT FROM gamification.routes) THEN
            RAISE EXCEPTION 'Import legacy routes through scripts/migrate_legacy.py into a clean S2 database';
        END IF;
    END $$""")
    op.drop_constraint("route_enrollments_route_id_fkey", "route_enrollments", type_="foreignkey")
    op.drop_table("route_points")
    op.drop_table("routes")
    # Keep the S2 schema independent of the runtime Visit model. The S4
    # revision removes raw GPS only after the historical import can run.
    op.create_table(
        "visits",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("tourist_spot_id", sa.String(36), nullable=False),
        sa.Column("user_latitude", sa.Numeric(10, 7), nullable=False),
        sa.Column("user_longitude", sa.Numeric(10, 7), nullable=False),
        sa.Column("distance_m", sa.Numeric(10, 2), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        sa.Column("notes", sa.Text()),
        schema="gamification",
    )
    op.create_index("ix_gamification_visits_user_id", "visits", ["user_id"], schema="gamification")
    op.create_index("ix_gamification_visits_tourist_spot_id", "visits", ["tourist_spot_id"], schema="gamification")
    op.create_index(
        "uq_visit_validated", "visits", ["user_id", "tourist_spot_id"], unique=True,
        schema="gamification", postgresql_where=sa.text("status = 'validated'"),
    )
    outbox_table("gamification").create(op.get_bind())
    inbox_table("gamification").create(op.get_bind())


def downgrade() -> None:
    raise RuntimeError("Restore the pre-S2 backup to roll back the domain split.")
