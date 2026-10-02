"""complete production readiness evidence and correlation contracts

Revision ID: 20260713_910
Revises: 20260713_900
Create Date: 2026-07-13 00:30:00.000000
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260713_910"
down_revision = "20260713_900"
branch_labels = None
depends_on = None


CORRELATED_EXECUTIONS = (
    "production_acceptance_runs",
    "operational_executions",
    "backup_executions",
    "restore_executions",
)


def upgrade() -> None:
    for table in CORRELATED_EXECUTIONS:
        op.add_column(table, sa.Column("correlation_id", sa.String(128)), schema="runtime")
        op.execute(f"UPDATE runtime.{table} SET correlation_id = '{table}:' || id::text WHERE correlation_id IS NULL")
        op.alter_column(table, "correlation_id", nullable=False, schema="runtime")
        op.create_index(f"ix_runtime_{table}_correlation", table, ["correlation_id"], schema="runtime")

    op.add_column(
        "production_acceptance_gate_results",
        sa.Column("duration_ms", sa.Integer(), server_default="0", nullable=False),
        schema="runtime",
    )
    op.add_column(
        "production_acceptance_gate_results",
        sa.Column(
            "components_evaluated",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        schema="runtime",
    )
    op.add_column(
        "production_acceptance_gate_results",
        sa.Column("evidence_origin", sa.String(64), server_default="runtime", nullable=False),
        schema="runtime",
    )
    op.create_check_constraint(
        "ck_runtime_production_acceptance_gate_duration",
        "production_acceptance_gate_results",
        "duration_ms >= 0",
        schema="runtime",
    )

    for column in (
        "document_registration_verified",
        "assistant_runtime_verified",
        "audit_runtime_verified",
    ):
        op.add_column(
            "restore_verifications",
            sa.Column(column, sa.Boolean(), server_default=sa.text("false"), nullable=False),
            schema="runtime",
        )


def downgrade() -> None:
    for column in (
        "audit_runtime_verified",
        "assistant_runtime_verified",
        "document_registration_verified",
    ):
        op.drop_column("restore_verifications", column, schema="runtime")

    op.drop_constraint(
        "ck_runtime_production_acceptance_gate_duration",
        "production_acceptance_gate_results",
        schema="runtime",
        type_="check",
    )
    op.drop_column("production_acceptance_gate_results", "evidence_origin", schema="runtime")
    op.drop_column("production_acceptance_gate_results", "components_evaluated", schema="runtime")
    op.drop_column("production_acceptance_gate_results", "duration_ms", schema="runtime")

    for table in reversed(CORRELATED_EXECUTIONS):
        op.drop_index(f"ix_runtime_{table}_correlation", table_name=table, schema="runtime")
        op.drop_column(table, "correlation_id", schema="runtime")
