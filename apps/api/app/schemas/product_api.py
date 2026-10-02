import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.core.platform_metadata import CURRENT_SPRINT, CURRENT_WORK_PACKAGE, PRODUCT_VERSION, RELEASE_STAGE


class ProductApiStatus(BaseModel):
    version: str = PRODUCT_VERSION
    sprint: str = CURRENT_SPRINT
    work_package: str = CURRENT_WORK_PACKAGE
    status: str = RELEASE_STAGE


class IngestionUploadRequest(BaseModel):
    organization_id: uuid.UUID
    title: str = Field(min_length=1, max_length=512)
    source_type: str = Field(min_length=1, max_length=64)
    source_ref: dict[str, Any] = Field(default_factory=dict)
    collection_id: uuid.UUID | None = None
    document_type_id: uuid.UUID | None = None
    metadata_template_id: uuid.UUID | None = None
    external_reference: str | None = Field(default=None, max_length=255)
    description: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    classification: dict[str, Any] = Field(default_factory=dict)
    requested_by: str | None = Field(default=None, max_length=255)
    version_label: str | None = Field(default=None, max_length=128)
    file_name: str | None = Field(default=None, max_length=512)
    content_type: str | None = Field(default=None, max_length=255)
    size_bytes: int | None = Field(default=None, ge=0)
    checksum_sha256: str | None = Field(default=None, max_length=64)
    object_store_provider: str | None = Field(default=None, max_length=64)
    object_store_bucket: str | None = Field(default=None, max_length=255)
    object_store_key: str | None = Field(default=None, max_length=1024)
    source_snapshot: dict[str, Any] = Field(default_factory=dict)
    pipeline_name: str | None = Field(default="ingestion_registration", max_length=128)
    pipeline_version: str | None = Field(default="registration-v1", max_length=64)
    adapter_profile: dict[str, Any] = Field(default_factory=dict)
    chunking_profile: dict[str, Any] = Field(default_factory=dict)
    quality_profile: dict[str, Any] = Field(default_factory=dict)
    publication_profile: dict[str, Any] = Field(default_factory=dict)
    priority: int = Field(default=100, ge=0)
    max_attempts: int = Field(default=3, ge=1, le=20)


class IngestionUploadResponse(BaseModel):
    document_record_id: uuid.UUID
    document_version_id: uuid.UUID
    ingestion_job_id: uuid.UUID
    status: str
    document_status: str
    version_status: str
    job_status: str


IngestionJobLifecycleStatus = Literal[
    "pending",
    "queued",
    "claimed",
    "running",
    "succeeded",
    "failed",
    "cancelled",
]


class IngestionJobClaimRequest(BaseModel):
    worker_id: str = Field(min_length=1, max_length=255)
    organization_id: uuid.UUID | None = None
    job_type: str | None = Field(default="ingestion", max_length=64)


class IngestionJobTransitionRequest(BaseModel):
    status: IngestionJobLifecycleStatus
    worker_id: str | None = Field(default=None, max_length=255)
    error_code: str | None = Field(default=None, max_length=128)
    error_message: str | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)


class ChunkPersistenceItem(BaseModel):
    chunk_index: int = Field(ge=0)
    text: str = Field(min_length=1)
    chunk_key: str | None = Field(default=None, max_length=512)
    content_hash: str | None = Field(default=None, max_length=64)
    semantic_hash: str | None = Field(default=None, max_length=64)
    content_type: str | None = Field(default="text/plain", max_length=64)
    section_ref: dict[str, Any] = Field(default_factory=dict)
    provenance: dict[str, Any] = Field(default_factory=dict)
    quality: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    status: str = Field(default="created", max_length=32)


class ChunkPersistenceRequest(BaseModel):
    organization_id: uuid.UUID
    document_version_id: uuid.UUID
    collection_id: uuid.UUID | None = None
    artifact_id: uuid.UUID | None = None
    chunks: tuple[ChunkPersistenceItem, ...] = Field(min_length=1)


class ChunkRead(BaseModel):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    organization_id: uuid.UUID
    document_record_id: uuid.UUID
    document_version_id: uuid.UUID
    artifact_id: uuid.UUID | None = None
    collection_id: uuid.UUID | None = None
    chunk_index: int
    chunk_key: str
    content_hash: str
    semantic_hash: str | None = None
    text: str
    content_type: str | None = None
    section_ref: dict[str, Any] = Field(default_factory=dict)
    provenance: dict[str, Any] = Field(default_factory=dict)
    quality: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    status: str


class ChunkPersistenceResponse(BaseModel):
    organization_id: uuid.UUID
    document_record_id: uuid.UUID
    document_version_id: uuid.UUID
    collection_id: uuid.UUID | None = None
    chunk_count: int
    chunks: tuple[ChunkRead, ...]
    metrics: dict[str, Any] = Field(default_factory=dict)


IndexingJobStatus = Literal["pending", "running", "succeeded", "failed", "cancelled"]


class IndexingJobCreateRequest(BaseModel):
    organization_id: uuid.UUID
    collection_id: uuid.UUID | None = None
    document_record_id: uuid.UUID | None = None
    document_version_id: uuid.UUID | None = None
    ingestion_job_id: uuid.UUID | None = None
    index_target: str = Field(default="postgres_fts", min_length=1, max_length=64)
    embedding_model_id: uuid.UUID | None = None
    vector_provider: str | None = Field(default=None, max_length=64)
    vector_collection_name: str | None = Field(default=None, max_length=255)
    metrics: dict[str, Any] = Field(default_factory=dict)


class IndexingJobRunRequest(BaseModel):
    force: bool = False
    metrics: dict[str, Any] = Field(default_factory=dict)


class IndexingJobRead(BaseModel):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    organization_id: uuid.UUID
    collection_id: uuid.UUID | None = None
    document_record_id: uuid.UUID | None = None
    document_version_id: uuid.UUID | None = None
    ingestion_job_id: uuid.UUID | None = None
    index_target: str
    embedding_model_id: uuid.UUID | None = None
    vector_provider: str | None = None
    vector_collection_name: str | None = None
    status: str
    attempt_count: int
    started_at: datetime | None = None
    finished_at: datetime | None = None
    indexed_chunk_count: int
    failed_chunk_count: int
    metrics: dict[str, Any] = Field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None


RetrievalMode = Literal["lexical_only", "vector_only", "hybrid"]


class KnowledgeSearchRequest(BaseModel):
    organization_id: uuid.UUID
    query_text: str = Field(min_length=1)
    collection_ids: tuple[uuid.UUID, ...] = ()
    top_k: int = Field(default=10, ge=1, le=100)
    candidate_k: int = Field(default=50, ge=1, le=500)
    metadata: dict[str, Any] = Field(default_factory=dict)
    classification: dict[str, Any] = Field(default_factory=dict)
    facet_fields: tuple[str, ...] = Field(default=("collection_id", "content_type"), max_length=20)
    retrieval_mode: RetrievalMode = "lexical_only"
    embedding_enabled: bool = False
    embedding_model_ref: str | None = Field(default=None, max_length=128)
    embedding_provider_ref: str | None = Field(default=None, max_length=128)
    embedding_dimension: int | None = Field(default=None, ge=1, le=65536)
    vector_provider_ref: str | None = Field(default=None, max_length=128)


class KnowledgeCandidateRead(BaseModel):
    chunk_id: uuid.UUID
    document_record_id: uuid.UUID
    document_version_id: uuid.UUID
    collection_id: uuid.UUID | None = None
    chunk_key: str
    text: str
    score: float
    metadata: dict[str, Any] = Field(default_factory=dict)
    classification: dict[str, Any] = Field(default_factory=dict)


class KnowledgeSearchResponse(BaseModel):
    query_text: str
    candidates: tuple[KnowledgeCandidateRead, ...]
    metrics: dict[str, Any] = Field(default_factory=dict)


class KnowledgeContextRequest(KnowledgeSearchRequest):
    context_token_budget: int = Field(default=4000, ge=256, le=32000)
    enable_rerank: bool = False
    enable_diversity: bool = True


class KnowledgeCitationRead(BaseModel):
    citation_key: str
    chunk_id: uuid.UUID
    document_record_id: uuid.UUID
    document_version_id: uuid.UUID
    collection_id: uuid.UUID | None = None
    chunk_key: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class KnowledgeContextItemRead(KnowledgeCandidateRead):
    rank: int
    citation_key: str | None = None


class KnowledgeContextResponse(BaseModel):
    query_text: str
    context: tuple[KnowledgeContextItemRead, ...]
    citations: tuple[KnowledgeCitationRead, ...]
    metrics: dict[str, Any] = Field(default_factory=dict)


KnowledgeAnswerMode = Literal["context_only", "extractive", "assisted"]


class KnowledgeAnswerRequest(KnowledgeContextRequest):
    use_inference: bool = True
    answer_mode: KnowledgeAnswerMode = "extractive"
    provider_ref: str | None = Field(default=None, max_length=128)
    model_ref: str | None = Field(default=None, max_length=128)
    prompt_ref: str | None = Field(default=None, max_length=128)
    guardrail_ref: str | None = Field(default=None, max_length=128)


class KnowledgeAnswerResponse(BaseModel):
    query_text: str
    answer: str | None = None
    context: tuple[KnowledgeContextItemRead, ...]
    citations: tuple[KnowledgeCitationRead, ...]
    requested_answer_mode: KnowledgeAnswerMode = "extractive"
    resolved_answer_mode: KnowledgeAnswerMode = "extractive"
    fallback_used: bool = False
    fallback_reason: str | None = None
    answer_generated: bool = False
    llm_used: bool = False
    provider_ref: str | None = None
    model_ref: str | None = None
    prompt_ref: str | None = None
    guardrail_ref: str | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)


KnowledgeFeedbackTargetType = Literal["query", "candidate", "context", "citation", "answer"]
KnowledgeFeedbackRating = Literal["positive", "negative", "neutral"]


class KnowledgeFeedbackRequest(BaseModel):
    organization_id: uuid.UUID
    query_event_id: str | None = Field(default=None, max_length=128)
    target_type: KnowledgeFeedbackTargetType = "query"
    target_id: str | None = Field(default=None, max_length=255)
    rating: KnowledgeFeedbackRating = "neutral"
    comment: str | None = Field(default=None, max_length=2000)
    metadata: dict[str, Any] = Field(default_factory=dict)


class KnowledgeFeedbackResponse(BaseModel):
    status: str
    receipt: dict[str, Any] = Field(default_factory=dict)
