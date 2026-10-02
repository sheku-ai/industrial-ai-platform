import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class KnowledgeCollectionCreate(BaseModel):
    organization_id: uuid.UUID | None = None
    code: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    vector_provider: str | None = None
    vector_collection_name: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    status: str = "active"


class KnowledgeCollectionUpdate(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=128)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    vector_provider: str | None = None
    vector_collection_name: str | None = None
    config: dict[str, Any] | None = None
    status: str | None = None


class KnowledgeCollectionRead(KnowledgeCollectionCreate):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    created_by: str | None = None
    updated_by: str | None = None


class KnowledgeCollectionReadiness(BaseModel):
    collection_id: uuid.UUID
    organization_id: uuid.UUID | None = None
    status: str
    active: bool
    document_count: int
    document_version_count: int
    chunk_count: int
    indexed_chunk_count: int
    knowledge_index_count: int
    has_documents: bool
    has_chunks: bool
    has_indexed_knowledge: bool
    enterprise_search_ready: bool
    assistant_ready: bool
    warnings: list[dict[str, Any]] = Field(default_factory=list)
    blocking_issues: list[dict[str, Any]] = Field(default_factory=list)
    llm_used: bool = False
    embeddings_used: bool = False
    qdrant_used: bool = False
    semantic_search_required: bool = False
    postgresql_source_of_truth: bool = True


class KnowledgeCollectionDocumentSummary(BaseModel):
    document_record_id: uuid.UUID
    title: str
    status: str
    source_type: str
    version_count: int
    chunk_count: int
    knowledge_index_count: int


class KnowledgeCollectionContents(BaseModel):
    collection: KnowledgeCollectionRead
    documents: list[KnowledgeCollectionDocumentSummary]
    versions_count: int
    chunks_count: int
    knowledge_index_count: int
    readiness: KnowledgeCollectionReadiness


class KnowledgeCollectionKnowledgeSourceRequest(BaseModel):
    source_type: str = Field(default="collection", min_length=1, max_length=64)
    config: dict[str, Any] = Field(default_factory=dict)
    status: str = "active"


class KnowledgeCollectionKnowledgeSourceResponse(BaseModel):
    collection_id: uuid.UUID
    organization_id: uuid.UUID | None = None
    source_prepared: bool
    source_persisted: bool
    knowledge_source_id: uuid.UUID | None = None
    source_type: str
    source_id: str
    status: str
    descriptor: dict[str, Any]
    llm_used: bool = False
    embeddings_used: bool = False
    qdrant_used: bool = False
    semantic_search_required: bool = False
    postgresql_source_of_truth: bool = True
