from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class RuntimeExecutionCreate(BaseModel):
    execution_type: str = Field(min_length=1, max_length=64)
    subject_type: str = Field(min_length=1, max_length=64)
    subject_id: UUID
    idempotency_key: str = Field(min_length=1, max_length=255)
    correlation_id: str | None = Field(default=None, max_length=128)
    priority: int = Field(default=100, ge=0)
    available_at: datetime | None = None
    input_payload: dict[str, Any] = Field(default_factory=dict)
    policy_snapshot: dict[str, Any] = Field(default_factory=dict)


class RuntimeExecutionRead(BaseModel):
    id: UUID
    execution_type: str
    subject_type: str
    subject_id: UUID
    requested_by: str | None
    correlation_id: str | None
    priority: int
    status: str
    requested_at: datetime
    available_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    cancel_requested_at: datetime | None
    metrics: dict[str, Any]
    error_code: str | None
    error_message: str | None

    model_config = {"from_attributes": True}


class RuntimeExecutionCreateResponse(BaseModel):
    execution: RuntimeExecutionRead
    created: bool


class RuntimeAttemptRead(BaseModel):
    id: UUID
    execution_id: UUID
    attempt_number: int
    status: str
    worker_id: str | None
    leased_at: datetime | None
    lease_expires_at: datetime | None
    heartbeat_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    metrics: dict[str, Any]
    error_code: str | None
    error_message: str | None

    model_config = {"from_attributes": True}


class RuntimeEventRead(BaseModel):
    id: UUID
    execution_id: UUID
    attempt_id: UUID | None
    event_type: str
    sequence_number: int
    occurred_at: datetime
    actor_type: str
    actor_reference: str | None
    payload: dict[str, Any]

    model_config = {"from_attributes": True}


class RuntimeArtifactRead(BaseModel):
    id: UUID
    execution_id: UUID
    attempt_id: UUID | None
    artifact_type: str
    storage_uri: str
    media_type: str | None
    checksum_sha256: str | None
    size_bytes: int | None
    metadata: dict[str, Any]
    status: str
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_orm_model(cls, artifact: Any) -> RuntimeArtifactRead:
        return cls(
            id=artifact.id,
            execution_id=artifact.execution_id,
            attempt_id=artifact.attempt_id,
            artifact_type=artifact.artifact_type,
            storage_uri=artifact.storage_uri,
            media_type=artifact.media_type,
            checksum_sha256=artifact.checksum_sha256,
            size_bytes=artifact.size_bytes,
            metadata=artifact.metadata_,
            status=artifact.status,
            created_at=artifact.created_at,
            updated_at=artifact.updated_at,
        )


class RuntimePage(BaseModel):
    items: list[Any]
    limit: int
    offset: int


class RuntimeCancelRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=512)


class RuntimeRetryRequest(BaseModel):
    available_at: datetime | None = None
