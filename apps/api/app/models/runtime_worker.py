from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RuntimeWorker(Base):
    """Persistent identity and lifecycle state for a generic platform worker."""

    __tablename__ = "workers"
    __table_args__ = (
        UniqueConstraint("worker_key", name="uq_runtime_workers_worker_key"),
        UniqueConstraint("instance_id", name="uq_runtime_workers_instance_id"),
        CheckConstraint("length(btrim(worker_key)) > 0", name="ck_runtime_workers_worker_key_not_blank"),
        CheckConstraint("length(btrim(instance_id)) > 0", name="ck_runtime_workers_instance_id_not_blank"),
        CheckConstraint("length(btrim(worker_type)) > 0", name="ck_runtime_workers_worker_type_not_blank"),
        CheckConstraint(
            "desired_state IN ('active','paused','draining','disabled')", name="ck_runtime_workers_desired_state"
        ),
        CheckConstraint(
            "observed_state IN ('starting','ready','busy','paused','draining','offline','failed')",
            name="ck_runtime_workers_observed_state",
        ),
        CheckConstraint("jsonb_typeof(capabilities) = 'array'", name="ck_runtime_workers_capabilities_array"),
        CheckConstraint("jsonb_typeof(queue_keys) = 'array'", name="ck_runtime_workers_queue_keys_array"),
        CheckConstraint("jsonb_typeof(workload_classes) = 'array'", name="ck_runtime_workers_workload_classes_array"),
        CheckConstraint("jsonb_typeof(metadata) = 'object'", name="ck_runtime_workers_metadata_object"),
        CheckConstraint("jsonb_typeof(metrics) = 'object'", name="ck_runtime_workers_metrics_object"),
        CheckConstraint("ready_at IS NULL OR ready_at >= started_at", name="ck_runtime_workers_ready_at"),
        CheckConstraint("heartbeat_at IS NULL OR heartbeat_at >= started_at", name="ck_runtime_workers_heartbeat_at"),
        CheckConstraint(
            "last_seen_at IS NULL OR heartbeat_at IS NULL OR last_seen_at >= heartbeat_at",
            name="ck_runtime_workers_last_seen_at",
        ),
        Index("ix_runtime_workers_type_state", "worker_type", "observed_state"),
        Index("ix_runtime_workers_heartbeat", "observed_state", "heartbeat_at"),
        Index("ix_runtime_workers_desired_observed", "desired_state", "observed_state"),
        {"schema": "runtime"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    worker_key: Mapped[str] = mapped_column(String(255), nullable=False)
    instance_id: Mapped[str] = mapped_column(String(255), nullable=False)
    worker_type: Mapped[str] = mapped_column(String(64), nullable=False)
    runtime_version: Mapped[str | None] = mapped_column(String(64))
    desired_state: Mapped[str] = mapped_column(String(32), server_default="active", nullable=False)
    observed_state: Mapped[str] = mapped_column(String(32), server_default="starting", nullable=False)
    capabilities: Mapped[list[Any]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"), nullable=False)
    queue_keys: Mapped[list[Any]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"), nullable=False)
    workload_classes: Mapped[list[Any]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"), nullable=False)
    active_configuration_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "runtime.configuration_revisions.id",
            name="fk_runtime_workers_active_configuration_revision",
            ondelete="SET NULL",
        ),
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, server_default=text("'{}'::jsonb"), nullable=False
    )
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"), nullable=False)
    last_error_code: Mapped[str | None] = mapped_column(String(128))
    last_error_message: Mapped[str | None] = mapped_column(String(2000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
