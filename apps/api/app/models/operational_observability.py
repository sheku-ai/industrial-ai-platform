from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
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


class RuntimeComponent(Base):
    __tablename__ = "operational_components"
    __table_args__ = (
        UniqueConstraint(
            "scope",
            "organization_id",
            "component_code",
            "instance_id",
            name="uq_runtime_operational_components_identity",
        ),
        CheckConstraint("scope IN ('platform','organization')", name="ck_runtime_operational_components_scope"),
        CheckConstraint(
            "(scope = 'platform' AND organization_id IS NULL) OR "
            "(scope = 'organization' AND organization_id IS NOT NULL)",
            name="ck_runtime_operational_components_scope_org",
        ),
        CheckConstraint(
            "component_type IN ('api','worker','scheduler','monitor','reconciler','database','object_storage',"
            "'queue','portal','external_service','other')",
            name="ck_runtime_operational_components_type",
        ),
        CheckConstraint(
            "status IN ('unknown','starting','running','degraded','stopping','stopped','failed','unavailable')",
            name="ck_runtime_operational_components_status",
        ),
        CheckConstraint(
            "health_status IN ('unknown','healthy','degraded','unhealthy')",
            name="ck_runtime_operational_components_health",
        ),
        CheckConstraint(
            "readiness_status IN ('unknown','ready','not_ready','blocked')",
            name="ck_runtime_operational_components_readiness",
        ),
        Index("ix_runtime_operational_components_scope", "scope", "organization_id", "status"),
        Index("ix_runtime_operational_components_type", "component_type", "health_status", "readiness_status"),
        Index("ix_runtime_operational_components_observed", "observed_at"),
        {"schema": "runtime"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.organizations.id"), nullable=True
    )
    scope: Mapped[str] = mapped_column(String(32), nullable=False)
    component_code: Mapped[str] = mapped_column(String(128), nullable=False)
    component_type: Mapped[str] = mapped_column(String(64), nullable=False)
    instance_id: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    runtime_version: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), server_default="unknown", nullable=False)
    health_status: Mapped[str] = mapped_column(String(32), server_default="unknown", nullable=False)
    readiness_status: Mapped[str] = mapped_column(String(32), server_default="unknown", nullable=False)
    capabilities: Mapped[list[Any]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"), nullable=False)
    configuration_reference: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb"), nullable=False
    )
    last_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_failure_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class RuntimeObservation(Base):
    __tablename__ = "operational_observations"
    __table_args__ = (
        UniqueConstraint(
            "component_id", "observation_type", "evidence_hash", name="uq_runtime_operational_observation"
        ),
        CheckConstraint("scope IN ('platform','organization')", name="ck_runtime_operational_observations_scope"),
        CheckConstraint(
            "observation_type IN ('heartbeat','health','readiness','throughput','latency','queue_depth','error_rate',"
            "'retry','lease','execution','storage','database','dependency','capacity','custom')",
            name="ck_runtime_operational_observations_type",
        ),
        CheckConstraint(
            "severity IN ('info','warning','error','critical')", name="ck_runtime_operational_observations_severity"
        ),
        CheckConstraint(
            "status IN ('normal','degraded','failed','blocked','unknown')",
            name="ck_runtime_operational_observations_status",
        ),
        CheckConstraint(
            "expires_at IS NULL OR expires_at > observed_at", name="ck_runtime_operational_observations_expiry"
        ),
        Index("ix_runtime_operational_observations_scope", "scope", "organization_id", "status"),
        Index("ix_runtime_operational_observations_component", "component_id", "observed_at"),
        Index("ix_runtime_operational_observations_observed", "observed_at", "expires_at"),
        {"schema": "runtime"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("core.organizations.id"))
    scope: Mapped[str] = mapped_column(String(32), nullable=False)
    component_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("runtime.operational_components.id", ondelete="CASCADE"), nullable=False
    )
    observation_type: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(32), server_default="info", nullable=False)
    status: Mapped[str] = mapped_column(String(32), server_default="normal", nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    observed_value: Mapped[str | None] = mapped_column(String(255))
    expected_value: Mapped[str | None] = mapped_column(String(255))
    unit: Mapped[str | None] = mapped_column(String(64))
    source_runtime: Mapped[str | None] = mapped_column(String(128))
    source_entity_type: Mapped[str | None] = mapped_column(String(128))
    source_entity_id: Mapped[str | None] = mapped_column(String(255))
    evidence_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"), nullable=False)
    evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class OperationalExecution(Base):
    __tablename__ = "operational_executions"
    __table_args__ = (
        UniqueConstraint(
            "scope",
            "organization_id",
            "execution_type",
            "idempotency_key",
            name="uq_runtime_operational_executions_idempotency",
        ),
        CheckConstraint("scope IN ('platform','organization')", name="ck_runtime_operational_executions_scope"),
        CheckConstraint(
            "execution_type IN ('scheduled_job','worker_job','reconciliation','monitoring_check','maintenance_action',"
            "'recovery_action','manual_operation','other')",
            name="ck_runtime_operational_executions_type",
        ),
        CheckConstraint(
            "status IN ('pending','claimed','running','completed','failed','blocked','cancelled','abandoned')",
            name="ck_runtime_operational_executions_status",
        ),
        CheckConstraint("attempt_number > 0", name="ck_runtime_operational_executions_attempt"),
        CheckConstraint("max_attempts > 0", name="ck_runtime_operational_executions_max_attempts"),
        CheckConstraint("length(input_hash) = 64", name="ck_runtime_operational_executions_input_hash"),
        CheckConstraint(
            "result_hash IS NULL OR length(result_hash) = 64", name="ck_runtime_operational_executions_result_hash"
        ),
        Index("ix_runtime_operational_executions_scope", "scope", "organization_id", "status"),
        Index("ix_runtime_operational_executions_component", "component_id", "status"),
        Index("ix_runtime_operational_executions_requested", "requested_at", "status"),
        Index("ix_runtime_operational_executions_correlation", "correlation_id"),
        {"schema": "runtime"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("core.organizations.id"))
    scope: Mapped[str] = mapped_column(String(32), nullable=False)
    component_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("runtime.operational_components.id", ondelete="SET NULL")
    )
    execution_type: Mapped[str] = mapped_column(String(64), nullable=False)
    execution_reference: Mapped[str | None] = mapped_column(String(255))
    correlation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), server_default="pending", nullable=False)
    attempt_number: Mapped[int] = mapped_column(Integer, server_default="1", nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, server_default="3", nullable=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_progress_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    result_hash: Mapped[str | None] = mapped_column(String(64))
    failure_code: Mapped[str | None] = mapped_column(String(128))
    failure_summary: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class BoundedRetryAttempt(Base):
    __tablename__ = "operational_retry_attempts"
    __table_args__ = (
        UniqueConstraint("operational_execution_id", "attempt_number", name="uq_runtime_operational_retry_attempt"),
        CheckConstraint(
            "status IN ('scheduled','running','succeeded','failed','skipped','exhausted','cancelled')",
            name="ck_runtime_operational_retry_attempts_status",
        ),
        CheckConstraint("attempt_number > 0", name="ck_runtime_operational_retry_attempts_number"),
        CheckConstraint("delay_seconds >= 0", name="ck_runtime_operational_retry_attempts_delay"),
        Index("ix_runtime_operational_retry_attempts_execution", "operational_execution_id", "status"),
        Index("ix_runtime_operational_retry_attempts_scheduled", "scheduled_at", "status"),
        {"schema": "runtime"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    operational_execution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("runtime.operational_executions.id", ondelete="CASCADE"), nullable=False
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    retry_policy_code: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), server_default="scheduled", nullable=False)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delay_seconds: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    failure_code: Mapped[str | None] = mapped_column(String(128))
    failure_summary: Mapped[str | None] = mapped_column(Text)
    retryable: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), nullable=False)
    decision_reason: Mapped[str | None] = mapped_column(Text)
    evidence_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class OperationalIncident(Base):
    __tablename__ = "operational_incidents"
    __table_args__ = (
        UniqueConstraint(
            "scope",
            "organization_id",
            "incident_code",
            "source_entity_type",
            "source_entity_id",
            "status",
            name="uq_runtime_operational_incident_open_identity",
        ),
        CheckConstraint("scope IN ('platform','organization')", name="ck_runtime_operational_incidents_scope"),
        CheckConstraint(
            "severity IN ('info','warning','error','critical')", name="ck_runtime_operational_incidents_severity"
        ),
        CheckConstraint(
            "status IN ('open','acknowledged','recovering','resolved','suppressed')",
            name="ck_runtime_operational_incidents_status",
        ),
        CheckConstraint("occurrence_count > 0", name="ck_runtime_operational_incidents_occurrence_count"),
        Index("ix_runtime_operational_incidents_scope", "scope", "organization_id", "status"),
        Index("ix_runtime_operational_incidents_severity", "severity", "status"),
        Index("ix_runtime_operational_incidents_component", "component_id", "status"),
        Index("ix_runtime_operational_incidents_open", "status", "severity", "last_observed_at"),
        {"schema": "runtime"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("core.organizations.id"))
    scope: Mapped[str] = mapped_column(String(32), nullable=False)
    incident_code: Mapped[str] = mapped_column(String(128), nullable=False)
    incident_type: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), server_default="open", nullable=False)
    component_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("runtime.operational_components.id", ondelete="SET NULL")
    )
    operational_execution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("runtime.operational_executions.id", ondelete="SET NULL")
    )
    source_entity_type: Mapped[str | None] = mapped_column(String(128))
    source_entity_id: Mapped[str | None] = mapped_column(String(255))
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"), nullable=False)
    first_observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledged_by: Mapped[str | None] = mapped_column(String(255))
    resolved_by: Mapped[str | None] = mapped_column(String(255))
    resolution_code: Mapped[str | None] = mapped_column(String(128))
    resolution_summary: Mapped[str | None] = mapped_column(Text)
    occurrence_count: Mapped[int] = mapped_column(Integer, server_default="1", nullable=False)
    evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class FailureRecoveryAction(Base):
    __tablename__ = "operational_recovery_actions"
    __table_args__ = (
        UniqueConstraint("incident_id", "input_hash", "action_type", name="uq_runtime_operational_recovery_action"),
        CheckConstraint(
            "action_type IN ('retry_execution','release_lease','reconcile_state','restart_component_request',"
            "'disable_schedule','enable_schedule','cancel_execution','mark_abandoned','manual_recovery','external_recovery')",
            name="ck_runtime_operational_recovery_actions_type",
        ),
        CheckConstraint(
            "status IN ('requested','approved','running','completed','failed','blocked','cancelled')",
            name="ck_runtime_operational_recovery_actions_status",
        ),
        CheckConstraint("length(input_hash) = 64", name="ck_runtime_operational_recovery_actions_input_hash"),
        CheckConstraint(
            "result_hash IS NULL OR length(result_hash) = 64",
            name="ck_runtime_operational_recovery_actions_result_hash",
        ),
        Index("ix_runtime_operational_recovery_actions_incident", "incident_id", "status"),
        Index("ix_runtime_operational_recovery_actions_status", "status", "requested_at"),
        {"schema": "runtime"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    incident_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("runtime.operational_incidents.id", ondelete="CASCADE"), nullable=False
    )
    operational_execution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("runtime.operational_executions.id", ondelete="SET NULL")
    )
    action_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), server_default="requested", nullable=False)
    requested_by: Mapped[str | None] = mapped_column(String(255))
    approved_by: Mapped[str | None] = mapped_column(String(255))
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    result_hash: Mapped[str | None] = mapped_column(String(64))
    failure_code: Mapped[str | None] = mapped_column(String(128))
    failure_summary: Mapped[str | None] = mapped_column(Text)
    evidence_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class OperationalEvidence(Base):
    __tablename__ = "operational_evidence"
    __table_args__ = (
        UniqueConstraint(
            "scope",
            "organization_id",
            "evidence_type",
            "source_entity_type",
            "source_entity_id",
            "evidence_hash",
            name="uq_runtime_operational_evidence_identity",
        ),
        CheckConstraint("scope IN ('platform','organization')", name="ck_runtime_operational_evidence_scope"),
        CheckConstraint(
            "status IN ('passed','failed','blocked','not_evaluated')", name="ck_runtime_operational_evidence_status"
        ),
        CheckConstraint(
            "expires_at IS NULL OR expires_at > observed_at", name="ck_runtime_operational_evidence_expiry"
        ),
        Index("ix_runtime_operational_evidence_scope", "scope", "organization_id", "status"),
        Index("ix_runtime_operational_evidence_type", "evidence_type", "observed_at"),
        {"schema": "runtime"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("core.organizations.id"))
    scope: Mapped[str] = mapped_column(String(32), nullable=False)
    evidence_type: Mapped[str] = mapped_column(String(128), nullable=False)
    source_entity_type: Mapped[str] = mapped_column(String(128), nullable=False)
    source_entity_id: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    evidence_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"), nullable=False)
    evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
