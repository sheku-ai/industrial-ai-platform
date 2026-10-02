"""add persistent portal acceptance evidence

Revision ID: 20260714_940
Revises: 20260714_930
Create Date: 2026-07-14 02:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260714_940"
down_revision = "20260714_930"
branch_labels = None
depends_on = None

SCHEMA = "runtime"
JSON = postgresql.JSONB(astext_type=sa.Text())
UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "portal_acceptance_evidence",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("scope", sa.String(32), nullable=False),
        sa.Column("organization_id", UUID, sa.ForeignKey("core.organizations.id"), nullable=True),
        sa.Column("validation_run_code", sa.String(128), nullable=False),
        sa.Column("validation_type", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("source", sa.String(128), nullable=False),
        sa.Column("source_reference", sa.String(512), nullable=True),
        sa.Column("evidence_payload", JSON, nullable=False),
        sa.Column("evidence_hash", sa.String(64), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("scope IN ('platform','organization')", name="ck_runtime_portal_evidence_scope"),
        sa.CheckConstraint(
            "(scope = 'platform' AND organization_id IS NULL) OR "
            "(scope = 'organization' AND organization_id IS NOT NULL)",
            name="ck_runtime_portal_evidence_scope_org",
        ),
        sa.CheckConstraint(
            "validation_type IN ('principal_routes','portal_build','portal_contract','negative_states',"
            "'permission_states','cross_organization_states')",
            name="ck_runtime_portal_evidence_type",
        ),
        sa.CheckConstraint(
            "status IN ('passed','failed','blocked','not_evaluated')",
            name="ck_runtime_portal_evidence_status",
        ),
        sa.CheckConstraint("length(evidence_hash) = 64", name="ck_runtime_portal_evidence_hash"),
        sa.CheckConstraint(
            "status <> 'passed' OR evidence_payload <> '{}'::jsonb",
            name="ck_runtime_portal_evidence_passed_payload",
        ),
        sa.CheckConstraint(
            "completed_at IS NULL OR completed_at >= started_at",
            name="ck_runtime_portal_evidence_completion",
        ),
        sa.CheckConstraint(
            "expires_at IS NULL OR expires_at > observed_at",
            name="ck_runtime_portal_evidence_expiry",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_runtime_portal_evidence_scope",
        "portal_acceptance_evidence",
        ["scope", "organization_id", "observed_at"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_runtime_portal_evidence_run",
        "portal_acceptance_evidence",
        ["validation_run_code", "validation_type"],
        schema=SCHEMA,
    )
    op.create_index(
        "uq_runtime_portal_evidence_platform_identity",
        "portal_acceptance_evidence",
        ["validation_run_code", "validation_type"],
        unique=True,
        schema=SCHEMA,
        postgresql_where=sa.text("organization_id IS NULL"),
    )
    op.create_index(
        "uq_runtime_portal_evidence_org_identity",
        "portal_acceptance_evidence",
        ["organization_id", "validation_run_code", "validation_type"],
        unique=True,
        schema=SCHEMA,
        postgresql_where=sa.text("organization_id IS NOT NULL"),
    )
    op.execute("""
        INSERT INTO security.permissions (id, resource, action, description, created_at, updated_at)
        VALUES
          (gen_random_uuid(), 'platform.portal_acceptance', 'read', 'Read governed Portal Acceptance evidence.', now(), now()),
          (gen_random_uuid(), 'platform.portal_acceptance', 'administer', 'Register governed Portal Acceptance evidence.', now(), now())
        ON CONFLICT (resource, action) DO NOTHING
    """)
    op.execute("""
        INSERT INTO security.role_permissions (id, role_id, permission_id, created_at, updated_at)
        SELECT DISTINCT gen_random_uuid(), rp.role_id, target.id, now(), now()
        FROM security.role_permissions rp
        JOIN security.permissions source ON source.id = rp.permission_id
        CROSS JOIN security.permissions target
        WHERE source.resource = 'platform.production_acceptance'
          AND target.resource = 'platform.portal_acceptance'
          AND target.action = source.action
        ON CONFLICT DO NOTHING
    """)


def downgrade() -> None:
    op.execute(
        "DELETE FROM security.role_permissions WHERE permission_id IN "
        "(SELECT id FROM security.permissions WHERE resource = 'platform.portal_acceptance')"
    )
    op.execute("DELETE FROM security.permissions WHERE resource = 'platform.portal_acceptance'")
    op.drop_table("portal_acceptance_evidence", schema=SCHEMA)
