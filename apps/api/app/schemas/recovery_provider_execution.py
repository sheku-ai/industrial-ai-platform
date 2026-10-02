from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ProviderExecutionEvidenceCreate(BaseModel):
    scope: str = Field(pattern="^(platform|organization)$")
    organization_id: uuid.UUID | None = None
    operation: str = Field(pattern="^(backup|restore)$")
    resource_type: str
    execution_entity_id: uuid.UUID
    provider_type: str = Field(min_length=1, max_length=64)
    provider_execution_id: str = Field(min_length=1, max_length=255)
    execution_status: str = Field(pattern="^(completed|succeeded|verified|failed|blocked)$")
    started_at: datetime
    completed_at: datetime
    observed_at: datetime | None = None
    evidence_source: str = Field(min_length=1, max_length=128)
    correlation_id: str = Field(min_length=1, max_length=128)
    idempotency_key: str = Field(min_length=1, max_length=255)
    reference_payload: dict[str, Any] = Field(default_factory=dict)


class ProviderExecutionEvidenceRead(BaseModel):
    id: uuid.UUID
    scope: str
    organization_id: uuid.UUID | None = None
    operation: str
    resource_type: str
    execution_entity_id: uuid.UUID
    provider_type: str
    provider_execution_id: str
    execution_status: str
    started_at: datetime
    completed_at: datetime
    observed_at: datetime
    evidence_source: str
    correlation_id: str
    idempotency_key: str
    evidence_hash: str
