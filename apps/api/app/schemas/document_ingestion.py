from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class DocumentIngestionRequest(BaseModel):
    pipeline_profile_id: UUID
    adapter_hint: str | None = None
    priority: int = Field(default=100, ge=0, le=1000)
    correlation_id: str | None = Field(default=None, max_length=255)
    metadata: dict[str, Any] = Field(default_factory=dict)
    options: dict[str, Any] = Field(default_factory=dict)


class DocumentIngestionRequestResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    execution_id: UUID
    organization_id: UUID
    document_id: UUID
    document_version_id: UUID
    pipeline_profile_id: UUID
    status: str
    created: bool
    requested_at: datetime
    source_reference: str


class DocumentVersionUploadRequest(BaseModel):
    file_name: str = Field(min_length=1, max_length=512)
    content_type: str = Field(min_length=3, max_length=255)
    size_bytes: int = Field(ge=0)
    checksum_sha256: str = Field(min_length=64, max_length=64)
    version_label: str | None = Field(default=None, max_length=128)


class DocumentVersionUploadResponse(BaseModel):
    organization_id: UUID
    document_id: UUID
    document_version_id: UUID
    version_number: int
    status: str
    bucket: str
    object_key: str
    upload_url: str
    method: str
    required_headers: dict[str, str]
    expires_in_seconds: int


class DocumentVersionUploadConfirmResponse(BaseModel):
    organization_id: UUID
    document_id: UUID
    document_version_id: UUID
    version_number: int
    status: str
    content_type: str
    size_bytes: int
    checksum_sha256: str
