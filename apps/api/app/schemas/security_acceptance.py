from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.readiness import AuthoritativeReadinessEvidence


class SecurityPolicyCreate(BaseModel):
    scope: str = Field(default="platform", pattern="^(platform|organization)$")
    organization_id: uuid.UUID | None = None
    policy_code: str = Field(default="default-security-policy", min_length=1, max_length=128)
    name: str = Field(default="Default Security Policy", min_length=1, max_length=255)
    description: str | None = None
    status: str = Field(default="draft", pattern="^(draft|active|inactive|retired)$")
    authentication_required: bool = True
    authorization_required: bool = True
    debug_allowed: bool = False
    cors_profile: str = Field(default="restricted", max_length=64)
    provider_execution_policy: str = Field(default="explicit", max_length=64)
    placeholder_detection_enabled: bool = True
    required_secrets: list[str] = Field(default_factory=list)
    required_configuration: list[str] = Field(default_factory=list)
    audit_requirements: dict[str, Any] = Field(default_factory=dict)
    organization_isolation_requirements: dict[str, Any] = Field(default_factory=dict)
    configuration_payload: dict[str, Any] = Field(default_factory=dict)
    created_by: str | None = Field(default=None, max_length=255)


class SecurityPolicyUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    description: str | None = None
    status: str | None = Field(default=None, pattern="^(draft|active|inactive|retired)$")
    authentication_required: bool | None = None
    authorization_required: bool | None = None
    debug_allowed: bool | None = None
    cors_profile: str | None = Field(default=None, max_length=64)
    provider_execution_policy: str | None = Field(default=None, max_length=64)
    placeholder_detection_enabled: bool | None = None
    required_secrets: list[str] | None = None
    required_configuration: list[str] | None = None
    audit_requirements: dict[str, Any] | None = None
    organization_isolation_requirements: dict[str, Any] | None = None
    configuration_payload: dict[str, Any] | None = None


class SecurityPolicyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID | None = None
    scope: str
    policy_code: str
    name: str
    description: str | None = None
    status: str
    authentication_required: bool
    authorization_required: bool
    debug_allowed: bool
    cors_profile: str
    provider_execution_policy: str
    placeholder_detection_enabled: bool
    required_secrets: list[str] = Field(default_factory=list)
    required_configuration: list[str] = Field(default_factory=list)
    audit_requirements: dict[str, Any] = Field(default_factory=dict)
    organization_isolation_requirements: dict[str, Any] = Field(default_factory=dict)
    configuration_payload: dict[str, Any] = Field(default_factory=dict)
    created_by: str | None = None
    activated_at: datetime | None = None
    deactivated_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class SecurityFindingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID | None = None
    scope: str
    severity: str
    status: str
    rule: str
    category: str
    summary: str
    evidence: dict[str, Any] = Field(default_factory=dict)
    remediation: str | None = None
    source_runtime: str
    source_entity_type: str
    source_entity_id: str | None = None
    evidence_hash: str
    first_observed_at: datetime
    last_observed_at: datetime
    resolved_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class SecurityEvidenceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID | None = None
    scope: str
    evidence_type: str
    source_runtime: str
    source_entity_type: str
    source_entity_id: str | None = None
    status: str
    evidence_payload: dict[str, Any] = Field(default_factory=dict)
    evidence_hash: str
    observed_at: datetime
    expires_at: datetime | None = None
    created_at: datetime


class SecurityConfigurationCheck(BaseModel):
    setting_code: str
    category: str
    status: str
    masked_value: str
    reason: str
    mandatory: bool
    configured: bool = False
    placeholder: bool = False
    evidence_origin: str = "settings.get_settings"
    evaluated_at: datetime


class SecurityEvaluationRequest(BaseModel):
    scope: str = Field(default="platform", pattern="^(platform|organization)$")
    organization_id: uuid.UUID | None = None
    requested_by: str | None = Field(default=None, max_length=255)
    idempotency_key: str = Field(default="default", min_length=1, max_length=255)


class SecurityReadinessGate(BaseModel):
    gate_code: str
    status: str
    mandatory: bool = True
    summary: str
    evidence_type: str | None = None
    evidence_reference: str | None = None
    blocking_issues: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[dict[str, Any]] = Field(default_factory=list)


class SecurityReadinessResponse(BaseModel):
    evidence_contract: AuthoritativeReadinessEvidence
    runtime_name: str = "security_acceptance_runtime"
    runtime_status: str
    status: str
    reason: str
    security_ready: bool
    gates: list[SecurityReadinessGate]
    policy: SecurityPolicyRead | None = None
    configuration_checks: list[SecurityConfigurationCheck] = Field(default_factory=list)
    findings: list[SecurityFindingRead] = Field(default_factory=list)
    evidence: list[SecurityEvidenceRead] = Field(default_factory=list)
    blockers: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[dict[str, Any]] = Field(default_factory=list)
    recommendations: list[dict[str, Any]] = Field(default_factory=list)
    next_actions: list[dict[str, Any]] = Field(default_factory=list)
    evaluation_timestamp: datetime
    expires_at: datetime | None = None
    contract_version: str
    runtime_version: str
    postgresql_source_of_truth: bool = True
    side_effects_performed: bool = False
    external_calls_performed: bool = False
    llm_used: bool = False
    qdrant_used: bool = False
    secrets_exposed: bool = False


class SecurityConfigurationResponse(BaseModel):
    profile: str
    checks: list[SecurityConfigurationCheck]
    findings: list[SecurityFindingRead] = Field(default_factory=list)
    postgresql_source_of_truth: bool = True
    secrets_exposed: bool = False


class SecurityWorkspaceRuntimeResponse(BaseModel):
    runtime_name: str = "security_acceptance_workspace_runtime"
    runtime_status: str
    readiness: SecurityReadinessResponse
    policies: list[SecurityPolicyRead] = Field(default_factory=list)
    findings: list[SecurityFindingRead] = Field(default_factory=list)
    evidence: list[SecurityEvidenceRead] = Field(default_factory=list)
    configuration_summary: dict[str, Any] = Field(default_factory=dict)
    severity_summary: dict[str, int] = Field(default_factory=dict)
    blockers: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[dict[str, Any]] = Field(default_factory=list)
    next_actions: list[dict[str, Any]] = Field(default_factory=list)
    postgresql_source_of_truth: bool = True
    side_effects_performed: bool = False
    external_calls_performed: bool = False
    llm_used: bool = False
    qdrant_used: bool = False
    secrets_exposed: bool = False
