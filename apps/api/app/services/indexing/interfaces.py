"""Knowledge Indexing service interfaces."""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.services.indexing.contracts import (
    ChunkIndexingBatch,
    EmbeddingRequest,
    EmbeddingVector,
    IndexingExecutionResult,
    IndexingPlan,
    LexicalIndexUpdate,
    VectorUpsertRequest,
)


class ChunkBatchProvider(ABC):
    """Loads persisted chunks selected for indexing."""

    @abstractmethod
    def load_batch(self, indexing_job_id: str) -> ChunkIndexingBatch:
        raise NotImplementedError


class IndexingPlanner(ABC):
    """Builds deterministic index operations for a chunk batch."""

    @abstractmethod
    def plan(self, batch: ChunkIndexingBatch) -> IndexingPlan:
        raise NotImplementedError


class LexicalIndexClient(ABC):
    """Updates PostgreSQL lexical index fields for persisted chunks."""

    @abstractmethod
    def update(self, request: LexicalIndexUpdate) -> int:
        raise NotImplementedError


class EmbeddingProvider(ABC):
    """Generates embeddings for chunk text."""

    @abstractmethod
    def embed(self, request: EmbeddingRequest) -> tuple[EmbeddingVector, ...]:
        raise NotImplementedError


class VectorIndexClient(ABC):
    """Upserts vectors into a retrieval index."""

    @abstractmethod
    def upsert(self, request: VectorUpsertRequest) -> int:
        raise NotImplementedError


class IndexingStateService(ABC):
    """Persists indexing job lifecycle state."""

    @abstractmethod
    def mark_running(self, indexing_job_id: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def complete(self, result: IndexingExecutionResult) -> None:
        raise NotImplementedError


class IndexingOrchestrator(ABC):
    """Executes a planned indexing batch through product service boundaries."""

    @abstractmethod
    def execute(self, batch: ChunkIndexingBatch) -> IndexingExecutionResult:
        raise NotImplementedError
