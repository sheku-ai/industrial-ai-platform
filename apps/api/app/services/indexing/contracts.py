"""Knowledge Indexing product contracts.

Sprint 9.3 establishes indexing as a generic platform boundary. These contracts
must not encode customer, plant, site, asset, country, department, process, fixed
document taxonomy, or hardcoded vector collection assumptions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID


class IndexTargetType(StrEnum):
    """Supported product-level index target types."""

    LEXICAL_POSTGRES = "lexical_postgres"
    VECTOR_STORE = "vector_store"
    HYBRID = "hybrid"


class IndexOperationType(StrEnum):
    """Concrete indexing operations produced by the planner."""

    UPDATE_LEXICAL = "update_lexical"
    EMBED_CHUNKS = "embed_chunks"
    UPSERT_VECTORS = "upsert_vectors"


class IndexingJobStatus(StrEnum):
    """Lifecycle states for indexing jobs."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED_RETRYABLE = "failed_retryable"
    FAILED_TERMINAL = "failed_terminal"


@dataclass(frozen=True)
class IndexingProfile:
    """Configurable indexing behavior for a knowledge collection."""

    collection_id: UUID
    index_target: IndexTargetType
    embedding_model_id: UUID | None = None
    vector_provider: str | None = None
    vector_collection_name: str | None = None
    lexical_language: str | None = None
    batch_size: int = 64
    classification_policy: dict[str, Any] = field(default_factory=dict)
    metadata_projection: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ChunkIndexRef:
    """Minimal chunk reference required for indexing operations."""

    chunk_id: UUID
    organization_id: UUID
    document_record_id: UUID
    document_version_id: UUID
    collection_id: UUID | None
    chunk_key: str
    content_hash: str
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)
    classification: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ChunkIndexingBatch:
    """Batch of chunks selected for one indexing job execution."""

    indexing_job_id: UUID
    organization_id: UUID
    collection_id: UUID
    chunks: tuple[ChunkIndexRef, ...]
    profile: IndexingProfile


@dataclass(frozen=True)
class EmbeddingRequest:
    """Request to an embedding provider."""

    organization_id: UUID
    embedding_model_id: UUID
    chunks: tuple[ChunkIndexRef, ...]
    input_texts: tuple[str, ...]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EmbeddingVector:
    """Embedding vector associated with a chunk reference."""

    chunk_id: UUID
    vector: tuple[float, ...]
    dimensions: int
    model_ref: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class VectorUpsertRequest:
    """Request to upsert vectors into a retrieval index."""

    organization_id: UUID
    collection_id: UUID
    vector_provider: str
    vector_collection_name: str
    vectors: tuple[EmbeddingVector, ...]
    payloads: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class LexicalIndexUpdate:
    """Request to update lexical index fields for chunks in PostgreSQL."""

    organization_id: UUID
    collection_id: UUID
    chunk_ids: tuple[UUID, ...]
    lexical_language: str | None = None


@dataclass(frozen=True)
class IndexOperation:
    """Planner-produced operation descriptor."""

    operation_type: IndexOperationType
    batch: ChunkIndexingBatch
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class IndexingPlan:
    """Deterministic indexing plan for one batch."""

    indexing_job_id: UUID
    organization_id: UUID
    collection_id: UUID
    operations: tuple[IndexOperation, ...]


@dataclass(frozen=True)
class IndexingExecutionResult:
    """Result returned by the indexing orchestrator boundary."""

    indexing_job_id: UUID
    status: IndexingJobStatus
    indexed_chunk_count: int = 0
    failed_chunk_count: int = 0
    metrics: dict[str, Any] = field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None
    finished_at: datetime | None = None
