from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class OperationalJob(Base):
    __tablename__ = "operational_jobs"
    __table_args__ = (
        UniqueConstraint("organization_id", "id", name="uq_control_plane_operational_jobs_tenant_id"),
        UniqueConstraint("organization_id", "code", name="uq_control_plane_operational_jobs_tenant_code"),
        CheckConstraint(
            "concurrency_policy IN ('forbid_overlap','allow_bounded','replace_pending')",
            name="ck_control_plane_operational_jobs_concurrency_policy",
        ),
        CheckConstraint(
            "misfire_policy IN ('skip','run_once','catch_up_bounded')",
            name="ck_control_plane_operational_jobs_misfire_policy",
        ),
        CheckConstraint("max_concurrent_runs > 0", name="ck_control_plane_operational_jobs_max_concurrent_runs"),
        CheckConstraint(
            "max_runtime_seconds IS NULL OR max_runtime_seconds > 0",
            name="ck_control_plane_operational_jobs_max_runtime_seconds",
        ),
        CheckConstraint(
            "jsonb_typeof(parameters) = 'object'",
            name="ck_control_plane_operational_jobs_parameters_object",
        ),
        Index("ix_control_plane_operational_jobs_enabled", "organization_id", "enabled", "operation_type"),
        {"schema": "control_plane"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("core.organizations.id", name="fk_control_plane_operational_jobs_organization"),
        nullable=False,
    )
    code: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    operation_type: Mapped[str] = mapped_column(String(128), nullable=False)
    parameters: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
    concurrency_policy: Mapped[str] = mapped_column(String(32), server_default="forbid_overlap", nullable=False)
    misfire_policy: Mapped[str] = mapped_column(String(32), server_default="skip", nullable=False)
    max_concurrent_runs: Mapped[int] = mapped_column(Integer, server_default=text("1"), nullable=False)
    max_runtime_seconds: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    created_by: Mapped[str | None] = mapped_column(String(255))
    updated_by: Mapped[str | None] = mapped_column(String(255))


class OperationalSchedule(Base):
    __tablename__ = "schedules"
    __table_args__ = (
        UniqueConstraint("organization_id", "id", name="uq_control_plane_schedules_tenant_id"),
        UniqueConstraint("operational_job_id", name="uq_control_plane_schedules_job"),
        ForeignKeyConstraint(
            ["organization_id", "operational_job_id"],
            ["control_plane.operational_jobs.organization_id", "control_plane.operational_jobs.id"],
            name="fk_control_plane_schedules_job",
            ondelete="CASCADE",
        ),
        CheckConstraint("schedule_type IN ('cron')", name="ck_control_plane_schedules_type"),
        CheckConstraint("schedule_version > 0", name="ck_control_plane_schedules_version"),
        CheckConstraint(
            "end_at IS NULL OR start_at IS NULL OR end_at > start_at",
            name="ck_control_plane_schedules_window",
        ),
        Index("ix_control_plane_schedules_due", "organization_id", "enabled", "next_run_at"),
        {"schema": "control_plane"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    operational_job_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    schedule_type: Mapped[str] = mapped_column(String(32), server_default="cron", nullable=False)
    schedule_expression: Mapped[str] = mapped_column(String(255), nullable=False)
    timezone: Mapped[str] = mapped_column(String(128), server_default="UTC", nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
    start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_evaluated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    schedule_version: Mapped[int] = mapped_column(Integer, server_default=text("1"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    created_by: Mapped[str | None] = mapped_column(String(255))
    updated_by: Mapped[str | None] = mapped_column(String(255))


class SchedulerRun(Base):
    __tablename__ = "scheduler_runs"
    __table_args__ = (
        UniqueConstraint("organization_id", "id", name="uq_control_plane_scheduler_runs_tenant_id"),
        UniqueConstraint("organization_id", "logical_run_key", name="uq_control_plane_scheduler_runs_logical_key"),
        ForeignKeyConstraint(
            ["organization_id", "operational_job_id"],
            ["control_plane.operational_jobs.organization_id", "control_plane.operational_jobs.id"],
            name="fk_control_plane_scheduler_runs_job",
        ),
        ForeignKeyConstraint(
            ["organization_id", "schedule_id"],
            ["control_plane.schedules.organization_id", "control_plane.schedules.id"],
            name="fk_control_plane_scheduler_runs_schedule",
        ),
        ForeignKeyConstraint(
            ["organization_id", "runtime_execution_id"],
            ["runtime.executions.organization_id", "runtime.executions.id"],
            name="fk_control_plane_scheduler_runs_runtime_execution",
        ),
        CheckConstraint(
            "trigger_type IN ('schedule','manual','recovery')",
            name="ck_control_plane_scheduler_runs_trigger_type",
        ),
        CheckConstraint(
            "status IN ('pending','claimed','dispatched','succeeded','failed','skipped','cancelled')",
            name="ck_control_plane_scheduler_runs_status",
        ),
        CheckConstraint(
            "jsonb_typeof(parameters_snapshot) = 'object'",
            name="ck_control_plane_scheduler_runs_parameters_object",
        ),
        CheckConstraint("jsonb_typeof(outcome) = 'object'", name="ck_control_plane_scheduler_runs_outcome_object"),
        CheckConstraint(
            "finished_at IS NULL OR started_at IS NULL OR finished_at >= started_at",
            name="ck_control_plane_scheduler_runs_finished_at",
        ),
        CheckConstraint(
            "status NOT IN ('succeeded','failed','skipped','cancelled') OR finished_at IS NOT NULL",
            name="ck_control_plane_scheduler_runs_terminal_finished",
        ),
        CheckConstraint(
            "status <> 'succeeded' OR (error_code IS NULL AND error_message IS NULL)",
            name="ck_control_plane_scheduler_runs_success_clean",
        ),
        CheckConstraint(
            "status <> 'failed' OR error_code IS NOT NULL OR error_message IS NOT NULL",
            name="ck_control_plane_scheduler_runs_failure_reason",
        ),
        Index("ix_control_plane_scheduler_runs_queue", "organization_id", "status", "requested_at"),
        Index("ix_control_plane_scheduler_runs_job", "organization_id", "operational_job_id", "created_at"),
        Index("ix_control_plane_scheduler_runs_runtime", "organization_id", "runtime_execution_id"),
        {"schema": "control_plane"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    operational_job_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    schedule_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    schedule_version: Mapped[int | None] = mapped_column(Integer)
    trigger_type: Mapped[str] = mapped_column(String(32), nullable=False)
    logical_run_key: Mapped[str] = mapped_column(String(512), nullable=False)
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32), server_default="pending", nullable=False)
    parameters_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb"), nullable=False
    )
    runtime_execution_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    requested_by: Mapped[str | None] = mapped_column(String(255))
    correlation_id: Mapped[str | None] = mapped_column(String(128))
    outcome: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(128))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class SchedulerClaim(Base):
    __tablename__ = "scheduler_claims"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "resource_type",
            "resource_id",
            name="uq_control_plane_scheduler_claims_resource",
        ),
        CheckConstraint(
            "resource_type IN ('schedule_evaluation','run_dispatch')",
            name="ck_control_plane_scheduler_claims_resource_type",
        ),
        CheckConstraint("expires_at > claimed_at", name="ck_control_plane_scheduler_claims_expiry"),
        CheckConstraint("heartbeat_at >= claimed_at", name="ck_control_plane_scheduler_claims_heartbeat"),
        Index("ix_control_plane_scheduler_claims_expiry", "organization_id", "expires_at"),
        Index("ix_control_plane_scheduler_claims_owner", "owner_id", "expires_at"),
        {"schema": "control_plane"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("core.organizations.id", name="fk_control_plane_scheduler_claims_organization"),
        nullable=False,
    )
    resource_type: Mapped[str] = mapped_column(String(32), nullable=False)
    resource_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    owner_id: Mapped[str] = mapped_column(String(255), nullable=False)
    claim_token: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, default=uuid.uuid4)
    claimed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    heartbeat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
