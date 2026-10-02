from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class RestoreVerificationCheckEvidenceCreate(BaseModel):
    check_code: str = Field(min_length=1, max_length=128)
    check_status: str = Field(pattern="^(passed|failed)$")
    observed_at: datetime | None = None
    evidence_source: str = Field(min_length=1, max_length=128)
    correlation_id: str = Field(min_length=1, max_length=128)
    idempotency_key: str = Field(min_length=1, max_length=255)
    reference_payload: dict[str, Any] = Field(default_factory=dict)


class RestoreVerificationCheckEvidenceRead(BaseModel):
    id: uuid.UUID
    scope: str
    organization_id: uuid.UUID | None = None
    verification_id: uuid.UUID
    check_code: str
    check_status: str
    observed_at: datetime
    evidence_source: str
    correlation_id: str
    idempotency_key: str
    evidence_hash: str
