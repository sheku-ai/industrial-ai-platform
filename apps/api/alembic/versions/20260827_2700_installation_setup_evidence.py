"""add authoritative installation setup evidence

Revision ID: 20260827_2700
Revises: 20260826_2600
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260827_2700"
down_revision: str | None = "20260826_2600"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "installation_setups",
        sa.Column("installation_setup_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("installation_instance_id", sa.String(length=128), nullable=False),
        sa.Column("setup_schema_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=True),
        sa.Column("updated_by", sa.String(length=255), nullable=True),
        sa.PrimaryKeyConstraint("installation_setup_id", name="pk_installation_setups"),
        sa.UniqueConstraint("installation_instance_id", name="uq_installation_setups_instance"),
        sa.CheckConstraint(
            "length(btrim(installation_instance_id)) > 0",
            name="ck_installation_setups_instance_not_blank",
        ),
        sa.CheckConstraint("setup_schema_version > 0", name="ck_installation_setups_schema_version"),
        schema="core",
    )
    op.create_table(
        "installation_setup_evidence",
        sa.Column("installation_setup_evidence_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("installation_setup_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("evidence_type", sa.String(length=64), nullable=False),
        sa.Column("evidence_version", sa.Integer(), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("resource_type", sa.String(length=128), nullable=False),
        sa.Column("resource_id", sa.String(length=255), nullable=False),
        sa.Column("evidence_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("evidence_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=True),
        sa.PrimaryKeyConstraint("installation_setup_evidence_id", name="pk_installation_setup_evidence"),
        sa.UniqueConstraint(
            "installation_setup_id", "evidence_type", name="uq_installation_setup_evidence_type"
        ),
        sa.ForeignKeyConstraint(
            ["installation_setup_id"],
            ["core.installation_setups.installation_setup_id"],
            name="fk_installation_setup_evidence_setup",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["core.organizations.id"],
            name="fk_installation_setup_evidence_organization",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("evidence_version > 0", name="ck_installation_setup_evidence_version"),
        sa.CheckConstraint(
            "evidence_type IN ('organization_configured','administrator_configured','preferences_configured')",
            name="ck_installation_setup_evidence_type",
        ),
        sa.CheckConstraint("char_length(evidence_hash) = 64", name="ck_installation_setup_evidence_hash"),
        schema="core",
    )
    op.create_index(
        "ix_installation_setup_evidence_organization",
        "installation_setup_evidence",
        ["organization_id", "evidence_type"],
        schema="core",
    )
    op.create_table(
        "installation_completion_evidence",
        sa.Column("installation_completion_evidence_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("installation_setup_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("initial_identity_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("initial_role_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("setup_schema_version", sa.Integer(), nullable=False),
        sa.Column("evidence_digest", sa.String(length=64), nullable=False),
        sa.Column("completion_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_by", sa.String(length=255), nullable=True),
        sa.PrimaryKeyConstraint(
            "installation_completion_evidence_id", name="pk_installation_completion_evidence"
        ),
        sa.UniqueConstraint("installation_setup_id", name="uq_installation_completion_setup"),
        sa.ForeignKeyConstraint(
            ["installation_setup_id"],
            ["core.installation_setups.installation_setup_id"],
            name="fk_installation_completion_setup",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["core.organizations.id"],
            name="fk_installation_completion_organization",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["initial_role_id"],
            ["security.roles.id"],
            name="fk_installation_completion_role",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("setup_schema_version > 0", name="ck_installation_completion_schema_version"),
        sa.CheckConstraint("char_length(evidence_digest) = 64", name="ck_installation_completion_digest"),
        schema="core",
    )


def downgrade() -> None:
    op.drop_table("installation_completion_evidence", schema="core")
    op.drop_index(
        "ix_installation_setup_evidence_organization",
        table_name="installation_setup_evidence",
        schema="core",
    )
    op.drop_table("installation_setup_evidence", schema="core")
    op.drop_table("installation_setups", schema="core")
