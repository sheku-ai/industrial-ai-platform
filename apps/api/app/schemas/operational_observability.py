from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class OperationalBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class RuntimeComponentCreate(BaseModel):
    scope: str = Field(pattern="^(platform|organization)$")
    organization_id: uuid.UUID | None = None
    component_code: str = Field(min_length=1, max_length=128)
    component_type: str
    instance_id: str = Field(min_length=1, max_length=255)
    display_name: str = Field(min_length=1, max_length=255)
    runtime_version: str | None = None
    status: str = "running"
    health_status: str = "healthy"
    readiness_status: str = "ready"
    capabilities: list[Any] = Field(default_factory=list)
    configuration_reference: dict[str, Any] = Field(default_factory=dict)
    last_started_at: datetime | None = None
    last_heartbeat_at: datetime | None = None
    last_success_at: datetime | None = None
    last_failure_at: datetime | None = None
    observed_at: datetime | None = None


class RuntimeComponentRead(OperationalBase):
    id: uuid.UUID
    organization_id: uuid.UUID | None
    scope: str
    component_code: str
    component_type: str
    instance_id: str
    display_name: str
    runtime_version: str | None
    status: str
    health_status: str
    readiness_status: str
    capabilities: list[Any]
    configuration_reference: dict[str, Any]
    last_started_at: datetime | None
    last_heartbeat_at: datetime | None
    last_success_at: datetime | None
    last_failure_at: datetime | None
    observed_at: datetime
    created_at: datetime
    updated_at: datetime


class RuntimeObservationCreate(BaseModel):
    observation_type: str
    severity: str = "info"
    status: str = "normal"
    summary: str = Field(min_length=1)
    observed_value: str | None = None
    expected_value: str | None = None
    unit: str | None = None
    source_runtime: str | None = None
    source_entity_type: str | None = None
    source_entity_id: str | None = None
    evidence_payload: dict[str, Any] = Field(default_factory=dict)
    observed_at: datetime | None = None
    expires_at: datetime | None = None


class RuntimeObservationRead(OperationalBase):
    id: uuid.UUID
    organization_id: uuid.UUID | None
    scope: str
    component_id: uuid.UUID
    observation_type: str
    severity: str
    status: str
    summary: str
    observed_value: str | None
    expected_value: str | None
    unit: str | None
    source_runtime: str | None
    source_entity_type: str | None
    source_entity_id: str | None
    evidence_payload: dict[str, Any]
    evidence_hash: str
    observed_at: datetime
    expires_at: datetime | None
    created_at: datetime


class OperationalExecutionCreate(BaseModel):
    scope: str = Field(pattern="^(platform|organization)$")
    organization_id: uuid.UUID | None = None
    component_id: uuid.UUID | None = None
    execution_type: str
    execution_reference: str | None = None
    idempotency_key: str = Field(min_length=1, max_length=255)
    status: str = "pending"
    attempt_number: int = Field(default=1, ge=1)
    max_attempts: int = Field(default=3, ge=1)
    input_payload: dict[str, Any] = Field(default_factory=dict)
    correlation_id: str | None = Field(default=None, max_length=128, exclude=True)


class OperationalExecutionRead(OperationalBase):
    id: uuid.UUID
    organization_id: uuid.UUID | None
    scope: str
    component_id: uuid.UUID | None
    execution_type: str
    execution_reference: str | None
    correlation_id: str
    idempotency_key: str
    status: str
    attempt_number: int
    max_attempts: int
    requested_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    last_progress_at: datetime | None
    input_hash: str
    result_hash: str | None
    failure_code: str | None
    failure_summary: str | None
    created_at: datetime
    updated_at: datetime


class RuntimeResultRequest(BaseModel):
    result_payload: dict[str, Any] = Field(default_factory=dict)
    failure_code: str | None = None
    failure_summary: str | None = None


class BoundedRetryCreate(BaseModel):
    attempt_number: int = Field(ge=1)
    retry_policy_code: str = Field(min_length=1, max_length=128)
    status: str = "scheduled"
    delay_seconds: int = Field(default=0, ge=0)
    failure_code: str | None = None
    failure_summary: str | None = None
    retryable: bool = True
    decision_reason: str | None = None
    evidence_payload: dict[str, Any] = Field(default_factory=dict)


class BoundedRetryRead(OperationalBase):
    id: uuid.UUID
    operational_execution_id: uuid.UUID
    attempt_number: int
    retry_policy_code: str
    status: str
    scheduled_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    delay_seconds: int
    failure_code: str | None
    failure_summary: str | None
    retryable: bool
    decision_reason: str | None
    evidence_payload: dict[str, Any]
    created_at: datetime


class OperationalIncidentCreate(BaseModel):
    scope: str = Field(pattern="^(platform|organization)$")
    organization_id: uuid.UUID | None = None
    incident_code: str = Field(min_length=1, max_length=128)
    incident_type: str
    severity: str
    component_id: uuid.UUID | None = None
    operational_execution_id: uuid.UUID | None = None
    source_entity_type: str | None = None
    source_entity_id: str | None = None
    summary: str = Field(min_length=1)
    details: dict[str, Any] = Field(default_factory=dict)


class OperationalIncidentRead(OperationalBase):
    id: uuid.UUID
    organization_id: uuid.UUID | None
    scope: str
    incident_code: str
    incident_type: str
    severity: str
    status: str
    component_id: uuid.UUID | None
    operational_execution_id: uuid.UUID | None
    source_entity_type: str | None
    source_entity_id: str | None
    summary: str
    details: dict[str, Any]
    first_observed_at: datetime
    last_observed_at: datetime
    acknowledged_at: datetime | None
    resolved_at: datetime | None
    acknowledged_by: str | None
    resolved_by: str | None
    resolution_code: str | None
    resolution_summary: str | None
    occurrence_count: int
    evidence_hash: str
    created_at: datetime
    updated_at: datetime


class IncidentTransitionRequest(BaseModel):
    actor_reference: str | None = None
    resolution_code: str | None = None
    resolution_summary: str | None = None
    evidence_payload: dict[str, Any] = Field(default_factory=dict)


class FailureRecoveryActionCreate(BaseModel):
    action_type: str
    requested_by: str | None = None
    approved_by: str | None = None
    operational_execution_id: uuid.UUID | None = None
    evidence_payload: dict[str, Any] = Field(default_factory=dict)


class FailureRecoveryActionRead(OperationalBase):
    id: uuid.UUID
    incident_id: uuid.UUID
    operational_execution_id: uuid.UUID | None
    action_type: str
    status: str
    requested_by: str | None
    approved_by: str | None
    requested_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    input_hash: str
    result_hash: str | None
    failure_code: str | None
    failure_summary: str | None
    evidence_payload: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class OperationalEvidenceRead(OperationalBase):
    id: uuid.UUID
    organization_id: uuid.UUID | None
    scope: str
    evidence_type: str
    source_entity_type: str
    source_entity_id: str
    status: str
    evidence_payload: dict[str, Any]
    evidence_hash: str
    observed_at: datetime
    expires_at: datetime | None
    created_at: datetime


class OperationalDiagnostic(BaseModel):
    diagnostic_code: str
    domain: str
    severity: str
    status: str
    summary: str
    affected_component: str | None = None
    affected_execution: str | None = None
    evidence_reference: str | None = None
    observed_at: datetime | None = None
    recommended_action: str | None = None


class OperationalReadinessGate(BaseModel):
    gate_code: str
    status: str
    summary: str
    evidence_reference: str | None = None
    blocking_issues: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[dict[str, Any]] = Field(default_factory=list)


class OperationalReadinessResponse(BaseModel):
    scope: str
    organization_id: uuid.UUID | None
    status: str
    operational_ready: bool
    gates: list[OperationalReadinessGate]
    blocking_issues: list[dict[str, Any]]
    warnings: list[dict[str, Any]]
    diagnostics: list[OperationalDiagnostic]
    postgresql_source_of_truth: bool = True
    side_effects_performed: bool = False
    external_calls_performed: bool = False
    llm_used: bool = False
    qdrant_used: bool = False


class OperationalWorkspaceRuntimeResponse(BaseModel):
    runtime_name: str = "operational_observability_runtime"
    runtime_status: str
    operational_readiness: OperationalReadinessResponse
    component_summary: dict[str, Any] = Field(default_factory=dict)
    worker_summary: dict[str, Any] = Field(default_factory=dict)
    scheduler_summary: dict[str, Any] = Field(default_factory=dict)
    lease_summary: dict[str, Any] = Field(default_factory=dict)
    execution_summary: dict[str, Any] = Field(default_factory=dict)
    retry_summary: dict[str, Any] = Field(default_factory=dict)
    incident_summary: dict[str, Any] = Field(default_factory=dict)
    open_blockers: list[dict[str, Any]] = Field(default_factory=list)
    diagnostics: list[OperationalDiagnostic] = Field(default_factory=list)
    recent_recovery_actions: list[dict[str, Any]] = Field(default_factory=list)
    evidence_freshness: dict[str, Any] = Field(default_factory=dict)
    dashboard_runtime: dict[str, Any] = Field(default_factory=dict)
    health_runtime: dict[str, Any] = Field(default_factory=dict)
    warning_runtime: dict[str, Any] = Field(default_factory=dict)
    alert_runtime: dict[str, Any] = Field(default_factory=dict)
    next_actions: list[dict[str, Any]] = Field(default_factory=list)
    postgresql_source_of_truth: bool = True
    side_effects_performed: bool = False
    external_calls_performed: bool = False
    llm_used: bool = False
    qdrant_used: bool = False
