import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class DocumentTypeCreate(BaseModel):
    organization_id: uuid.UUID | None = None
    code: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    version: str = "1.0"
    status: str = "active"
    config: dict[str, Any] = Field(default_factory=dict)


class DocumentTypeUpdate(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=128)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    version: str | None = None
    status: str | None = None
    config: dict[str, Any] | None = None


class DocumentTypeRead(DocumentTypeCreate):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    created_by: str | None = None
    updated_by: str | None = None


class MetadataTemplateCreate(BaseModel):
    organization_id: uuid.UUID | None = None
    document_type_id: uuid.UUID | None = None
    code: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=255)
    schema_definition: dict[str, Any] = Field(default_factory=dict)
    status: str = "active"


class MetadataTemplateUpdate(BaseModel):
    document_type_id: uuid.UUID | None = None
    code: str | None = Field(default=None, min_length=1, max_length=128)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    schema_definition: dict[str, Any] | None = None
    status: str | None = None


class MetadataTemplateRead(MetadataTemplateCreate):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    created_by: str | None = None
    updated_by: str | None = None


class PolicyRuleCreate(BaseModel):
    organization_id: uuid.UUID | None = None
    code: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=255)
    rules: dict[str, Any] = Field(default_factory=dict)
    status: str = "active"


class PolicyRuleUpdate(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=128)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    rules: dict[str, Any] | None = None
    status: str | None = None


class PolicyRuleRead(PolicyRuleCreate):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    created_by: str | None = None
    updated_by: str | None = None


class CollectionCreate(BaseModel):
    organization_id: uuid.UUID | None = None
    code: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    vector_provider: str | None = None
    vector_collection_name: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    status: str = "active"


class CollectionUpdate(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=128)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    vector_provider: str | None = None
    vector_collection_name: str | None = None
    config: dict[str, Any] | None = None
    status: str | None = None


class CollectionRead(CollectionCreate):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    created_by: str | None = None
    updated_by: str | None = None


class DocumentRegistrationRequest(BaseModel):
    organization_id: uuid.UUID
    title: str = Field(min_length=1, max_length=512)
    source_type: str = Field(min_length=1, max_length=64)
    document_type_id: uuid.UUID
    metadata_template_id: uuid.UUID | None = None
    classification_rule_id: uuid.UUID | None = None
    retention_policy_id: uuid.UUID | None = None
    collection_id: uuid.UUID | None = None
    external_reference: str | None = Field(default=None, max_length=255)
    description: str | None = None
    source_ref: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    classification: dict[str, Any] = Field(default_factory=dict)
    requested_by: str | None = Field(default=None, max_length=255)


class DocumentVersionPlanRequest(BaseModel):
    organization_id: uuid.UUID
    document_record_id: uuid.UUID
    version_label: str | None = Field(default=None, max_length=128)
    requested_by: str | None = Field(default=None, max_length=255)
    metadata: dict[str, Any] = Field(default_factory=dict)


class DocumentBinaryUploadPlanRequest(BaseModel):
    organization_id: uuid.UUID
    document_record_id: uuid.UUID
    document_version_id: uuid.UUID | None = None
    file_name: str | None = Field(default=None, max_length=512)
    content_type: str | None = Field(default=None, max_length=255)
    size_bytes: int | None = Field(default=None, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class DocumentBinaryUploadExecuteRequest(DocumentBinaryUploadPlanRequest):
    document_version_id: uuid.UUID
    requested_by: str | None = Field(default=None, max_length=255)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=255)


class StorageExecutionRequestPayload(BaseModel):
    requested_operation: str = Field(min_length=1, max_length=64)
    requested_by: str | None = Field(default=None, max_length=255)
    request_metadata: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=255)


class DocumentChunkGenerationRequest(BaseModel):
    storage_execution_status: dict[str, Any] | None = None
    chunker_config: dict[str, Any] = Field(default_factory=dict)


class KnowledgePublicationRequest(BaseModel):
    storage_execution_status: dict[str, Any] | None = None
    chunker_config: dict[str, Any] = Field(default_factory=dict)
    publication_config: dict[str, Any] = Field(default_factory=dict)


class EnterpriseSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=512)
    top_k: int = Field(default=5, ge=1, le=50)
    storage_execution_status: dict[str, Any] | None = None
    chunker_config: dict[str, Any] = Field(default_factory=dict)
    publication_config: dict[str, Any] = Field(default_factory=dict)
    search_config: dict[str, Any] = Field(default_factory=dict)


class KnowledgeIndexRequest(BaseModel):
    publication_evidence_id: uuid.UUID | None = None
    publication_result: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_publication_source(self) -> "KnowledgeIndexRequest":
        if self.publication_evidence_id is not None and self.publication_result:
            raise ValueError("publication_evidence_id and publication_result are mutually exclusive")
        return self


class KnowledgeLifecycleRequest(BaseModel):
    mode: str = "INCREMENTAL"
    artifact_id: str | None = None
    publication_id: str | None = None
    document_id: str | None = None
    publication_result: dict[str, Any] = Field(default_factory=dict)


class KnowledgeFtsSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=512)
    top_k: int = Field(default=5, ge=1, le=100)
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=5, ge=1, le=50)
    artifact_id: str | None = None
    publication_id: str | None = None
    knowledge_document_id: str | None = None
    content_type: str | None = None
    chunk_scope: str | None = None
    status: str = "indexed"
    include_facets: bool = False
    include_debug: bool = False


class EmbeddingRuntimeRequest(BaseModel):
    chunk_id: str = Field(min_length=1, max_length=128)
    provider_name: str | None = Field(default=None, max_length=128)
    model_name: str | None = Field(default=None, max_length=255)
    model_version: str | None = Field(default=None, max_length=128)
    embedding_dimensions: int | None = Field(default=0, ge=0)
    runtime_metadata: dict[str, Any] = Field(default_factory=dict)


class VectorIndexPrepareRequest(BaseModel):
    embedding_id: str = Field(min_length=1, max_length=128)
    index_name: str | None = Field(default=None, max_length=255)
    index_provider: str | None = Field(default=None, max_length=128)
    index_provider_type: str | None = Field(default=None, max_length=128)
    index_version: str | None = Field(default=None, max_length=128)
    qdrant_provider_name: str | None = Field(default=None, max_length=128)
    qdrant_collection_name: str | None = Field(default=None, max_length=255)
    runtime_metadata: dict[str, Any] = Field(default_factory=dict)


class VectorIndexPrepareResponse(BaseModel):
    model_config = ConfigDict(extra="allow")


class VectorIndexRecordResponse(BaseModel):
    model_config = ConfigDict(extra="allow")


class VectorIndexHealthResponse(BaseModel):
    model_config = ConfigDict(extra="allow")


class QdrantProviderResponse(BaseModel):
    model_config = ConfigDict(extra="allow")


class QdrantProviderHealthResponse(BaseModel):
    model_config = ConfigDict(extra="allow")


class QdrantExecutionPlanResponse(BaseModel):
    model_config = ConfigDict(extra="allow")


class SemanticSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=512)
    top_k: int | None = Field(default=5, ge=1, le=50)
    vector_index_id: str | None = Field(default=None, max_length=128)
    qdrant_provider_name: str | None = Field(default=None, max_length=128)
    semantic_search_enabled: bool = False
    runtime_metadata: dict[str, Any] = Field(default_factory=dict)


class SemanticSearchResponse(BaseModel):
    model_config = ConfigDict(extra="allow")


class SemanticSearchHealthResponse(BaseModel):
    model_config = ConfigDict(extra="allow")


class HybridSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=512)
    top_k: int | None = Field(default=5, ge=1, le=50)
    hybrid_search_enabled: bool = False
    runtime_metadata: dict[str, Any] = Field(default_factory=dict)


class HybridSearchResponse(BaseModel):
    model_config = ConfigDict(extra="allow")


class HybridSearchHealthResponse(BaseModel):
    model_config = ConfigDict(extra="allow")


class EnterpriseSearchProductRequest(BaseModel):
    organization_id: uuid.UUID | None = None
    query: str = Field(min_length=1, max_length=512)
    top_k: int = Field(default=10, ge=1, le=100)
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=10, ge=1, le=50)
    artifact_id: str | None = None
    publication_id: str | None = None
    knowledge_document_id: str | None = None
    content_type: str | None = None
    chunk_scope: str | None = None
    status: str = "indexed"
    include_facets: bool = True
    include_debug: bool = False


class DocumentLifecycleOrchestrateRequest(BaseModel):
    registration: DocumentRegistrationRequest
    organization_node_ids: list[uuid.UUID] = Field(
        default_factory=list,
        max_length=100,
    )
    version_label: str | None = Field(default=None, max_length=128)
    file_name: str = Field(min_length=1, max_length=512)
    content_type: str = Field(min_length=1, max_length=255)
    content_text: str | None = None
    content_bytes: str | None = None
    size_bytes: int | None = Field(default=None, ge=0)
    storage_provider: dict[str, Any] = Field(default_factory=dict)
    chunker_config: dict[str, Any] = Field(default_factory=dict)
    publication_config: dict[str, Any] = Field(default_factory=dict)
    search_query: str = Field(min_length=1, max_length=512)
    search_config: dict[str, Any] = Field(default_factory=dict)
    top_k: int = Field(default=5, ge=1, le=50)
    requested_by: str | None = Field(default=None, max_length=255)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=255)
    lifecycle_metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("organization_node_ids")
    @classmethod
    def validate_unique_organization_nodes(
        cls,
        value: list[uuid.UUID],
    ) -> list[uuid.UUID]:
        if len(value) != len(set(value)):
            raise ValueError("organization node references must be unique")
        return value


class DocumentLifecycleOrchestrateResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
