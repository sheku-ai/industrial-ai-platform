"""add governed organization deletion lifecycle

Revision ID: 20260715_960
Revises: 20260714_950
Create Date: 2026-07-15 00:00:00.000000
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260715_960"
down_revision = "20260714_950"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "organization_deletion_executions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("organization_name_hash", sa.String(64), nullable=False),
        sa.Column("requested_by", sa.String(255), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("resource_counts_before", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("resource_counts_deleted", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("external_objects", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("object_storage_objects_deleted", sa.Integer(), server_default="0", nullable=False),
        sa.Column("blockers", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("warnings", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("correlation_id", sa.String(128), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "status IN ('deletion_requested','deletion_previewed','deleting','deleted','failed')",
            name="ck_core_organization_deletion_status",
        ),
        sa.UniqueConstraint(
            "organization_id",
            "idempotency_key",
            name="uq_core_organization_deletion_idempotency",
        ),
        schema="core",
    )
    op.create_index(
        "ix_core_organization_deletion_org",
        "organization_deletion_executions",
        ["organization_id", "created_at"],
        schema="core",
    )
    op.create_index(
        "ix_core_organization_deletion_status",
        "organization_deletion_executions",
        ["status", "updated_at"],
        schema="core",
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION runtime.fn_runtime_reject_event_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NULLIF(current_setting('app.organization_deletion_execution_id', true), '') IS NOT NULL THEN
                RETURN OLD;
            END IF;
            RAISE EXCEPTION 'runtime.execution_events is append-only';
        END;
        $$
        """
    )


def downgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION runtime.fn_runtime_reject_event_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'runtime.execution_events is append-only';
        END;
        $$
        """
    )
    op.drop_index(
        "ix_core_organization_deletion_status",
        table_name="organization_deletion_executions",
        schema="core",
    )
    op.drop_index(
        "ix_core_organization_deletion_org",
        table_name="organization_deletion_executions",
        schema="core",
    )
    op.drop_table("organization_deletion_executions", schema="core")
