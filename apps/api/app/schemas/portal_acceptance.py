from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.readiness import AuthoritativeReadinessEvidence
from app.schemas.release_governance import reject_credential_reference, reject_secrets

PortalValidationType = Literal[
    "principal_routes",
    "portal_build",
    "portal_contract",
    "negative_states",
    "permission_states",
    "cross_organization_states",
]
PortalValidationStatus = Literal["passed", "failed", "blocked", "not_evaluated"]


class PortalAcceptanceEvidenceCreate(BaseModel):
    scope: Literal["platform", "organization"] = "platform"
    organization_id: uuid.UUID | None = None
    validation_run_code: str = Field(min_length=1, max_length=128)
    validation_type: PortalValidationType
    status: PortalValidationStatus
    source: str = Field(min_length=1, max_length=128)
    source_reference: str | None = Field(default=None, max_length=512)
    evidence_payload: dict[str, Any]
    started_at: datetime
    completed_at: datetime | None = None
    observed_at: datetime
    expires_at: datetime | None = None
    created_by: str | None = Field(default=None, max_length=255)

    _reject_secrets = field_validator("evidence_payload")(reject_secrets)

    @field_validator("source_reference")
    @classmethod
    def safe_source_reference(cls, value: str | None) -> str | None:
        return reject_credential_reference(value) if value else value

    @model_validator(mode="after")
    def validate_contract(self) -> PortalAcceptanceEvidenceCreate:
        if self.scope == "platform" and self.organization_id is not None:
            raise ValueError("organization_id must be omitted for platform scope")
        if self.scope == "organization" and self.organization_id is None:
            raise ValueError("organization_id is required for organization scope")
        if self.status == "passed" and not self.evidence_payload:
            raise ValueError("passed portal evidence requires a non-empty evidence payload")
        if self.completed_at is not None and self.completed_at < self.started_at:
            raise ValueError("completed_at cannot precede started_at")
        if self.expires_at is not None and self.expires_at <= self.observed_at:
            raise ValueError("expires_at must be later than observed_at")
        return self


class PortalAcceptanceEvidenceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    scope: str
    organization_id: uuid.UUID | None
    validation_run_code: str
    validation_type: str
    status: str
    source: str
    source_reference: str | None
    evidence_payload: dict[str, Any]
    evidence_hash: str
    started_at: datetime
    completed_at: datetime | None
    observed_at: datetime
    expires_at: datetime | None
    created_by: str | None
    created_at: datetime


class PortalAcceptanceGateResult(BaseModel):
    gate_code: str
    validation_type: str
    status: str
    summary: str
    evidence_reference: str | None = None
    evidence_origin: str | None = None
    observed_at: datetime | None = None
    evidence_age_seconds: int | None = None


class PortalAcceptanceReadiness(BaseModel):
    evidence_contract: AuthoritativeReadinessEvidence
    domain: str = "portal"
    status: str
    reason: str
    scope: str
    organization_id: uuid.UUID | None
    validation_run_code: str | None = None
    gate_results: list[PortalAcceptanceGateResult]
    blockers: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[dict[str, Any]] = Field(default_factory=list)
    recommendations: list[dict[str, Any]] = Field(default_factory=list)
    next_actions: list[dict[str, Any]] = Field(default_factory=list)
    components_evaluated: list[str] = Field(default_factory=list)
    evidence_origins: list[str] = Field(default_factory=list)
    evidence_references: list[str] = Field(default_factory=list)
    evaluated_at: datetime
    evaluation_timestamp: datetime
    expires_at: datetime | None = None
    evidence_age_seconds: int | None = None
    contract_version: str = "platform.readiness.evidence.v1"
    runtime_version: str = "portal-acceptance-runtime.v1"
    postgresql_source_of_truth: bool = True
    side_effects_performed: bool = False
    browser_execution_performed: bool = False


class PortalAcceptanceLatest(BaseModel):
    found: bool
    validation_run_code: str | None = None
    evidence: list[PortalAcceptanceEvidenceRead] = Field(default_factory=list)
    readiness: PortalAcceptanceReadiness
