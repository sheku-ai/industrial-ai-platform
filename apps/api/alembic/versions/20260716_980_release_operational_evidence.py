"""add release operational evidence ledger

Revision ID: 20260716_980
Revises: 20260716_970
Create Date: 2026-07-16 00:30:00.000000
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260716_980"
down_revision = "20260716_970"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "release_operational_evidence",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("backup_execution_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("scope", sa.String(length=32), nullable=False),
        sa.Column("evidence_type", sa.String(length=64), nullable=False),
        sa.Column("release_version", sa.String(length=64), nullable=False),
        sa.Column("alembic_revision", sa.String(length=128), nullable=False),
        sa.Column("edition", sa.String(length=32), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("execution_key", sa.String(length=255), nullable=False),
        sa.Column("correlation_id", sa.String(length=128), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("evidence_payload", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("evidence_hash", sa.String(length=64), nullable=False),
        sa.Column("source_evidence_ids", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("scope IN ('platform','organization')", name="ck_runtime_release_operational_scope"),
        sa.CheckConstraint(
            "(scope = 'platform' AND organization_id IS NULL) OR "
            "(scope = 'organization' AND organization_id IS NOT NULL)",
            name="ck_runtime_release_operational_scope_org",
        ),
        sa.CheckConstraint(
            "evidence_type IN ('configuration_preflight','upgrade_readiness','rollback_eligibility',"
            "'rc_operational_refresh')",
            name="ck_runtime_release_operational_type",
        ),
        sa.CheckConstraint(
            "status IN ('passed','failed','blocked','expired','not_evaluated','requires_restore',"
            "'eligible_application_only','incompatible')",
            name="ck_runtime_release_operational_status",
        ),
        sa.CheckConstraint(
            "edition IS NULL OR edition IN ('community','enterprise')",
            name="ck_runtime_release_operational_edition",
        ),
        sa.CheckConstraint("length(input_hash) = 64", name="ck_runtime_release_operational_input_hash"),
        sa.CheckConstraint("length(evidence_hash) = 64", name="ck_runtime_release_operational_evidence_hash"),
        sa.ForeignKeyConstraint(
            ["backup_execution_id"], ["runtime.backup_executions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["core.organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "scope",
            "organization_id",
            "evidence_type",
            "execution_key",
            name="uq_runtime_release_operational_evidence_execution",
            postgresql_nulls_not_distinct=True,
        ),
        schema="runtime",
    )
    op.create_index(
        "ix_runtime_release_operational_latest",
        "release_operational_evidence",
        ["scope", "organization_id", "evidence_type", "evaluated_at"],
        schema="runtime",
    )
    op.create_index(
        "ix_runtime_release_operational_correlation",
        "release_operational_evidence",
        ["correlation_id"],
        schema="runtime",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_runtime_release_operational_correlation",
        table_name="release_operational_evidence",
        schema="runtime",
    )
    op.drop_index(
        "ix_runtime_release_operational_latest",
        table_name="release_operational_evidence",
        schema="runtime",
    )
    op.drop_table("release_operational_evidence", schema="runtime")
