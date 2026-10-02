import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RuntimeReadMixin(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    created_by: str | None = None
    updated_by: str | None = None


class DocumentRecordCreate(BaseModel):
    organization_id: uuid.UUID
    collection_id: uuid.UUID | None = None
    document_type_id: uuid.UUID | None = None
    metadata_template_id: uuid.UUID | None = None
    external_reference: str | None = Field(default=None, max_length=255)
    title: str = Field(min_length=1, max_length=512)
    description: str | None = None
    source_type: str = Field(min_length=1, max_length=64)
    source_ref: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    classification: dict[str, Any] = Field(default_factory=dict)
    status: str = "registered"


class DocumentRecordUpdate(BaseModel):
    collection_id: uuid.UUID | None = None
    document_type_id: uuid.UUID | None = None
    metadata_template_id: uuid.UUID | None = None
    external_reference: str | None = Field(default=None, max_length=255)
    title: str | None = Field(default=None, min_length=1, max_length=512)
    description: str | None = None
    source_type: str | None = Field(default=None, min_length=1, max_length=64)
    source_ref: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    classification: dict[str, Any] | None = None
    status: str | None = None


class DocumentRecordRead(DocumentRecordCreate, RuntimeReadMixin):
    pass


class DocumentVersionCreate(BaseModel):
    organization_id: uuid.UUID
    document_record_id: uuid.UUID
    version_number: int = Field(ge=1)
    version_label: str | None = Field(default=None, max_length=128)
    content_type: str | None = Field(default=None, max_length=255)
    file_name: str | None = Field(default=None, max_length=512)
    size_bytes: int | None = Field(default=None, ge=0)
    checksum_sha256: str | None = Field(default=None, max_length=64)
    object_store_provider: str | None = Field(default=None, max_length=64)
    object_store_bucket: str | None = Field(default=None, max_length=255)
    object_store_key: str | None = Field(default=None, max_length=1024)
    source_snapshot: dict[str, Any] = Field(default_factory=dict)
    status: str = "registered"


class DocumentVersionUpdate(BaseModel):
    version_label: str | None = Field(default=None, max_length=128)
    content_type: str | None = Field(default=None, max_length=255)
    file_name: str | None = Field(default=None, max_length=512)
    size_bytes: int | None = Field(default=None, ge=0)
    checksum_sha256: str | None = Field(default=None, max_length=64)
    object_store_provider: str | None = Field(default=None, max_length=64)
    object_store_bucket: str | None = Field(default=None, max_length=255)
    object_store_key: str | None = Field(default=None, max_length=1024)
    source_snapshot: dict[str, Any] | None = None
    status: str | None = None


class DocumentVersionRead(DocumentVersionCreate, RuntimeReadMixin):
    pass


class IngestionJobCreate(BaseModel):
    organization_id: uuid.UUID
    document_record_id: uuid.UUID | None = None
    document_version_id: uuid.UUID | None = None
    connector_id: uuid.UUID | None = None
    connector_run_id: uuid.UUID | None = None
    requested_by: str | None = Field(default=None, max_length=255)
    job_type: str = Field(min_length=1, max_length=64)
    pipeline_name: str | None = Field(default=None, max_length=128)
    pipeline_version: str | None = Field(default=None, max_length=64)
    adapter_profile: dict[str, Any] = Field(default_factory=dict)
    chunking_profile: dict[str, Any] = Field(default_factory=dict)
    quality_profile: dict[str, Any] = Field(default_factory=dict)
    publication_profile: dict[str, Any] = Field(default_factory=dict)
    status: str = "pending"
    priority: int = 100
    attempt_count: int = 0
    max_attempts: int = 3
    metrics: dict[str, Any] = Field(default_factory=dict)


class IngestionJobUpdate(BaseModel):
    document_record_id: uuid.UUID | None = None
    document_version_id: uuid.UUID | None = None
    status: str | None = None
    priority: int | None = None
    attempt_count: int | None = None
    max_attempts: int | None = None
    locked_by: str | None = Field(default=None, max_length=255)
    locked_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_code: str | None = Field(default=None, max_length=128)
    error_message: str | None = None
    metrics: dict[str, Any] | None = None


class IngestionJobRead(IngestionJobCreate, RuntimeReadMixin):
    locked_by: str | None = None
    locked_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_code: str | None = None
    error_message: str | None = None


class ArtifactCreate(BaseModel):
    organization_id: uuid.UUID
    document_record_id: uuid.UUID
    document_version_id: uuid.UUID
    ingestion_job_id: uuid.UUID | None = None
    artifact_type: str = Field(min_length=1, max_length=64)
    media_type: str | None = Field(default=None, max_length=255)
    object_store_provider: str | None = Field(default=None, max_length=64)
    bucket: str | None = Field(default=None, max_length=255)
    object_key: str | None = Field(default=None, max_length=1024)
    checksum_sha256: str | None = Field(default=None, max_length=64)
    size_bytes: int | None = Field(default=None, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)
    status: str = "created"


class ArtifactUpdate(BaseModel):
    artifact_type: str | None = Field(default=None, min_length=1, max_length=64)
    media_type: str | None = Field(default=None, max_length=255)
    object_store_provider: str | None = Field(default=None, max_length=64)
    bucket: str | None = Field(default=None, max_length=255)
    object_key: str | None = Field(default=None, max_length=1024)
    checksum_sha256: str | None = Field(default=None, max_length=64)
    size_bytes: int | None = Field(default=None, ge=0)
    metadata: dict[str, Any] | None = None
    status: str | None = None


class ArtifactRead(ArtifactCreate, RuntimeReadMixin):
    pass


class ChunkCreate(BaseModel):
    organization_id: uuid.UUID
    document_record_id: uuid.UUID
    document_version_id: uuid.UUID
    artifact_id: uuid.UUID | None = None
    collection_id: uuid.UUID | None = None
    chunk_index: int = Field(ge=0)
    chunk_key: str = Field(min_length=1, max_length=512)
    content_hash: str = Field(min_length=1, max_length=64)
    semantic_hash: str | None = Field(default=None, max_length=64)
    text: str = Field(min_length=1)
    content_type: str | None = Field(default=None, max_length=64)
    section_ref: dict[str, Any] = Field(default_factory=dict)
    provenance: dict[str, Any] = Field(default_factory=dict)
    quality: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    status: str = "created"


class ChunkUpdate(BaseModel):
    artifact_id: uuid.UUID | None = None
    collection_id: uuid.UUID | None = None
    content_type: str | None = Field(default=None, max_length=64)
    section_ref: dict[str, Any] | None = None
    provenance: dict[str, Any] | None = None
    quality: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    status: str | None = None


class ChunkRead(ChunkCreate, RuntimeReadMixin):
    pass


class IndexingJobCreate(BaseModel):
    organization_id: uuid.UUID
    collection_id: uuid.UUID
    document_record_id: uuid.UUID | None = None
    document_version_id: uuid.UUID | None = None
    ingestion_job_id: uuid.UUID | None = None
    index_target: str = Field(min_length=1, max_length=64)
    embedding_model_id: uuid.UUID | None = None
    vector_provider: str | None = Field(default=None, max_length=64)
    vector_collection_name: str | None = Field(default=None, max_length=255)
    status: str = "pending"
    attempt_count: int = 0
    indexed_chunk_count: int = 0
    failed_chunk_count: int = 0
    metrics: dict[str, Any] = Field(default_factory=dict)


class IndexingJobUpdate(BaseModel):
    status: str | None = None
    attempt_count: int | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    indexed_chunk_count: int | None = None
    failed_chunk_count: int | None = None
    metrics: dict[str, Any] | None = None
    error_code: str | None = Field(default=None, max_length=128)
    error_message: str | None = None


class IndexingJobRead(IndexingJobCreate, RuntimeReadMixin):
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_code: str | None = None
    error_message: str | None = None
