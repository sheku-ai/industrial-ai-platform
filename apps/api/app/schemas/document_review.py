import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class DocumentReviewCreate(BaseModel):
    organization_id: uuid.UUID
    document_record_id: uuid.UUID
    document_version_id: uuid.UUID
    ingestion_job_id: uuid.UUID | None = None
    reason: str = Field(min_length=1, max_length=64)
    detected_format: str = Field(min_length=1, max_length=128)
    detected_by: str = Field(min_length=1, max_length=128)
    encryption_type: str | None = Field(default=None, max_length=128)
    allowed_actions: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    expires_at: datetime | None = None


class DocumentReviewRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    document_record_id: uuid.UUID
    document_version_id: uuid.UUID
    ingestion_job_id: uuid.UUID | None
    status: str
    reason: str
    detected_format: str
    detected_by: str
    encryption_type: str | None
    allowed_actions: list[str]
    metadata: dict[str, Any] = Field(alias="metadata_json")
    secret_expires_at: datetime | None
    secret_single_use: bool
    expires_at: datetime | None
    resolved_at: datetime | None
    created_at: datetime
    updated_at: datetime
    created_by: str | None
    updated_by: str | None


class DocumentReviewDecisionRequest(BaseModel):
    action: str = Field(min_length=1, max_length=64)
    reviewer_subject: str = Field(min_length=1, max_length=255)
    target_status: str = Field(min_length=1, max_length=64)
    note: str | None = Field(default=None, max_length=4000)
    secret_reference: str | None = Field(default=None, max_length=1024)
    secret_expires_at: datetime | None = None
    secret_single_use: bool = True

    @field_validator("secret_reference")
    @classmethod
    def reject_plaintext_like_secret(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if "://" not in value:
            raise ValueError("secret_reference must be an external secret-store reference")
        return value


class DocumentReviewEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    review_case_id: uuid.UUID
    event_type: str
    from_status: str | None
    to_status: str | None
    action: str | None
    actor_subject: str | None
    note: str | None
    details: dict[str, Any]
    created_at: datetime
    updated_at: datetime
