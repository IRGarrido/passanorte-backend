"""Remove raw GPS and preserve prior route completions without retroactive credit."""

import sqlalchemy as sa
from alembic import op

from services.gamification.app.models.enrollment import CreditIntent, RouteCompletion

revision = "20261123_gamification_s4"
down_revision = "20261123_gamification_s2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    RouteCompletion.__table__.create(op.get_bind())
    CreditIntent.__table__.create(op.get_bind())
    op.execute("""
        INSERT INTO gamification.route_completions (id, user_id, route_id, reward_amount, completed_at)
        SELECT id, user_id, route_id, 0, COALESCE(completed_at, started_at) AT TIME ZONE 'UTC'
        FROM gamification.route_enrollments WHERE status = 'completed'
        ON CONFLICT (user_id, route_id) DO NOTHING
    """)
    op.execute("""
        INSERT INTO gamification.route_completions (id, user_id, route_id, reward_amount, completed_at)
        SELECT md5('legacy-badge:' || id), user_id, route_id, 0, awarded_at AT TIME ZONE 'UTC'
        FROM gamification.badges ON CONFLICT (user_id, route_id) DO NOTHING
    """)
    op.add_column("visits", sa.Column("accuracy_m", sa.Numeric(10, 2)), schema="gamification")
    op.drop_column("visits", "user_latitude", schema="gamification")
    op.drop_column("visits", "user_longitude", schema="gamification")


def downgrade() -> None:
    raise RuntimeError("Raw tourist coordinates removed for S4 cannot be recovered by downgrade.")
