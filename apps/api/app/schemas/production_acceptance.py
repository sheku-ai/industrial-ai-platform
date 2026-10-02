from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.readiness import AuthoritativeReadinessEvidence


class ProductionAcceptanceRequest(BaseModel):
    scope: str = Field(default="platform", pattern="^(platform|organization)$")
    organization_id: uuid.UUID | None = None
    idempotency_key: str = Field(default="default", min_length=1, max_length=255)
    requested_by: str | None = Field(default=None, max_length=255)
    correlation_id: str | None = Field(default=None, max_length=128, exclude=True)


class ProductionBlocker(BaseModel):
    code: str
    gate_code: str | None = None
    domain: str | None = None
    message: str


class ProductionWarning(BaseModel):
    code: str
    gate_code: str | None = None
    domain: str | None = None
    message: str


class ProductionAcceptanceEvidence(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    run_id: uuid.UUID
    gate_result_id: uuid.UUID | None = None
    evidence_type: str
    source_runtime: str
    source_entity_type: str
    source_entity_id: str | None = None
    evidence_payload: dict[str, Any] = Field(default_factory=dict)
    evidence_hash: str
    observed_at: datetime
    created_at: datetime


class ProductionAcceptanceGateResult(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    run_id: uuid.UUID
    gate_code: str
    domain: str
    status: str
    mandatory: bool
    summary: str
    blocker_code: str | None = None
    warning_code: str | None = None
    evidence_type: str | None = None
    evidence_reference: str | None = None
    evidence_payload: dict[str, Any] = Field(default_factory=dict)
    duration_ms: int = 0
    components_evaluated: list[str] = Field(default_factory=list)
    evidence_origin: str = "runtime"
    evaluated_at: datetime
    created_at: datetime
    updated_at: datetime


class ProductionAcceptanceDomainSummary(BaseModel):
    domain: str
    status: str
    mandatory_total: int
    passed: int
    failed: int
    blocked: int
    not_evaluated: int
    blockers: list[ProductionBlocker] = Field(default_factory=list)
    warnings: list[ProductionWarning] = Field(default_factory=list)
    duration_ms: int = 0
    components_evaluated: list[str] = Field(default_factory=list)
    evidence_origins: list[str] = Field(default_factory=list)
    evidence_references: list[str] = Field(default_factory=list)
    evaluated_at: datetime | None = None
    evidence_age_seconds: int | None = None


class ProductionReadinessSummary(BaseModel):
    production_ready: bool
    release_candidate_eligible: bool
    status: str
    domain_summary: list[ProductionAcceptanceDomainSummary] = Field(default_factory=list)


class ConfigurationPreflightCheck(BaseModel):
    setting_code: str
    status: str
    source: str
    masked_value: str
    reason: str
    mandatory: bool
    configured: bool = False
    placeholder: bool = False
    evidence_origin: str = "settings.get_settings"
    evaluated_at: datetime


class ConfigurationPreflightResult(BaseModel):
    profile: str
    status: str
    checks: list[ConfigurationPreflightCheck]
    blockers: list[ProductionBlocker] = Field(default_factory=list)
    warnings: list[ProductionWarning] = Field(default_factory=list)
    postgresql_source_of_truth: bool = True
    secrets_exposed: bool = False
    evaluated_at: datetime
    duration_ms: int = 0


class ProductionAcceptanceRunResult(BaseModel):
    run_id: uuid.UUID
    correlation_id: str
    scope: str
    organization_id: uuid.UUID | None = None
    status: str
    reason: str
    functional_acceptance: ProductionAcceptanceDomainSummary
    operational_acceptance: ProductionAcceptanceDomainSummary
    security_acceptance: ProductionAcceptanceDomainSummary
    recovery_acceptance: ProductionAcceptanceDomainSummary
    deployment_acceptance: ProductionAcceptanceDomainSummary
    capacity_acceptance: ProductionAcceptanceDomainSummary
    portal_acceptance: ProductionAcceptanceDomainSummary
    production_ready: bool
    mandatory_gate_counts: dict[str, int]
    blockers: list[ProductionBlocker] = Field(default_factory=list)
    warnings: list[ProductionWarning] = Field(default_factory=list)
    recommendations: list[dict[str, Any]] = Field(default_factory=list)
    next_actions: list[dict[str, Any]] = Field(default_factory=list)
    evidence: list[ProductionAcceptanceEvidence] = Field(default_factory=list)
    evidence_contracts: list[AuthoritativeReadinessEvidence] = Field(default_factory=list)
    gate_results: list[ProductionAcceptanceGateResult] = Field(default_factory=list)
    contract_version: str
    requested_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    evaluated_at: datetime
    evaluation_timestamp: datetime
    expires_at: datetime | None = None
    runtime_version: str = "production-acceptance-runtime.v5"
    result_hash: str | None = None
    reused: bool = False
    configuration_preflight: ConfigurationPreflightResult | None = None


class ProductionAcceptanceLatestResponse(BaseModel):
    found: bool
    result: ProductionAcceptanceRunResult | None = None
    postgresql_source_of_truth: bool = True


class ProductionWorkspaceRuntimeResponse(BaseModel):
    runtime_name: str = "production_workspace_runtime"
    runtime_status: str
    current_status: str
    local_product_acceptance: dict[str, Any] = Field(default_factory=dict)
    product_acceptance: dict[str, Any] = Field(default_factory=dict)
    evidence_freshness: dict[str, Any] = Field(default_factory=dict)
    release_eligibility: dict[str, Any] = Field(default_factory=dict)
    release_candidate_eligible: bool
    production_ready: bool
    latest_run: ProductionAcceptanceRunResult | None = None
    domain_summary: list[ProductionAcceptanceDomainSummary] = Field(default_factory=list)
    mandatory_gate_counts: dict[str, int] = Field(default_factory=dict)
    blockers: list[ProductionBlocker] = Field(default_factory=list)
    warnings: list[ProductionWarning] = Field(default_factory=list)
    configuration_preflight: ConfigurationPreflightResult | None = None
    operational_readiness: dict[str, Any] = Field(default_factory=dict)
    security_readiness: dict[str, Any] = Field(default_factory=dict)
    recovery_readiness: dict[str, Any] = Field(default_factory=dict)
    deployment_readiness: dict[str, Any] = Field(default_factory=dict)
    capacity_readiness: dict[str, Any] = Field(default_factory=dict)
    next_actions: list[dict[str, Any]] = Field(default_factory=list)
    postgresql_source_of_truth: bool = True
    side_effects_performed: bool = False
    external_calls_performed: bool = False
    llm_used: bool = False
    qdrant_used: bool = False
