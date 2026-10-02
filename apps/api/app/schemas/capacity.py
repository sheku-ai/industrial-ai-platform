from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.readiness import AuthoritativeReadinessEvidence

CAPACITY_METRICS = (
    "concurrent_requests",
    "ingestion",
    "search",
    "assistant",
    "queue",
    "worker",
    "storage",
    "database",
)


class CapacityVector(BaseModel):
    concurrent_requests: float = Field(ge=0)
    ingestion: float = Field(ge=0)
    search: float = Field(ge=0)
    assistant: float = Field(ge=0)
    queue: float = Field(ge=0)
    worker: float = Field(ge=0)
    storage: float = Field(ge=0)
    database: float = Field(ge=0)


class CapacityProfileCreate(BaseModel):
    scope: str = Field(pattern="^(platform|organization)$")
    organization_id: uuid.UUID | None = None
    profile_code: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    version: str = Field(min_length=1, max_length=64)
    status: str = Field(default="active", pattern="^(draft|active|inactive|retired)$")
    configured_capacity: CapacityVector
    target_capacity: CapacityVector
    thresholds: dict[str, Any] = Field(default_factory=dict)
    evidence_max_age_hours: int = Field(default=168, gt=0)
    created_by: str | None = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def validate_scope(self) -> CapacityProfileCreate:
        if self.scope == "organization" and self.organization_id is None:
            raise ValueError("organization_id is required for organization scope")
        if self.scope == "platform" and self.organization_id is not None:
            raise ValueError("organization_id must be omitted for platform scope")
        return self


class CapacityProfileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    organization_id: uuid.UUID | None
    scope: str
    profile_code: str
    name: str
    description: str | None
    version: str
    status: str
    configured_capacity: CapacityVector
    target_capacity: CapacityVector
    thresholds: dict[str, Any]
    evidence_max_age_hours: int
    created_by: str | None
    activated_at: datetime | None
    created_at: datetime
    updated_at: datetime


class LoadTestExecutionCreate(BaseModel):
    scope: str = Field(pattern="^(platform|organization)$")
    organization_id: uuid.UUID | None = None
    profile_id: uuid.UUID
    execution_name: str = Field(min_length=1, max_length=255)
    scenario: str = Field(min_length=1, max_length=128)
    concurrent_requests: int = Field(gt=0)
    duration_seconds: int = Field(gt=0)
    requests_planned: int = Field(gt=0)
    idempotency_key: str = Field(min_length=1, max_length=255)
    requested_by: str | None = Field(default=None, max_length=255)
    execution_metadata: dict[str, Any] = Field(default_factory=dict)
    correlation_id: str | None = Field(default=None, max_length=128, exclude=True)

    @model_validator(mode="after")
    def validate_scope(self) -> LoadTestExecutionCreate:
        if self.scope == "organization" and self.organization_id is None:
            raise ValueError("organization_id is required for organization scope")
        if self.scope == "platform" and self.organization_id is not None:
            raise ValueError("organization_id must be omitted for platform scope")
        return self


class LoadTestExecutionComplete(BaseModel):
    status: str = Field(default="completed", pattern="^(completed|failed|blocked|cancelled)$")
    requests_completed: int = Field(ge=0)
    requests_failed: int = Field(ge=0)
    result_metadata: dict[str, Any] = Field(default_factory=dict)


class LoadTestExecutionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    profile_id: uuid.UUID
    organization_id: uuid.UUID | None
    scope: str
    execution_name: str
    scenario: str
    status: str
    concurrent_requests: int
    duration_seconds: int
    requests_planned: int
    requests_completed: int
    requests_failed: int
    idempotency_key: str
    input_hash: str
    result_hash: str | None
    correlation_id: str
    requested_by: str | None
    requested_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    execution_metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class LoadTestResultCreate(BaseModel):
    metric_code: str = Field(pattern="^(concurrent_requests|ingestion|search|assistant|queue|worker|storage|database)$")
    component: str = Field(min_length=1, max_length=128)
    observed_value: float = Field(ge=0)
    target_value: float = Field(ge=0)
    unit: str = Field(min_length=1, max_length=64)
    sample_count: int = Field(gt=0)
    percentile_values: dict[str, Any] = Field(default_factory=dict)
    details: dict[str, Any] = Field(default_factory=dict)
    observed_at: datetime


class LoadTestResultRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    load_test_execution_id: uuid.UUID
    metric_code: str
    component: str
    observed_value: float
    target_value: float
    unit: str
    passed: bool
    sample_count: int
    percentile_values: dict[str, Any]
    details: dict[str, Any]
    observed_at: datetime
    recorded_at: datetime


class CapacityEvaluationRequest(BaseModel):
    scope: str = Field(pattern="^(platform|organization)$")
    organization_id: uuid.UUID | None = None
    profile_id: uuid.UUID
    load_test_execution_id: uuid.UUID
    idempotency_key: str = Field(min_length=1, max_length=255)
    requested_by: str | None = Field(default=None, max_length=255)
    correlation_id: str | None = Field(default=None, max_length=128, exclude=True)

    @model_validator(mode="after")
    def validate_scope(self) -> CapacityEvaluationRequest:
        if self.scope == "organization" and self.organization_id is None:
            raise ValueError("organization_id is required for organization scope")
        if self.scope == "platform" and self.organization_id is not None:
            raise ValueError("organization_id must be omitted for platform scope")
        return self


class CapacityFindingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    evaluation_id: uuid.UUID
    finding_code: str
    finding_type: str
    severity: str
    status: str
    component: str
    summary: str
    details: dict[str, Any]
    resolved_by: str | None
    resolved_at: datetime | None
    created_at: datetime


class CapacityRecommendationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    evaluation_id: uuid.UUID
    finding_id: uuid.UUID | None
    recommendation_code: str
    priority: str
    status: str
    component: str
    summary: str
    recommended_action: str
    details: dict[str, Any]
    created_at: datetime


class CapacityEvidenceCreate(BaseModel):
    evidence_code: str = Field(min_length=1, max_length=128)
    evidence_type: str = Field(min_length=1, max_length=64)
    source_runtime: str = Field(min_length=1, max_length=128)
    source_reference: str | None = Field(default=None, max_length=255)
    evidence_payload: dict[str, Any]
    observed_at: datetime


class CapacityEvidenceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    evaluation_id: uuid.UUID
    load_test_execution_id: uuid.UUID | None
    evidence_code: str
    evidence_type: str
    source_runtime: str
    source_reference: str | None
    evidence_payload: dict[str, Any]
    evidence_hash: str
    observed_at: datetime
    recorded_at: datetime


class CapacityTrendRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    evaluation_id: uuid.UUID
    organization_id: uuid.UUID | None
    scope: str
    metric_code: str
    observed_value: float
    configured_value: float
    target_value: float
    utilization_ratio: float
    status: str
    captured_at: datetime


class CapacityGateResult(BaseModel):
    gate_code: str
    status: str
    evidence_reference: str | None = None
    summary: str


class CapacityAcceptanceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    evaluation_id: uuid.UUID
    profile_id: uuid.UUID
    organization_id: uuid.UUID | None
    scope: str
    status: str
    gate_results: list[CapacityGateResult]
    blocker_count: int
    recommendation_count: int
    evidence_age_seconds: int | None
    result_hash: str
    accepted_by: str | None
    accepted_at: datetime


class CapacityEvaluationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    profile_id: uuid.UUID
    load_test_execution_id: uuid.UUID | None
    organization_id: uuid.UUID | None
    scope: str
    status: str
    configured_capacity: CapacityVector
    observed_capacity: CapacityVector
    target_capacity: CapacityVector
    utilization: CapacityVector
    concurrent_requests_supported: float
    ingestion_capacity: float
    search_capacity: float
    assistant_capacity: float
    queue_capacity: float
    worker_capacity: float
    storage_capacity: float
    database_capacity: float
    bottlenecks: list[dict[str, Any]]
    blockers: list[dict[str, Any]]
    warnings: list[dict[str, Any]]
    recommendations: list[dict[str, Any]]
    next_actions: list[dict[str, Any]]
    idempotency_key: str
    input_hash: str
    result_hash: str
    correlation_id: str
    requested_by: str | None
    evidence_observed_at: datetime | None
    evidence_age_seconds: int | None
    evaluated_at: datetime
    created_at: datetime

    @model_validator(mode="before")
    @classmethod
    def expose_capacity_scalars(cls, value: Any) -> Any:
        if hasattr(value, "observed_capacity"):
            data = {column.name: getattr(value, column.name) for column in value.__table__.columns}
        elif isinstance(value, dict):
            data = dict(value)
        else:
            return value
        observed = data.get("observed_capacity") or {}
        data.update(
            concurrent_requests_supported=observed.get("concurrent_requests", 0),
            ingestion_capacity=observed.get("ingestion", 0),
            search_capacity=observed.get("search", 0),
            assistant_capacity=observed.get("assistant", 0),
            queue_capacity=observed.get("queue", 0),
            worker_capacity=observed.get("worker", 0),
            storage_capacity=observed.get("storage", 0),
            database_capacity=observed.get("database", 0),
        )
        return data


class CapacityReadinessResponse(BaseModel):
    evidence_contract: AuthoritativeReadinessEvidence
    status: str
    reason: str
    scope: str
    organization_id: uuid.UUID | None
    active_profile: CapacityProfileRead | None
    latest_evaluation: CapacityEvaluationRead | None
    latest_acceptance: CapacityAcceptanceRead | None
    configured_capacity: CapacityVector | None
    observed_capacity: CapacityVector | None
    target_capacity: CapacityVector | None
    utilization: CapacityVector | None
    bottlenecks: list[dict[str, Any]]
    blockers: list[dict[str, Any]]
    warnings: list[dict[str, Any]]
    recommendations: list[dict[str, Any]]
    next_actions: list[dict[str, Any]]
    blocker_count: int
    recommendation_count: int
    evidence_age_seconds: int | None
    evidence_age_hours: float | None
    gate_results: list[CapacityGateResult]
    evaluation_timestamp: datetime
    expires_at: datetime | None = None
    contract_version: str
    runtime_version: str
    postgresql_source_of_truth: bool = True
    llm_used: bool = False
    qdrant_used: bool = False


class CapacityLatestResponse(BaseModel):
    found: bool
    evaluation: CapacityEvaluationRead | None = None
    acceptance: CapacityAcceptanceRead | None = None
    load_test_execution: LoadTestExecutionRead | None = None
    results: list[LoadTestResultRead] = Field(default_factory=list)
    postgresql_source_of_truth: bool = True
