from alembic import op
import sqlalchemy as sa

revision = "20260623_261a1"
down_revision = "20260623_261a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "uq_runtime_configurations_named_platform_scope",
        "configurations",
        ["scope_type", "scope_key", "configuration_type", "configuration_key"],
        unique=True,
        schema="runtime",
        postgresql_where=sa.text(
            "scope_type IN ('worker','workload_class') AND organization_id IS NULL"
        ),
    )
    op.create_index(
        "uq_runtime_configurations_named_organization_scope",
        "configurations",
        ["organization_id", "scope_type", "scope_key", "configuration_type", "configuration_key"],
        unique=True,
        schema="runtime",
        postgresql_where=sa.text(
            "scope_type IN ('worker','workload_class') AND organization_id IS NOT NULL"
        ),
    )


def downgrade() -> None:
    pass
