"""security acceptance runtime

Revision ID: 20260711_870
Revises: 20260711_860
Create Date: 2026-07-11 00:00:00.000000
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260711_870"
down_revision = "20260711_860"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "security_acceptance_policies",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("scope", sa.String(length=32), nullable=False),
        sa.Column("policy_code", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), server_default="draft", nullable=False),
        sa.Column("authentication_required", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("authorization_required", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("debug_allowed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("cors_profile", sa.String(length=64), server_default="restricted", nullable=False),
        sa.Column("provider_execution_policy", sa.String(length=64), server_default="explicit", nullable=False),
        sa.Column("placeholder_detection_enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "required_secrets",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "required_configuration",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "audit_requirements",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "organization_isolation_requirements",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "configuration_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("created_by", sa.String(length=255), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("scope IN ('platform','organization')", name="ck_runtime_security_policy_scope"),
        sa.CheckConstraint(
            "status IN ('draft','active','inactive','retired')", name="ck_runtime_security_policy_status"
        ),
        sa.CheckConstraint(
            "(scope = 'platform' AND organization_id IS NULL) OR "
            "(scope = 'organization' AND organization_id IS NOT NULL)",
            name="ck_runtime_security_policy_scope_org",
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["core.organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "scope", "organization_id", "policy_code", name="uq_runtime_security_acceptance_policy_code"
        ),
        schema="runtime",
    )
    op.create_index(
        "ix_runtime_security_policy_scope",
        "security_acceptance_policies",
        ["scope", "organization_id", "status"],
        schema="runtime",
    )
    op.create_index(
        "uq_runtime_security_policy_platform_active",
        "security_acceptance_policies",
        ["scope"],
        unique=True,
        schema="runtime",
        postgresql_where=sa.text("organization_id IS NULL AND status = 'active'"),
    )
    op.create_index(
        "uq_runtime_security_policy_org_active",
        "security_acceptance_policies",
        ["scope", "organization_id"],
        unique=True,
        schema="runtime",
        postgresql_where=sa.text("organization_id IS NOT NULL AND status = 'active'"),
    )
    op.create_table(
        "security_acceptance_findings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("scope", sa.String(length=32), nullable=False),
        sa.Column("severity", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="open", nullable=False),
        sa.Column("rule", sa.String(length=128), nullable=False),
        sa.Column("category", sa.String(length=128), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column(
            "evidence", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("remediation", sa.Text(), nullable=True),
        sa.Column("source_runtime", sa.String(length=128), nullable=False),
        sa.Column("source_entity_type", sa.String(length=128), nullable=False),
        sa.Column("source_entity_id", sa.String(length=255), nullable=True),
        sa.Column("evidence_hash", sa.String(length=64), nullable=False),
        sa.Column("first_observed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_observed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("scope IN ('platform','organization')", name="ck_runtime_security_finding_scope"),
        sa.CheckConstraint(
            "severity IN ('info','warning','high','critical')", name="ck_runtime_security_finding_severity"
        ),
        sa.CheckConstraint(
            "status IN ('open','acknowledged','resolved','suppressed')",
            name="ck_runtime_security_finding_status",
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["core.organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "scope",
            "organization_id",
            "rule",
            "source_runtime",
            "source_entity_type",
            "source_entity_id",
            "evidence_hash",
            name="uq_runtime_security_finding_identity",
        ),
        schema="runtime",
    )
    op.create_index(
        "ix_runtime_security_finding_scope",
        "security_acceptance_findings",
        ["scope", "organization_id", "status"],
        schema="runtime",
    )
    op.create_index(
        "ix_runtime_security_finding_severity", "security_acceptance_findings", ["severity", "status"], schema="runtime"
    )
    op.create_index(
        "ix_runtime_security_finding_rule", "security_acceptance_findings", ["rule", "category"], schema="runtime"
    )
    op.create_table(
        "security_acceptance_evidence",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("scope", sa.String(length=32), nullable=False),
        sa.Column("evidence_type", sa.String(length=128), nullable=False),
        sa.Column("source_runtime", sa.String(length=128), nullable=False),
        sa.Column("source_entity_type", sa.String(length=128), nullable=False),
        sa.Column("source_entity_id", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column(
            "evidence_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("evidence_hash", sa.String(length=64), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("scope IN ('platform','organization')", name="ck_runtime_security_evidence_scope"),
        sa.CheckConstraint(
            "status IN ('passed','failed','blocked','not_evaluated')",
            name="ck_runtime_security_evidence_status",
        ),
        sa.CheckConstraint(
            "expires_at IS NULL OR expires_at > observed_at", name="ck_runtime_security_evidence_expiry"
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["core.organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "scope",
            "organization_id",
            "evidence_type",
            "source_runtime",
            "source_entity_type",
            "source_entity_id",
            "evidence_hash",
            name="uq_runtime_security_evidence_identity",
        ),
        schema="runtime",
    )
    op.create_index(
        "ix_runtime_security_evidence_scope",
        "security_acceptance_evidence",
        ["scope", "organization_id", "status"],
        schema="runtime",
    )
    op.create_index(
        "ix_runtime_security_evidence_type",
        "security_acceptance_evidence",
        ["evidence_type", "observed_at"],
        schema="runtime",
    )


def downgrade() -> None:
    op.drop_table("security_acceptance_evidence", schema="runtime")
    op.drop_table("security_acceptance_findings", schema="runtime")
    op.drop_table("security_acceptance_policies", schema="runtime")
