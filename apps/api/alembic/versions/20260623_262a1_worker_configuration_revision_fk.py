from alembic import op


revision = "20260623_262a1"
down_revision = "20260623_262a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_foreign_key(
        "fk_runtime_workers_active_configuration_revision",
        "workers",
        "configuration_revisions",
        ["active_configuration_revision_id"],
        ["id"],
        source_schema="runtime",
        referent_schema="runtime",
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_runtime_workers_active_configuration_revision",
        "workers",
        schema="runtime",
        type_="foreignkey",
    )
