from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.release_governance import reject_secrets


class OperationalEvidenceRequest(BaseModel):
    scope: str = Field(default="platform", pattern="^(platform|organization)$")
    organization_id: uuid.UUID | None = None
    release_version: str = Field(min_length=1, max_length=64)
    alembic_revision: str = Field(min_length=1, max_length=128)
    edition: str | None = Field(default=None, pattern="^(community|enterprise)$")
    execution_key: str = Field(min_length=1, max_length=255)
    correlation_id: str | None = Field(default=None, max_length=128, exclude=True)
    backup_evidence_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def validate_scope(self) -> OperationalEvidenceRequest:
        if self.scope == "platform" and self.organization_id is not None:
            raise ValueError("organization_id_must_be_omitted_for_platform_scope")
        if self.scope == "organization" and self.organization_id is None:
            raise ValueError("organization_id_required")
        return self


class OperationalEvidenceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID | None = None
    backup_execution_id: uuid.UUID | None = None
    scope: str
    evidence_type: str
    release_version: str
    alembic_revision: str
    edition: str | None = None
    status: str
    execution_key: str
    correlation_id: str
    input_hash: str
    evidence_payload: dict[str, Any]
    evidence_hash: str
    source_evidence_ids: list[str]
    evaluated_at: datetime
    expires_at: datetime | None = None
    created_at: datetime


class ReleaseEligibilityRequest(OperationalEvidenceRequest):
    manifest: dict[str, Any]

    _reject_manifest_secrets = field_validator("manifest")(reject_secrets)


class OperationalRefreshSummaryRequest(OperationalEvidenceRequest):
    summary: dict[str, Any]
    source_evidence_ids: list[str] = Field(default_factory=list)

    _reject_summary_secrets = field_validator("summary")(reject_secrets)


class BackupEvidenceContract(BaseModel):
    evidence_id: uuid.UUID
    backup_id: uuid.UUID
    scope: str
    organization_id: uuid.UUID | None = None
    provider: str
    provider_reference: str
    started_at: datetime
    completed_at: datetime
    status: str
    integrity_verified: bool
    checksums: list[dict[str, str]] = Field(default_factory=list)
    application_version: str
    alembic_revision: str
    postgresql_version: str
    expires_at: datetime
    correlation_id: str
    execution_key: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    error_code: str | None = None
    error_detail: str | None = None
