"""add local product acceptance evidence

Revision ID: 20260710_830
Revises: 20260705_620
Create Date: 2026-07-10
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260710_830"
down_revision = "20260705_620"
branch_labels = None
depends_on = None


GLOBAL_STATUSES = "'PENDING','RUNNING','PASSED','PASSED_WITH_WARNINGS','BLOCKED_BY_ENVIRONMENT','FAILED'"
GATE_STATUSES = (
    "'PENDING','RUNNING','PASSED','PASSED_WITH_WARNINGS','BLOCKED_BY_ENVIRONMENT','FAILED',"
    "'CAPABILITY_MISSING','SKIPPED'"
)


def upgrade() -> None:
    op.create_table(
        "acceptance_executions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("execution_key", sa.String(length=255), nullable=False),
        sa.Column("correlation_id", sa.String(length=255), nullable=False),
        sa.Column("scenario", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="PENDING", nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("preserve_requested", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("reuse_requested", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("cleanup_requested", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "report", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column(
            "warnings",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "blockers",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_runtime_acceptance_executions"),
        sa.UniqueConstraint("execution_key", name="uq_runtime_acceptance_executions_key"),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["core.organizations.id"],
            name="fk_runtime_acceptance_executions_org",
        ),
        sa.CheckConstraint(f"status IN ({GLOBAL_STATUSES})", name="ck_runtime_acceptance_executions_status"),
        schema="runtime",
    )
    op.create_index(
        "ix_runtime_acceptance_executions_correlation",
        "acceptance_executions",
        ["correlation_id"],
        schema="runtime",
    )
    op.create_index("ix_runtime_acceptance_executions_status", "acceptance_executions", ["status"], schema="runtime")
    op.create_index(
        "ix_runtime_acceptance_executions_scenario",
        "acceptance_executions",
        ["scenario", "started_at"],
        schema="runtime",
    )

    op.create_table(
        "acceptance_gates",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("execution_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("gate_code", sa.String(length=128), nullable=False),
        sa.Column("phase_code", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "details", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_runtime_acceptance_gates"),
        sa.UniqueConstraint("execution_id", "phase_code", "gate_code", name="uq_runtime_acceptance_gates_identity"),
        sa.ForeignKeyConstraint(
            ["execution_id"],
            ["runtime.acceptance_executions.id"],
            name="fk_runtime_acceptance_gates_execution",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(f"status IN ({GATE_STATUSES})", name="ck_runtime_acceptance_gates_status"),
        schema="runtime",
    )
    op.create_index(
        "ix_runtime_acceptance_gates_execution",
        "acceptance_gates",
        ["execution_id", "phase_code"],
        schema="runtime",
    )
    op.create_index("ix_runtime_acceptance_gates_status", "acceptance_gates", ["status"], schema="runtime")

    op.create_table(
        "acceptance_resources",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("execution_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("resource_type", sa.String(length=128), nullable=False),
        sa.Column("resource_id", sa.String(length=255), nullable=True),
        sa.Column("external_ref", sa.String(length=255), nullable=False),
        sa.Column("created_by_execution", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("reused", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("cleanup_status", sa.String(length=64), server_default="not_requested", nullable=False),
        sa.Column(
            "details", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_runtime_acceptance_resources"),
        sa.UniqueConstraint(
            "execution_id", "resource_type", "external_ref", name="uq_runtime_acceptance_resources_ref"
        ),
        sa.ForeignKeyConstraint(
            ["execution_id"],
            ["runtime.acceptance_executions.id"],
            name="fk_runtime_acceptance_resources_execution",
            ondelete="CASCADE",
        ),
        schema="runtime",
    )
    op.create_index(
        "ix_runtime_acceptance_resources_execution",
        "acceptance_resources",
        ["execution_id", "resource_type"],
        schema="runtime",
    )
    op.create_index(
        "ix_runtime_acceptance_resources_resource_id",
        "acceptance_resources",
        ["resource_type", "resource_id"],
        schema="runtime",
    )
    op.create_index(
        "ix_runtime_acceptance_resources_cleanup",
        "acceptance_resources",
        ["cleanup_status"],
        schema="runtime",
    )


def downgrade() -> None:
    op.drop_index("ix_runtime_acceptance_resources_cleanup", table_name="acceptance_resources", schema="runtime")
    op.drop_index("ix_runtime_acceptance_resources_resource_id", table_name="acceptance_resources", schema="runtime")
    op.drop_index("ix_runtime_acceptance_resources_execution", table_name="acceptance_resources", schema="runtime")
    op.drop_table("acceptance_resources", schema="runtime")
    op.drop_index("ix_runtime_acceptance_gates_status", table_name="acceptance_gates", schema="runtime")
    op.drop_index("ix_runtime_acceptance_gates_execution", table_name="acceptance_gates", schema="runtime")
    op.drop_table("acceptance_gates", schema="runtime")
    op.drop_index("ix_runtime_acceptance_executions_scenario", table_name="acceptance_executions", schema="runtime")
    op.drop_index("ix_runtime_acceptance_executions_status", table_name="acceptance_executions", schema="runtime")
    op.drop_index("ix_runtime_acceptance_executions_correlation", table_name="acceptance_executions", schema="runtime")
    op.drop_table("acceptance_executions", schema="runtime")
