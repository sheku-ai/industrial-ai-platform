"""persistent generic runtime foundation

Revision ID: 20260619_1901
Revises: 20260618_1510
Create Date: 2026-06-19
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260619_1901"
down_revision: Union[str, None] = "20260618_1510"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS runtime")

    op.create_table(
        "executions",
        sa.Column("id", UUID, nullable=False),
        sa.Column("organization_id", UUID, nullable=False),
        sa.Column("execution_type", sa.String(64), nullable=False),
        sa.Column("subject_type", sa.String(64), nullable=False),
        sa.Column("subject_id", UUID, nullable=False),
        sa.Column("requested_by", sa.String(255), nullable=True),
        sa.Column("correlation_id", sa.String(128), nullable=True),
        sa.Column("idempotency_key", sa.String(255), nullable=True),
        sa.Column("priority", sa.Integer(), server_default=sa.text("100"), nullable=False),
        sa.Column("status", sa.String(32), server_default="pending", nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("input_payload", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("policy_snapshot", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("metrics", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("error_code", sa.String(128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=True),
        sa.Column("updated_by", sa.String(255), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["core.organizations.id"], name="fk_runtime_executions_organization"),
        sa.PrimaryKeyConstraint("id", name="pk_runtime_executions"),
        sa.UniqueConstraint("organization_id", "id", name="uq_runtime_executions_tenant_id"),
        sa.CheckConstraint("priority >= 0", name="ck_runtime_executions_priority"),
        sa.CheckConstraint("status IN ('pending','scheduled','leased','running','succeeded','failed','cancelled','expired','dead_lettered')", name="ck_runtime_executions_status"),
        sa.CheckConstraint("available_at >= requested_at", name="ck_runtime_executions_available_at"),
        sa.CheckConstraint("started_at IS NULL OR started_at >= requested_at", name="ck_runtime_executions_started_at"),
        sa.CheckConstraint("finished_at IS NULL OR started_at IS NULL OR finished_at >= started_at", name="ck_runtime_executions_finished_at"),
        sa.CheckConstraint("cancel_requested_at IS NULL OR cancel_requested_at >= requested_at", name="ck_runtime_executions_cancel_requested_at"),
        sa.CheckConstraint("status NOT IN ('succeeded','failed','cancelled','dead_lettered') OR finished_at IS NOT NULL", name="ck_runtime_executions_terminal_finished"),
        sa.CheckConstraint("status <> 'succeeded' OR (error_code IS NULL AND error_message IS NULL)", name="ck_runtime_executions_success_clean"),
        sa.CheckConstraint("status NOT IN ('failed','expired','dead_lettered') OR error_code IS NOT NULL OR error_message IS NOT NULL", name="ck_runtime_executions_failure_reason"),
        schema="runtime",
    )
    op.create_index("ix_runtime_executions_queue", "executions", ["organization_id", "status", "priority", "available_at", "created_at"], schema="runtime")
    op.create_index("ix_runtime_executions_type_status", "executions", ["organization_id", "execution_type", "status"], schema="runtime")
    op.create_index("ix_runtime_executions_subject", "executions", ["organization_id", "subject_type", "subject_id"], schema="runtime")
    op.create_index("ix_runtime_executions_correlation", "executions", ["organization_id", "correlation_id"], schema="runtime")
    op.create_index("uq_runtime_executions_idempotency", "executions", ["organization_id", "execution_type", "idempotency_key"], unique=True, schema="runtime", postgresql_where=sa.text("idempotency_key IS NOT NULL"))

    op.create_table(
        "execution_attempts",
        sa.Column("id", UUID, nullable=False),
        sa.Column("organization_id", UUID, nullable=False),
        sa.Column("execution_id", UUID, nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("worker_id", sa.String(255), nullable=True),
        sa.Column("lease_token", UUID, nullable=True),
        sa.Column("leased_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_reference", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("metrics", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("error_code", sa.String(128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_runtime_execution_attempts"),
        sa.UniqueConstraint("organization_id", "execution_id", "id", name="uq_runtime_execution_attempts_tenant_execution_id"),
        sa.UniqueConstraint("execution_id", "attempt_number", name="uq_runtime_execution_attempts_number"),
        sa.ForeignKeyConstraint(["organization_id", "execution_id"], ["runtime.executions.organization_id", "runtime.executions.id"], name="fk_runtime_execution_attempts_execution", ondelete="CASCADE"),
        sa.CheckConstraint("attempt_number > 0", name="ck_runtime_execution_attempts_number"),
        sa.CheckConstraint("status IN ('leased','running','succeeded','failed','abandoned','expired','cancelled')", name="ck_runtime_execution_attempts_status"),
        sa.CheckConstraint("finished_at IS NULL OR started_at IS NULL OR finished_at >= started_at", name="ck_runtime_execution_attempts_finished_at"),
        sa.CheckConstraint("lease_expires_at IS NULL OR leased_at IS NULL OR lease_expires_at > leased_at", name="ck_runtime_execution_attempts_lease_window"),
        sa.CheckConstraint("heartbeat_at IS NULL OR leased_at IS NULL OR heartbeat_at >= leased_at", name="ck_runtime_execution_attempts_heartbeat"),
        sa.CheckConstraint("status NOT IN ('leased','running') OR (worker_id IS NOT NULL AND lease_token IS NOT NULL AND leased_at IS NOT NULL AND lease_expires_at IS NOT NULL)", name="ck_runtime_execution_attempts_active_lease"),
        sa.CheckConstraint("status NOT IN ('succeeded','failed','abandoned','expired','cancelled') OR finished_at IS NOT NULL", name="ck_runtime_execution_attempts_closed_finished"),
        sa.CheckConstraint("status <> 'succeeded' OR (error_code IS NULL AND error_message IS NULL)", name="ck_runtime_execution_attempts_success_clean"),
        sa.CheckConstraint("status NOT IN ('failed','abandoned','expired') OR error_code IS NOT NULL OR error_message IS NOT NULL", name="ck_runtime_execution_attempts_failure_reason"),
        schema="runtime",
    )
    op.create_index("ix_runtime_execution_attempts_lease", "execution_attempts", ["organization_id", "status", "lease_expires_at"], schema="runtime")
    op.create_index("ix_runtime_execution_attempts_worker", "execution_attempts", ["worker_id", "status"], schema="runtime")
    op.create_index("uq_runtime_execution_attempts_active", "execution_attempts", ["execution_id"], unique=True, schema="runtime", postgresql_where=sa.text("status IN ('leased','running')"))

    op.create_table(
        "execution_events",
        sa.Column("id", UUID, nullable=False),
        sa.Column("organization_id", UUID, nullable=False),
        sa.Column("execution_id", UUID, nullable=False),
        sa.Column("attempt_id", UUID, nullable=True),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("sequence_number", sa.BigInteger(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("actor_type", sa.String(32), nullable=False),
        sa.Column("actor_reference", sa.String(255), nullable=True),
        sa.Column("payload", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_runtime_execution_events"),
        sa.UniqueConstraint("execution_id", "sequence_number", name="uq_runtime_execution_events_sequence"),
        sa.ForeignKeyConstraint(["organization_id", "execution_id"], ["runtime.executions.organization_id", "runtime.executions.id"], name="fk_runtime_execution_events_execution", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id", "execution_id", "attempt_id"], ["runtime.execution_attempts.organization_id", "runtime.execution_attempts.execution_id", "runtime.execution_attempts.id"], name="fk_runtime_execution_events_attempt"),
        sa.CheckConstraint("sequence_number > 0", name="ck_runtime_execution_events_sequence"),
        schema="runtime",
    )
    op.create_index("ix_runtime_execution_events_timeline", "execution_events", ["organization_id", "execution_id", "occurred_at"], schema="runtime")

    op.create_table(
        "execution_artifacts",
        sa.Column("id", UUID, nullable=False),
        sa.Column("organization_id", UUID, nullable=False),
        sa.Column("execution_id", UUID, nullable=False),
        sa.Column("attempt_id", UUID, nullable=True),
        sa.Column("artifact_type", sa.String(64), nullable=False),
        sa.Column("storage_uri", sa.Text(), nullable=False),
        sa.Column("media_type", sa.String(255), nullable=True),
        sa.Column("checksum_sha256", sa.String(64), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("metadata", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_runtime_execution_artifacts"),
        sa.ForeignKeyConstraint(["organization_id", "execution_id"], ["runtime.executions.organization_id", "runtime.executions.id"], name="fk_runtime_execution_artifacts_execution", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id", "execution_id", "attempt_id"], ["runtime.execution_attempts.organization_id", "runtime.execution_attempts.execution_id", "runtime.execution_attempts.id"], name="fk_runtime_execution_artifacts_attempt"),
        sa.CheckConstraint("size_bytes IS NULL OR size_bytes >= 0", name="ck_runtime_execution_artifacts_size"),
        sa.CheckConstraint("checksum_sha256 IS NULL OR checksum_sha256 ~ '^[0-9a-f]{64}$'", name="ck_runtime_execution_artifacts_checksum"),
        schema="runtime",
    )
    op.create_index("ix_runtime_execution_artifacts_type", "execution_artifacts", ["organization_id", "execution_id", "artifact_type"], schema="runtime")

    op.execute("""
        CREATE FUNCTION runtime.fn_runtime_reject_event_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'runtime.execution_events is append-only';
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER trg_runtime_execution_events_append_only
        BEFORE UPDATE OR DELETE ON runtime.execution_events
        FOR EACH ROW EXECUTE FUNCTION runtime.fn_runtime_reject_event_mutation()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_runtime_execution_events_append_only ON runtime.execution_events")
    op.execute("DROP FUNCTION IF EXISTS runtime.fn_runtime_reject_event_mutation()")
    op.drop_table("execution_artifacts", schema="runtime")
    op.drop_table("execution_events", schema="runtime")
    op.drop_table("execution_attempts", schema="runtime")
    op.drop_table("executions", schema="runtime")
    op.execute("DROP SCHEMA IF EXISTS runtime")
