from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class WorkflowDefinition(Base):
    __tablename__ = "workflows"
    __table_args__ = (
        UniqueConstraint("workflow_key", "workflow_version", name="uq_runtime_workflows_key_version"),
        CheckConstraint(
            "workflow_status IN ('draft','prepared','active','disabled','failed')", name="ck_runtime_workflows_status"
        ),
        Index("ix_runtime_workflows_key", "workflow_key"),
        Index("ix_runtime_workflows_status", "workflow_status"),
        {"schema": "runtime"},
    )

    workflow_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workflow_name: Mapped[str] = mapped_column(String(255), nullable=False)
    workflow_key: Mapped[str] = mapped_column(String(128), nullable=False)
    workflow_status: Mapped[str] = mapped_column(String(32), server_default="prepared", nullable=False)
    workflow_version: Mapped[str] = mapped_column(String(64), server_default="1.0", nullable=False)
    workflow_type: Mapped[str] = mapped_column(String(128), server_default="platform_runtime", nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    runtime_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class WorkflowStep(Base):
    __tablename__ = "workflow_steps"
    __table_args__ = (
        UniqueConstraint("workflow_id", "step_key", name="uq_runtime_workflow_steps_key"),
        UniqueConstraint("workflow_id", "step_order", name="uq_runtime_workflow_steps_order"),
        CheckConstraint("step_order >= 0", name="ck_runtime_workflow_steps_order"),
        CheckConstraint(
            "step_status IN ('draft','prepared','active','disabled','failed')", name="ck_runtime_workflow_steps_status"
        ),
        Index("ix_runtime_workflow_steps_workflow", "workflow_id", "step_order"),
        Index("ix_runtime_workflow_steps_domain", "runtime_domain"),
        {"schema": "runtime"},
    )

    workflow_step_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("runtime.workflows.workflow_id", ondelete="CASCADE"), nullable=False
    )
    step_key: Mapped[str] = mapped_column(String(128), nullable=False)
    step_name: Mapped[str] = mapped_column(String(255), nullable=False)
    step_order: Mapped[int] = mapped_column(Integer, nullable=False)
    step_type: Mapped[str] = mapped_column(String(128), nullable=False)
    step_status: Mapped[str] = mapped_column(String(32), server_default="prepared", nullable=False)
    runtime_domain: Mapped[str] = mapped_column(String(64), nullable=False)
    runtime_action: Mapped[str] = mapped_column(String(128), nullable=False)
    runtime_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class WorkflowRun(Base):
    __tablename__ = "workflow_runs"
    __table_args__ = (
        CheckConstraint(
            "run_status IN ('prepared','planned','completed','failed','blocked','disabled')",
            name="ck_runtime_workflow_runs_status",
        ),
        CheckConstraint(
            "execution_state IN ('metadata_only','planned','completed','failed','blocked','disabled')",
            name="ck_runtime_workflow_runs_execution_state",
        ),
        Index("ix_runtime_workflow_runs_workflow", "workflow_id", "created_at"),
        Index("ix_runtime_workflow_runs_status", "run_status"),
        {"schema": "runtime"},
    )

    workflow_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("runtime.workflows.workflow_id", ondelete="CASCADE"), nullable=False
    )
    run_status: Mapped[str] = mapped_column(String(32), server_default="planned", nullable=False)
    execution_state: Mapped[str] = mapped_column(String(32), server_default="metadata_only", nullable=False)
    requested_by: Mapped[str | None] = mapped_column(String(255))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_reason: Mapped[str | None] = mapped_column(Text)
    runtime_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
