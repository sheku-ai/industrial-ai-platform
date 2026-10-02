from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.readiness import AuthoritativeReadinessEvidence
from app.schemas.release_governance import reject_secrets

Scope = Literal["platform", "organization"]
HealthStatus = Literal[
    "passed", "healthy", "degraded", "failed", "blocked", "not_evaluated", "expired", "stale", "interrupted"
]


class ScopedInput(BaseModel):
    scope: Scope = "platform"
    organization_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def validate_scope(self) -> ScopedInput:
        if self.scope == "platform" and self.organization_id is not None:
            raise ValueError("organization_id must be omitted for platform scope")
        if self.scope == "organization" and self.organization_id is None:
            raise ValueError("organization_id is required for organization scope")
        return self


class ObservabilityProfileCreate(ScopedInput):
    profile_code: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    version: str = Field(min_length=1, max_length=64)
    status: Literal["draft", "active", "inactive", "retired"] = "active"
    evidence_max_age_seconds: int = Field(default=3600, gt=0)
    heartbeat_max_age_seconds: int = Field(default=300, gt=0)
    minimum_availability_percentage: float = Field(default=99.0, ge=0, le=100)
    minimum_signal_coverage_percentage: float = Field(default=100.0, ge=0, le=100)
    thresholds: dict[str, Any] = Field(default_factory=dict)
    contract_version: str = Field(default="observability.evidence.v1", min_length=1, max_length=64)
    runtime_version: str = Field(default="observability-runtime.v1", min_length=1, max_length=64)
    created_by: str | None = Field(default=None, max_length=255)

    _reject_threshold_secrets = field_validator("thresholds")(reject_secrets)


class ObservabilityProfileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    organization_id: uuid.UUID | None
    scope: str
    profile_code: str
    name: str
    description: str | None
    version: str
    status: str
    evidence_max_age_seconds: int
    heartbeat_max_age_seconds: int
    minimum_availability_percentage: float
    minimum_signal_coverage_percentage: float
    thresholds: dict[str, Any]
    contract_version: str
    runtime_version: str
    record_version: int
    created_by: str | None
    activated_at: datetime | None
    created_at: datetime
    updated_at: datetime


class HealthDomainCreate(ScopedInput):
    profile_id: uuid.UUID
    domain_code: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    version: str = Field(default="1", min_length=1, max_length=64)
    status: Literal["active", "inactive", "degraded", "failed", "unknown"] = "active"
    required_component_codes: list[str] = Field(default_factory=list)
    created_by: str | None = Field(default=None, max_length=255)


class HealthDomainRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    profile_id: uuid.UUID
    organization_id: uuid.UUID | None
    scope: str
    domain_code: str
    name: str
    description: str | None
    version: str
    status: str
    required_component_codes: list[str]
    record_version: int
    created_by: str | None
    created_at: datetime
    updated_at: datetime


class ObservedComponentCreate(ScopedInput):
    health_domain_id: uuid.UUID
    component_code: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=255)
    component_type: str = Field(min_length=1, max_length=128)
    version: str = Field(default="1", min_length=1, max_length=64)
    status: Literal["active", "inactive", "degraded", "failed", "unknown"] = "active"
    required: bool = True
    required_signal_codes: list[str] = Field(default_factory=list)
    component_metadata: dict[str, Any] = Field(default_factory=dict)
    created_by: str | None = Field(default=None, max_length=255)

    _reject_metadata_secrets = field_validator("component_metadata")(reject_secrets)


class ObservedComponentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    health_domain_id: uuid.UUID
    organization_id: uuid.UUID | None
    scope: str
    component_code: str
    name: str
    component_type: str
    version: str
    status: str
    required: bool
    required_signal_codes: list[str]
    component_metadata: dict[str, Any]
    record_version: int
    created_by: str | None
    created_at: datetime
    updated_at: datetime


class ObservedDependencyCreate(BaseModel):
    component_id: uuid.UUID
    dependency_code: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=255)
    dependency_type: str = Field(min_length=1, max_length=128)
    version: str = Field(default="1", min_length=1, max_length=64)
    status: Literal["active", "inactive", "degraded", "failed", "unknown"]
    critical: bool = True
    origin: str = Field(min_length=1, max_length=128)
    source: str = Field(min_length=1, max_length=255)
    details: dict[str, Any] = Field(default_factory=dict)
    observed_at: datetime
    expires_at: datetime | None = None

    _reject_details_secrets = field_validator("details")(reject_secrets)

    @model_validator(mode="after")
    def validate_expiration(self) -> ObservedDependencyCreate:
        if self.expires_at is not None and self.expires_at <= self.observed_at:
            raise ValueError("expires_at must be later than observed_at")
        return self


class ObservedDependencyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    component_id: uuid.UUID
    dependency_code: str
    name: str
    dependency_type: str
    version: str
    status: str
    critical: bool
    origin: str
    source: str
    details: dict[str, Any]
    observed_at: datetime
    expires_at: datetime | None
    record_version: int
    created_at: datetime
    updated_at: datetime


class ObservedSignalCreate(BaseModel):
    component_id: uuid.UUID
    signal_code: str = Field(min_length=1, max_length=128)
    signal_type: str = Field(min_length=1, max_length=128)
    status: Literal["healthy", "degraded", "failed", "unknown"]
    severity: Literal["info", "warning", "error", "critical"]
    value: float | None = None
    unit: str | None = Field(default=None, max_length=64)
    origin: str = Field(min_length=1, max_length=128)
    source: str = Field(min_length=1, max_length=255)
    contract_version: str = Field(default="observability.signal.v1", min_length=1, max_length=64)
    runtime_version: str = Field(default="observability-runtime.v1", min_length=1, max_length=64)
    evidence_payload: dict[str, Any]
    idempotency_key: str = Field(min_length=1, max_length=255)
    observed_at: datetime
    expires_at: datetime | None = None

    _reject_signal_secrets = field_validator("evidence_payload")(reject_secrets)

    @model_validator(mode="after")
    def validate_expiration(self) -> ObservedSignalCreate:
        if self.expires_at is not None and self.expires_at <= self.observed_at:
            raise ValueError("expires_at must be later than observed_at")
        return self


class ObservedSignalRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    component_id: uuid.UUID
    signal_code: str
    signal_type: str
    status: str
    severity: str
    value: float | None
    unit: str | None
    origin: str
    source: str
    contract_version: str
    runtime_version: str
    evidence_payload: dict[str, Any]
    idempotency_key: str
    input_hash: str
    observed_at: datetime
    expires_at: datetime | None
    record_version: int
    created_at: datetime
    updated_at: datetime


class HeartbeatCreate(BaseModel):
    component_id: uuid.UUID
    status: Literal["healthy", "degraded", "failed"]
    origin: str = Field(min_length=1, max_length=128)
    source: str = Field(min_length=1, max_length=255)
    contract_version: str = Field(default="observability.heartbeat.v1", min_length=1, max_length=64)
    runtime_version: str = Field(default="observability-runtime.v1", min_length=1, max_length=64)
    sequence: int | None = Field(default=None, ge=0)
    details: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str = Field(min_length=1, max_length=255)
    observed_at: datetime
    expires_at: datetime | None = None

    _reject_heartbeat_secrets = field_validator("details")(reject_secrets)

    @model_validator(mode="after")
    def validate_expiration(self) -> HeartbeatCreate:
        if self.expires_at is not None and self.expires_at <= self.observed_at:
            raise ValueError("expires_at must be later than observed_at")
        return self


class HeartbeatRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    component_id: uuid.UUID
    status: str
    origin: str
    source: str
    contract_version: str
    runtime_version: str
    sequence: int | None
    details: dict[str, Any]
    idempotency_key: str
    input_hash: str
    observed_at: datetime
    expires_at: datetime | None
    record_version: int
    created_at: datetime
    updated_at: datetime


class AvailabilityWindowCreate(BaseModel):
    component_id: uuid.UUID
    status: Literal["healthy", "degraded", "failed"]
    window_start: datetime
    window_end: datetime
    available_seconds: int = Field(ge=0)
    unavailable_seconds: int = Field(ge=0)
    origin: str = Field(min_length=1, max_length=128)
    source: str = Field(min_length=1, max_length=255)
    details: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str = Field(min_length=1, max_length=255)

    _reject_availability_secrets = field_validator("details")(reject_secrets)

    @model_validator(mode="after")
    def validate_window(self) -> AvailabilityWindowCreate:
        if self.window_end <= self.window_start:
            raise ValueError("window_end must be later than window_start")
        duration = int((self.window_end - self.window_start).total_seconds())
        if self.available_seconds + self.unavailable_seconds > duration:
            raise ValueError("availability seconds exceed window duration")
        return self


class AvailabilityWindowRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    component_id: uuid.UUID
    status: str
    window_start: datetime
    window_end: datetime
    available_seconds: int
    unavailable_seconds: int
    availability_percentage: float
    origin: str
    source: str
    details: dict[str, Any]
    idempotency_key: str
    input_hash: str
    record_version: int
    created_at: datetime
    updated_at: datetime


class HealthEvaluationRequest(ScopedInput):
    profile_id: uuid.UUID
    idempotency_key: str = Field(min_length=1, max_length=255)
    requested_by: str | None = Field(default=None, max_length=255)
    correlation_id: str | None = Field(default=None, max_length=128, exclude=True)


class HealthEvaluationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    profile_id: uuid.UUID
    organization_id: uuid.UUID | None
    scope: str
    overall_health: str
    availability_status: str
    heartbeat_status: str
    signal_status: str
    dependency_status: str
    coverage_status: str
    freshness_status: str
    component_status: str
    acceptance_status: str
    availability_percentage: float
    signal_coverage_percentage: float
    evidence_age_seconds: int | None
    blockers: list[dict[str, Any]]
    warnings: list[dict[str, Any]]
    recommendations: list[dict[str, Any]]
    next_actions: list[dict[str, Any]]
    idempotency_key: str
    input_hash: str
    result_hash: str
    correlation_id: str
    contract_version: str
    runtime_version: str
    record_version: int
    requested_by: str | None
    evaluated_at: datetime
    created_at: datetime
    updated_at: datetime


class HealthFindingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    evaluation_id: uuid.UUID
    component_id: uuid.UUID | None
    dependency_id: uuid.UUID | None
    finding_code: str
    finding_type: str
    severity: str
    status: str
    summary: str
    details: dict[str, Any]
    record_version: int
    created_at: datetime
    updated_at: datetime


class HealthEvidenceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    evaluation_id: uuid.UUID
    origin: str
    source: str
    contract_version: str
    runtime_version: str
    evaluation_timestamp: datetime
    expires_at: datetime
    component_ids: list[str]
    dependency_ids: list[str]
    heartbeat_ids: list[str]
    signal_ids: list[str]
    finding_ids: list[str]
    evidence_payload: dict[str, Any]
    evidence_hash: str
    record_version: int
    created_at: datetime
    updated_at: datetime


class ObservabilityGateResult(BaseModel):
    gate_code: str
    status: Literal["passed", "failed", "blocked", "not_evaluated"]
    summary: str
    evidence_reference: str | None = None


class HealthAcceptanceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    evaluation_id: uuid.UUID
    organization_id: uuid.UUID | None
    scope: str
    status: str
    gate_results: list[ObservabilityGateResult]
    blocker_count: int
    warning_count: int
    evidence_age_seconds: int | None
    result_hash: str
    record_version: int
    accepted_by: str | None
    accepted_at: datetime
    created_at: datetime
    updated_at: datetime


class HealthHistoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    evaluation_id: uuid.UUID
    organization_id: uuid.UUID | None
    scope: str
    overall_health: str
    availability_percentage: float
    signal_coverage_percentage: float
    evidence_age_seconds: int | None
    component_summary: dict[str, Any]
    dependency_summary: dict[str, Any]
    finding_summary: dict[str, Any]
    record_version: int
    captured_at: datetime
    created_at: datetime
    updated_at: datetime


class ObservabilityReadinessResponse(BaseModel):
    evidence_contract: AuthoritativeReadinessEvidence
    status: HealthStatus
    reason: str
    scope: str
    organization_id: uuid.UUID | None
    active_profile: ObservabilityProfileRead | None
    latest_evaluation: HealthEvaluationRead | None
    latest_acceptance: HealthAcceptanceRead | None
    overall_health: str
    availability_status: str
    heartbeat_status: str
    signal_status: str
    dependency_status: str
    coverage_status: str
    freshness_status: str
    component_status: str
    acceptance_status: str
    availability_percentage: float | None
    signal_coverage_percentage: float | None
    components: list[ObservedComponentRead]
    dependencies: list[ObservedDependencyRead]
    heartbeats: list[HeartbeatRead]
    findings: list[HealthFindingRead]
    blockers: list[dict[str, Any]]
    warnings: list[dict[str, Any]]
    recommendations: list[dict[str, Any]]
    next_actions: list[dict[str, Any]]
    evidence_age_seconds: int | None
    gate_results: list[ObservabilityGateResult]
    evaluated_at: datetime | None
    evaluation_timestamp: datetime
    expires_at: datetime | None = None
    contract_version: str = "platform.readiness.evidence.v1"
    runtime_version: str
    postgresql_source_of_truth: bool = True
    side_effects_performed: bool = False
    external_calls_performed: bool = False
    llm_used: bool = False
    qdrant_used: bool = False


class ObservabilityLatestResponse(BaseModel):
    found: bool
    evaluation: HealthEvaluationRead | None = None
    acceptance: HealthAcceptanceRead | None = None
    evidence: list[HealthEvidenceRead] = Field(default_factory=list)
    postgresql_source_of_truth: bool = True
