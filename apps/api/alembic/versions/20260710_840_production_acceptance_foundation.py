"""add production acceptance foundation

Revision ID: 20260710_840
Revises: 20260710_830
Create Date: 2026-07-10
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260710_840"
down_revision = "20260710_830"
branch_labels = None
depends_on = None

RUN_STATUSES = "'pending','running','passed','failed','blocked'"
GATE_STATUSES = "'passed','failed','blocked','not_evaluated'"
DOMAINS = "'functional','operational','security','recovery','deployment','capacity','portal'"


def upgrade() -> None:
    op.create_table(
        "production_acceptance_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("scope", sa.String(length=32), nullable=False),
        sa.Column("requested_by", sa.String(length=255), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=32), server_default="pending", nullable=False),
        sa.Column("production_ready", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("contract_version", sa.String(length=32), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("result_hash", sa.String(length=64), nullable=True),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_runtime_production_acceptance_runs"),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["core.organizations.id"], name="fk_runtime_prod_acceptance_runs_org"
        ),
        sa.UniqueConstraint(
            "scope",
            "organization_id",
            "contract_version",
            "input_hash",
            "idempotency_key",
            name="uq_runtime_production_acceptance_idempotency",
        ),
        sa.CheckConstraint(f"status IN ({RUN_STATUSES})", name="ck_runtime_production_acceptance_runs_status"),
        sa.CheckConstraint("scope IN ('platform','organization')", name="ck_runtime_production_acceptance_runs_scope"),
        sa.CheckConstraint(
            "(scope = 'platform' AND organization_id IS NULL) OR "
            "(scope = 'organization' AND organization_id IS NOT NULL)",
            name="ck_runtime_production_acceptance_runs_scope_org",
        ),
        sa.CheckConstraint("length(input_hash) = 64", name="ck_runtime_production_acceptance_runs_input_hash"),
        sa.CheckConstraint(
            "result_hash IS NULL OR length(result_hash) = 64",
            name="ck_runtime_production_acceptance_runs_result_hash",
        ),
        schema="runtime",
    )
    op.create_index(
        "ix_runtime_production_acceptance_runs_scope",
        "production_acceptance_runs",
        ["scope", "organization_id", "requested_at"],
        schema="runtime",
    )
    op.create_index(
        "ix_runtime_production_acceptance_runs_status",
        "production_acceptance_runs",
        ["status", "requested_at"],
        schema="runtime",
    )
    op.create_index(
        "uq_runtime_production_acceptance_platform_idempotency",
        "production_acceptance_runs",
        ["scope", "contract_version", "input_hash", "idempotency_key"],
        unique=True,
        schema="runtime",
        postgresql_where=sa.text("organization_id IS NULL"),
    )
    op.create_index(
        "uq_runtime_production_acceptance_org_idempotency",
        "production_acceptance_runs",
        ["scope", "organization_id", "contract_version", "input_hash", "idempotency_key"],
        unique=True,
        schema="runtime",
        postgresql_where=sa.text("organization_id IS NOT NULL"),
    )

    op.create_table(
        "production_acceptance_gate_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("gate_code", sa.String(length=128), nullable=False),
        sa.Column("domain", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("mandatory", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("blocker_code", sa.String(length=128), nullable=True),
        sa.Column("warning_code", sa.String(length=128), nullable=True),
        sa.Column("evidence_type", sa.String(length=128), nullable=True),
        sa.Column("evidence_reference", sa.String(length=255), nullable=True),
        sa.Column(
            "evidence_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_runtime_production_acceptance_gate_results"),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["runtime.production_acceptance_runs.id"],
            name="fk_runtime_prod_acceptance_gate_run",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("run_id", "gate_code", name="uq_runtime_production_acceptance_gate"),
        sa.CheckConstraint(f"domain IN ({DOMAINS})", name="ck_runtime_production_acceptance_gate_domain"),
        sa.CheckConstraint(f"status IN ({GATE_STATUSES})", name="ck_runtime_production_acceptance_gate_status"),
        schema="runtime",
    )
    op.create_index(
        "ix_runtime_production_acceptance_gate_run",
        "production_acceptance_gate_results",
        ["run_id", "domain"],
        schema="runtime",
    )
    op.create_index(
        "ix_runtime_production_acceptance_gate_status",
        "production_acceptance_gate_results",
        ["status", "mandatory"],
        schema="runtime",
    )

    op.create_table(
        "production_acceptance_evidence",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("gate_result_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("evidence_type", sa.String(length=128), nullable=False),
        sa.Column("source_runtime", sa.String(length=128), nullable=False),
        sa.Column("source_entity_type", sa.String(length=128), nullable=False),
        sa.Column("source_entity_id", sa.String(length=255), nullable=True),
        sa.Column(
            "evidence_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("evidence_hash", sa.String(length=64), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_runtime_production_acceptance_evidence"),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["runtime.production_acceptance_runs.id"],
            name="fk_runtime_prod_acceptance_evidence_run",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["gate_result_id"],
            ["runtime.production_acceptance_gate_results.id"],
            name="fk_runtime_prod_acceptance_evidence_gate",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint("run_id", "evidence_hash", name="uq_runtime_production_acceptance_evidence_hash"),
        schema="runtime",
    )
    op.create_index(
        "ix_runtime_production_acceptance_evidence_run",
        "production_acceptance_evidence",
        ["run_id", "evidence_type"],
        schema="runtime",
    )
    op.create_index(
        "ix_runtime_production_acceptance_evidence_gate",
        "production_acceptance_evidence",
        ["gate_result_id"],
        schema="runtime",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_runtime_production_acceptance_evidence_gate",
        table_name="production_acceptance_evidence",
        schema="runtime",
    )
    op.drop_index(
        "ix_runtime_production_acceptance_evidence_run",
        table_name="production_acceptance_evidence",
        schema="runtime",
    )
    op.drop_table("production_acceptance_evidence", schema="runtime")
    op.drop_index(
        "ix_runtime_production_acceptance_gate_status",
        table_name="production_acceptance_gate_results",
        schema="runtime",
    )
    op.drop_index(
        "ix_runtime_production_acceptance_gate_run",
        table_name="production_acceptance_gate_results",
        schema="runtime",
    )
    op.drop_table("production_acceptance_gate_results", schema="runtime")
    op.drop_index(
        "ix_runtime_production_acceptance_runs_status",
        table_name="production_acceptance_runs",
        schema="runtime",
    )
    op.drop_index(
        "uq_runtime_production_acceptance_org_idempotency",
        table_name="production_acceptance_runs",
        schema="runtime",
    )
    op.drop_index(
        "uq_runtime_production_acceptance_platform_idempotency",
        table_name="production_acceptance_runs",
        schema="runtime",
    )
    op.drop_index(
        "ix_runtime_production_acceptance_runs_scope",
        table_name="production_acceptance_runs",
        schema="runtime",
    )
    op.drop_table("production_acceptance_runs", schema="runtime")
