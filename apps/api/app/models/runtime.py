from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
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


class RuntimeExecution(Base):
    __tablename__ = "executions"
    __table_args__ = (
        UniqueConstraint("organization_id", "id", name="uq_runtime_executions_tenant_id"),
        CheckConstraint("priority >= 0", name="ck_runtime_executions_priority"),
        CheckConstraint(
            "status IN ('pending','scheduled','leased','running','succeeded','failed','cancelled',"
            "'expired','dead_lettered')",
            name="ck_runtime_executions_status",
        ),
        CheckConstraint("available_at >= requested_at", name="ck_runtime_executions_available_at"),
        CheckConstraint("started_at IS NULL OR started_at >= requested_at", name="ck_runtime_executions_started_at"),
        CheckConstraint(
            "finished_at IS NULL OR started_at IS NULL OR finished_at >= started_at",
            name="ck_runtime_executions_finished_at",
        ),
        CheckConstraint(
            "cancel_requested_at IS NULL OR cancel_requested_at >= requested_at",
            name="ck_runtime_executions_cancel_requested_at",
        ),
        CheckConstraint(
            "status NOT IN ('succeeded','failed','cancelled','dead_lettered') OR finished_at IS NOT NULL",
            name="ck_runtime_executions_terminal_finished",
        ),
        CheckConstraint(
            "status <> 'succeeded' OR (error_code IS NULL AND error_message IS NULL)",
            name="ck_runtime_executions_success_clean",
        ),
        CheckConstraint(
            "status NOT IN ('failed','expired','dead_lettered') OR error_code IS NOT NULL OR error_message IS NOT NULL",
            name="ck_runtime_executions_failure_reason",
        ),
        Index("ix_runtime_executions_queue", "organization_id", "status", "priority", "available_at", "created_at"),
        Index("ix_runtime_executions_type_status", "organization_id", "execution_type", "status"),
        Index("ix_runtime_executions_subject", "organization_id", "subject_type", "subject_id"),
        Index("ix_runtime_executions_correlation", "organization_id", "correlation_id"),
        Index(
            "uq_runtime_executions_idempotency",
            "organization_id",
            "execution_type",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
        {"schema": "runtime"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("core.organizations.id", name="fk_runtime_executions_organization"),
        nullable=False,
    )
    execution_type: Mapped[str] = mapped_column(String(64), nullable=False)
    subject_type: Mapped[str] = mapped_column(String(64), nullable=False)
    subject_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    requested_by: Mapped[str | None] = mapped_column(String(255))
    correlation_id: Mapped[str | None] = mapped_column(String(128))
    idempotency_key: Mapped[str | None] = mapped_column(String(255))
    priority: Mapped[int] = mapped_column(Integer, server_default=text("100"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), server_default="pending", nullable=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    input_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"), nullable=False)
    policy_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"), nullable=False)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(128))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    created_by: Mapped[str | None] = mapped_column(String(255))
    updated_by: Mapped[str | None] = mapped_column(String(255))


class RuntimeExecutionAttempt(Base):
    __tablename__ = "execution_attempts"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "execution_id", "id", name="uq_runtime_execution_attempts_tenant_execution_id"
        ),
        UniqueConstraint("execution_id", "attempt_number", name="uq_runtime_execution_attempts_number"),
        ForeignKeyConstraint(
            ["organization_id", "execution_id"],
            ["runtime.executions.organization_id", "runtime.executions.id"],
            name="fk_runtime_execution_attempts_execution",
            ondelete="CASCADE",
        ),
        CheckConstraint("attempt_number > 0", name="ck_runtime_execution_attempts_number"),
        CheckConstraint(
            "status IN ('leased','running','succeeded','failed','abandoned','expired','cancelled')",
            name="ck_runtime_execution_attempts_status",
        ),
        CheckConstraint(
            "finished_at IS NULL OR started_at IS NULL OR finished_at >= started_at",
            name="ck_runtime_execution_attempts_finished_at",
        ),
        CheckConstraint(
            "lease_expires_at IS NULL OR leased_at IS NULL OR lease_expires_at > leased_at",
            name="ck_runtime_execution_attempts_lease_window",
        ),
        CheckConstraint(
            "heartbeat_at IS NULL OR leased_at IS NULL OR heartbeat_at >= leased_at",
            name="ck_runtime_execution_attempts_heartbeat",
        ),
        CheckConstraint(
            "status NOT IN ('leased','running') OR (worker_id IS NOT NULL AND lease_token IS NOT NULL "
            "AND leased_at IS NOT NULL AND lease_expires_at IS NOT NULL)",
            name="ck_runtime_execution_attempts_active_lease",
        ),
        CheckConstraint(
            "status NOT IN ('succeeded','failed','abandoned','expired','cancelled') OR finished_at IS NOT NULL",
            name="ck_runtime_execution_attempts_closed_finished",
        ),
        CheckConstraint(
            "status <> 'succeeded' OR (error_code IS NULL AND error_message IS NULL)",
            name="ck_runtime_execution_attempts_success_clean",
        ),
        CheckConstraint(
            "status NOT IN ('failed','abandoned','expired') OR error_code IS NOT NULL OR error_message IS NOT NULL",
            name="ck_runtime_execution_attempts_failure_reason",
        ),
        Index("ix_runtime_execution_attempts_lease", "organization_id", "status", "lease_expires_at"),
        Index("ix_runtime_execution_attempts_worker", "worker_id", "status"),
        Index(
            "uq_runtime_execution_attempts_active",
            "execution_id",
            unique=True,
            postgresql_where=text("status IN ('leased','running')"),
        ),
        {"schema": "runtime"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    execution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    worker_id: Mapped[str | None] = mapped_column(String(255))
    lease_token: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    leased_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    provider_reference: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb"), nullable=False
    )
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(128))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class RuntimeExecutionEvent(Base):
    __tablename__ = "execution_events"
    __table_args__ = (
        UniqueConstraint("execution_id", "sequence_number", name="uq_runtime_execution_events_sequence"),
        ForeignKeyConstraint(
            ["organization_id", "execution_id"],
            ["runtime.executions.organization_id", "runtime.executions.id"],
            name="fk_runtime_execution_events_execution",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organization_id", "execution_id", "attempt_id"],
            [
                "runtime.execution_attempts.organization_id",
                "runtime.execution_attempts.execution_id",
                "runtime.execution_attempts.id",
            ],
            name="fk_runtime_execution_events_attempt",
        ),
        CheckConstraint("sequence_number > 0", name="ck_runtime_execution_events_sequence"),
        Index("ix_runtime_execution_events_timeline", "organization_id", "execution_id", "occurred_at"),
        {"schema": "runtime"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    execution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    attempt_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    sequence_number: Mapped[int] = mapped_column(BigInteger, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_reference: Mapped[str | None] = mapped_column(String(255))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class RuntimeExecutionArtifact(Base):
    __tablename__ = "execution_artifacts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "execution_id"],
            ["runtime.executions.organization_id", "runtime.executions.id"],
            name="fk_runtime_execution_artifacts_execution",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organization_id", "execution_id", "attempt_id"],
            [
                "runtime.execution_attempts.organization_id",
                "runtime.execution_attempts.execution_id",
                "runtime.execution_attempts.id",
            ],
            name="fk_runtime_execution_artifacts_attempt",
        ),
        CheckConstraint("size_bytes IS NULL OR size_bytes >= 0", name="ck_runtime_execution_artifacts_size"),
        CheckConstraint(
            "checksum_sha256 IS NULL OR checksum_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_runtime_execution_artifacts_checksum",
        ),
        Index("ix_runtime_execution_artifacts_type", "organization_id", "execution_id", "artifact_type"),
        {"schema": "runtime"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    execution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    attempt_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    artifact_type: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_uri: Mapped[str] = mapped_column(Text, nullable=False)
    media_type: Mapped[str | None] = mapped_column(String(255))
    checksum_sha256: Mapped[str | None] = mapped_column(String(64))
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, server_default=text("'{}'::jsonb"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class RuntimePersistenceRecord(Base):
    __tablename__ = "persistence_records"
    __table_args__ = (
        UniqueConstraint(
            "execution_id", "runtime_domain", "record_type", "record_key", name="uq_runtime_persistence_record_identity"
        ),
        CheckConstraint(
            "runtime_domain IN ('storage','processing','chunk','knowledge_publication','knowledge_index',"
            "'knowledge_lifecycle','knowledge_fts','embedding_runtime','vector_index_runtime',"
            "'semantic_search_runtime','hybrid_search_runtime','workflow_runtime','assistant_runtime',"
            "'assistant_retrieval_runtime','assistant_retrieval_execution_readiness',"
            "'assistant_search_execution','assistant_context_builder','assistant_prompt_assembly',"
            "'assistant_llm_gateway','assistant_llm_execution','assistant_citation_verification',"
            "'assistant_response','conversation_runtime','chat_runtime','enterprise_search',"
            "'runtime_persistence')",
            name="ck_runtime_persistence_records_domain",
        ),
        CheckConstraint(
            "persistence_status IN ('persisted','failed','skipped')", name="ck_runtime_persistence_records_status"
        ),
        Index("ix_runtime_persistence_execution", "execution_id"),
        Index("ix_runtime_persistence_domain_status", "runtime_domain", "persistence_status"),
        Index("ix_runtime_persistence_artifact", "artifact_id"),
        Index("ix_runtime_persistence_correlation", "correlation_id"),
        {"schema": "runtime"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    execution_id: Mapped[str] = mapped_column(String(255), nullable=False)
    runtime_domain: Mapped[str] = mapped_column(String(64), nullable=False)
    record_type: Mapped[str] = mapped_column(String(128), nullable=False)
    record_key: Mapped[str] = mapped_column(String(512), nullable=False)
    artifact_id: Mapped[str | None] = mapped_column(String(128))
    processing_session_id: Mapped[str | None] = mapped_column(String(255))
    correlation_id: Mapped[str | None] = mapped_column(String(255))
    provider: Mapped[str | None] = mapped_column(String(128))
    execution_status: Mapped[str | None] = mapped_column(String(64))
    content_hash: Mapped[str | None] = mapped_column(String(128))
    summary: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"), nullable=False)
    validation: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"), nullable=False)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"), nullable=False)
    persistence_status: Mapped[str] = mapped_column(String(32), server_default="persisted", nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    persisted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
