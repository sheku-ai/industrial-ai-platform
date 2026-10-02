"""add persistent control-plane scheduler model

Revision ID: 20260620_2301
Revises: 20260619_2180
Create Date: 2026-06-20
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260620_2301"
down_revision: str | None = "20260619_2180"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS control_plane")

    op.create_table(
        "operational_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("operation_type", sa.String(length=128), nullable=False),
        sa.Column("parameters", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("concurrency_policy", sa.String(length=32), server_default="forbid_overlap", nullable=False),
        sa.Column("misfire_policy", sa.String(length=32), server_default="skip", nullable=False),
        sa.Column("max_concurrent_runs", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("max_runtime_seconds", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=True),
        sa.Column("updated_by", sa.String(length=255), nullable=True),
        sa.CheckConstraint(
            "concurrency_policy IN ('forbid_overlap','allow_bounded','replace_pending')",
            name="ck_control_plane_operational_jobs_concurrency_policy",
        ),
        sa.CheckConstraint(
            "misfire_policy IN ('skip','run_once','catch_up_bounded')",
            name="ck_control_plane_operational_jobs_misfire_policy",
        ),
        sa.CheckConstraint("max_concurrent_runs > 0", name="ck_control_plane_operational_jobs_max_concurrent_runs"),
        sa.CheckConstraint(
            "max_runtime_seconds IS NULL OR max_runtime_seconds > 0",
            name="ck_control_plane_operational_jobs_max_runtime_seconds",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(parameters) = 'object'",
            name="ck_control_plane_operational_jobs_parameters_object",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["core.organizations.id"],
            name="fk_control_plane_operational_jobs_organization",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_operational_jobs")),
        sa.UniqueConstraint("organization_id", "code", name="uq_control_plane_operational_jobs_tenant_code"),
        sa.UniqueConstraint("organization_id", "id", name="uq_control_plane_operational_jobs_tenant_id"),
        schema="control_plane",
    )
    op.create_index(
        "ix_control_plane_operational_jobs_enabled",
        "operational_jobs",
        ["organization_id", "enabled", "operation_type"],
        unique=False,
        schema="control_plane",
    )

    op.create_table(
        "schedules",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("operational_job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("schedule_type", sa.String(length=32), server_default="cron", nullable=False),
        sa.Column("schedule_expression", sa.String(length=255), nullable=False),
        sa.Column("timezone", sa.String(length=128), server_default="UTC", nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_evaluated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("schedule_version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=True),
        sa.Column("updated_by", sa.String(length=255), nullable=True),
        sa.CheckConstraint("schedule_type IN ('cron')", name="ck_control_plane_schedules_type"),
        sa.CheckConstraint("schedule_version > 0", name="ck_control_plane_schedules_version"),
        sa.CheckConstraint(
            "end_at IS NULL OR start_at IS NULL OR end_at > start_at",
            name="ck_control_plane_schedules_window",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "operational_job_id"],
            ["control_plane.operational_jobs.organization_id", "control_plane.operational_jobs.id"],
            name="fk_control_plane_schedules_job",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_schedules")),
        sa.UniqueConstraint("operational_job_id", name="uq_control_plane_schedules_job"),
        sa.UniqueConstraint("organization_id", "id", name="uq_control_plane_schedules_tenant_id"),
        schema="control_plane",
    )
    op.create_index(
        "ix_control_plane_schedules_due",
        "schedules",
        ["organization_id", "enabled", "next_run_at"],
        unique=False,
        schema="control_plane",
    )

    op.create_table(
        "scheduler_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("operational_job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("schedule_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("schedule_version", sa.Integer(), nullable=True),
        sa.Column("trigger_type", sa.String(length=32), nullable=False),
        sa.Column("logical_run_key", sa.String(length=512), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=32), server_default="pending", nullable=False),
        sa.Column("parameters_snapshot", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("runtime_execution_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("requested_by", sa.String(length=255), nullable=True),
        sa.Column("correlation_id", sa.String(length=128), nullable=True),
        sa.Column("outcome", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "trigger_type IN ('schedule','manual','recovery')",
            name="ck_control_plane_scheduler_runs_trigger_type",
        ),
        sa.CheckConstraint(
            "status IN ('pending','claimed','dispatched','succeeded','failed','skipped','cancelled')",
            name="ck_control_plane_scheduler_runs_status",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(parameters_snapshot) = 'object'",
            name="ck_control_plane_scheduler_runs_parameters_object",
        ),
        sa.CheckConstraint("jsonb_typeof(outcome) = 'object'", name="ck_control_plane_scheduler_runs_outcome_object"),
        sa.CheckConstraint(
            "finished_at IS NULL OR started_at IS NULL OR finished_at >= started_at",
            name="ck_control_plane_scheduler_runs_finished_at",
        ),
        sa.CheckConstraint(
            "status NOT IN ('succeeded','failed','skipped','cancelled') OR finished_at IS NOT NULL",
            name="ck_control_plane_scheduler_runs_terminal_finished",
        ),
        sa.CheckConstraint(
            "status <> 'succeeded' OR (error_code IS NULL AND error_message IS NULL)",
            name="ck_control_plane_scheduler_runs_success_clean",
        ),
        sa.CheckConstraint(
            "status <> 'failed' OR error_code IS NOT NULL OR error_message IS NOT NULL",
            name="ck_control_plane_scheduler_runs_failure_reason",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "operational_job_id"],
            ["control_plane.operational_jobs.organization_id", "control_plane.operational_jobs.id"],
            name="fk_control_plane_scheduler_runs_job",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "schedule_id"],
            ["control_plane.schedules.organization_id", "control_plane.schedules.id"],
            name="fk_control_plane_scheduler_runs_schedule",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "runtime_execution_id"],
            ["runtime.executions.organization_id", "runtime.executions.id"],
            name="fk_control_plane_scheduler_runs_runtime_execution",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scheduler_runs")),
        sa.UniqueConstraint("organization_id", "id", name="uq_control_plane_scheduler_runs_tenant_id"),
        sa.UniqueConstraint("organization_id", "logical_run_key", name="uq_control_plane_scheduler_runs_logical_key"),
        schema="control_plane",
    )
    op.create_index(
        "ix_control_plane_scheduler_runs_job",
        "scheduler_runs",
        ["organization_id", "operational_job_id", "created_at"],
        unique=False,
        schema="control_plane",
    )
    op.create_index(
        "ix_control_plane_scheduler_runs_queue",
        "scheduler_runs",
        ["organization_id", "status", "requested_at"],
        unique=False,
        schema="control_plane",
    )
    op.create_index(
        "ix_control_plane_scheduler_runs_runtime",
        "scheduler_runs",
        ["organization_id", "runtime_execution_id"],
        unique=False,
        schema="control_plane",
    )

    op.create_table(
        "scheduler_claims",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("resource_type", sa.String(length=32), nullable=False),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_id", sa.String(length=255), nullable=False),
        sa.Column("claim_token", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "resource_type IN ('schedule_evaluation','run_dispatch')",
            name="ck_control_plane_scheduler_claims_resource_type",
        ),
        sa.CheckConstraint("expires_at > claimed_at", name="ck_control_plane_scheduler_claims_expiry"),
        sa.CheckConstraint("heartbeat_at >= claimed_at", name="ck_control_plane_scheduler_claims_heartbeat"),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["core.organizations.id"],
            name="fk_control_plane_scheduler_claims_organization",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scheduler_claims")),
        sa.UniqueConstraint(
            "organization_id",
            "resource_type",
            "resource_id",
            name="uq_control_plane_scheduler_claims_resource",
        ),
        schema="control_plane",
    )
    op.create_index(
        "ix_control_plane_scheduler_claims_expiry",
        "scheduler_claims",
        ["organization_id", "expires_at"],
        unique=False,
        schema="control_plane",
    )
    op.create_index(
        "ix_control_plane_scheduler_claims_owner",
        "scheduler_claims",
        ["owner_id", "expires_at"],
        unique=False,
        schema="control_plane",
    )


def downgrade() -> None:
    op.drop_index("ix_control_plane_scheduler_claims_owner", table_name="scheduler_claims", schema="control_plane")
    op.drop_index("ix_control_plane_scheduler_claims_expiry", table_name="scheduler_claims", schema="control_plane")
    op.drop_table("scheduler_claims", schema="control_plane")

    op.drop_index("ix_control_plane_scheduler_runs_runtime", table_name="scheduler_runs", schema="control_plane")
    op.drop_index("ix_control_plane_scheduler_runs_queue", table_name="scheduler_runs", schema="control_plane")
    op.drop_index("ix_control_plane_scheduler_runs_job", table_name="scheduler_runs", schema="control_plane")
    op.drop_table("scheduler_runs", schema="control_plane")

    op.drop_index("ix_control_plane_schedules_due", table_name="schedules", schema="control_plane")
    op.drop_table("schedules", schema="control_plane")

    op.drop_index("ix_control_plane_operational_jobs_enabled", table_name="operational_jobs", schema="control_plane")
    op.drop_table("operational_jobs", schema="control_plane")

    op.execute("DROP SCHEMA IF EXISTS control_plane")
