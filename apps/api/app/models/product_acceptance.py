from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

ACCEPTANCE_STATUSES = (
    "PENDING",
    "RUNNING",
    "PASSED",
    "PASSED_WITH_WARNINGS",
    "BLOCKED_BY_ENVIRONMENT",
    "FAILED",
)

ACCEPTANCE_GATE_STATUSES = (*ACCEPTANCE_STATUSES, "CAPABILITY_MISSING", "SKIPPED")


class AcceptanceExecution(Base):
    __tablename__ = "acceptance_executions"
    __table_args__ = (
        UniqueConstraint("execution_key", name="uq_runtime_acceptance_executions_key"),
        CheckConstraint(
            f"status IN {ACCEPTANCE_STATUSES!r}",
            name="ck_runtime_acceptance_executions_status",
        ),
        Index("ix_runtime_acceptance_executions_correlation", "correlation_id"),
        Index("ix_runtime_acceptance_executions_status", "status"),
        Index("ix_runtime_acceptance_executions_scenario", "scenario", "started_at"),
        {"schema": "runtime"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    execution_key: Mapped[str] = mapped_column(String(255), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(255), nullable=False)
    scenario: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), server_default="PENDING", nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.organizations.id", name="fk_runtime_acceptance_executions_org")
    )
    preserve_requested: Mapped[bool] = mapped_column(server_default=text("false"), nullable=False)
    reuse_requested: Mapped[bool] = mapped_column(server_default=text("false"), nullable=False)
    cleanup_requested: Mapped[bool] = mapped_column(server_default=text("false"), nullable=False)
    report: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"), nullable=False)
    warnings: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"), nullable=False)
    blockers: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class AcceptanceGate(Base):
    __tablename__ = "acceptance_gates"
    __table_args__ = (
        UniqueConstraint("execution_id", "phase_code", "gate_code", name="uq_runtime_acceptance_gates_identity"),
        CheckConstraint(
            f"status IN {ACCEPTANCE_GATE_STATUSES!r}",
            name="ck_runtime_acceptance_gates_status",
        ),
        Index("ix_runtime_acceptance_gates_execution", "execution_id", "phase_code"),
        Index("ix_runtime_acceptance_gates_status", "status"),
        {"schema": "runtime"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    execution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "runtime.acceptance_executions.id", name="fk_runtime_acceptance_gates_execution", ondelete="CASCADE"
        ),
        nullable=False,
    )
    gate_code: Mapped[str] = mapped_column(String(128), nullable=False)
    phase_code: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(128))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class AcceptanceResource(Base):
    __tablename__ = "acceptance_resources"
    __table_args__ = (
        UniqueConstraint("execution_id", "resource_type", "external_ref", name="uq_runtime_acceptance_resources_ref"),
        Index("ix_runtime_acceptance_resources_execution", "execution_id", "resource_type"),
        Index("ix_runtime_acceptance_resources_resource_id", "resource_type", "resource_id"),
        Index("ix_runtime_acceptance_resources_cleanup", "cleanup_status"),
        {"schema": "runtime"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    execution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "runtime.acceptance_executions.id",
            name="fk_runtime_acceptance_resources_execution",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    resource_type: Mapped[str] = mapped_column(String(128), nullable=False)
    resource_id: Mapped[str | None] = mapped_column(String(255))
    external_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    created_by_execution: Mapped[bool] = mapped_column(server_default=text("false"), nullable=False)
    reused: Mapped[bool] = mapped_column(server_default=text("false"), nullable=False)
    cleanup_status: Mapped[str] = mapped_column(String(64), server_default="not_requested", nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
