"""Introduce route themes and virtual rewards while retaining legacy references."""

import sqlalchemy as sa
from alembic import op

revision = "20261123_catalog_s4"
down_revision = "20261123_catalog_s3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("tourist_spots", "tolerance_radius_m", nullable=True, schema="catalog")
    op.alter_column("routes", "prize_id", nullable=True, schema="catalog")
    op.add_column("routes", sa.Column("category_ids", sa.JSON(), nullable=False, server_default="[]"), schema="catalog")
    op.add_column("routes", sa.Column("reward_amount", sa.Integer(), nullable=False, server_default="0"), schema="catalog")
    op.add_column("routes", sa.Column("is_removed", sa.Boolean(), nullable=False, server_default="false"), schema="catalog")
    op.execute("""
        DELETE FROM catalog.route_points WHERE id IN (
            SELECT id FROM (
                SELECT id, row_number() OVER (
                    PARTITION BY route_id, tourist_spot_id ORDER BY is_active DESC, position, id
                ) AS duplicate FROM catalog.route_points
            ) ranked WHERE duplicate > 1
        )
    """)
    op.execute("""
        UPDATE catalog.route_points p SET is_active = false
        WHERE NOT EXISTS (
            SELECT FROM catalog.tourist_spots s WHERE s.id = p.tourist_spot_id
            AND NOT s.is_removed AND s.status != 'permanently_closed'
        )
    """)
    op.execute("""
        UPDATE catalog.routes r SET category_ids = COALESCE((
            SELECT json_agg(DISTINCT c.id ORDER BY c.id) FROM catalog.route_points p
            JOIN catalog.spot_categories sc ON sc.spot_id = p.tourist_spot_id
            JOIN catalog.categories c ON c.id = sc.category_id
            WHERE p.route_id = r.id AND p.is_active AND c.is_active
        ), '[]'::json)
    """)
    op.execute("""
        UPDATE catalog.routes r SET is_active = false WHERE json_array_length(category_ids) = 0
        OR (SELECT count(*) FROM catalog.route_points p WHERE p.route_id = r.id AND p.is_active) < 2
    """)
    op.create_unique_constraint("uq_route_spot", "route_points", ["route_id", "tourist_spot_id"], schema="catalog")
    op.create_check_constraint("ck_route_reward_amount", "routes", "reward_amount >= 0", schema="catalog")


def downgrade() -> None:
    raise RuntimeError("Restore a pre-S4 schema backup according to the GPS retention policy.")
