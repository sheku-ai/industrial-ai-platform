"""Retrieval Orchestration product contracts.

Sprint 9.4 reintroduces historical RAG retrieval behavior behind generic
platform contracts. These contracts must not encode customer, plant, site,
asset, country, department, process, fixed document taxonomy, or hardcoded
collection assumptions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
from uuid import UUID


class RetrievalSource(StrEnum):
    """Supported retrieval source types."""

    LEXICAL = "lexical"
    VECTOR = "vector"
    HYBRID = "hybrid"
    RERANKED = "reranked"


@dataclass(frozen=True)
class RetrievalFilters:
    """Configurable filters for retrieval execution."""

    organization_id: UUID
    collection_ids: tuple[UUID, ...] = ()
    document_record_ids: tuple[UUID, ...] = ()
    document_version_ids: tuple[UUID, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    classification: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RetrievalQuery:
    """User or system query submitted to the retrieval orchestrator."""

    query_text: str
    filters: RetrievalFilters
    top_k: int = 10
    candidate_k: int = 50
    lexical_weight: float = 0.5
    vector_weight: float = 0.5
    enable_rerank: bool = False
    enable_diversity: bool = True
    context_token_budget: int = 4000


@dataclass(frozen=True)
class RetrievalCandidate:
    """Candidate chunk returned by a retrieval source."""

    chunk_id: UUID
    organization_id: UUID
    document_record_id: UUID
    document_version_id: UUID
    collection_id: UUID | None
    chunk_key: str
    text: str
    source: RetrievalSource
    score: float
    content_hash: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    classification: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MergedRetrievalCandidate:
    """Candidate after hybrid merge and score normalization."""

    candidate: RetrievalCandidate
    lexical_score: float | None = None
    vector_score: float | None = None
    merged_score: float = 0.0
    rank: int | None = None


@dataclass(frozen=True)
class RerankedCandidate:
    """Candidate after optional rerank provider execution."""

    merged: MergedRetrievalCandidate
    rerank_score: float
    rank: int


@dataclass(frozen=True)
class ContextItem:
    """Chunk selected for context assembly."""

    chunk_id: UUID
    document_record_id: UUID
    document_version_id: UUID
    collection_id: UUID | None
    chunk_key: str
    text: str
    rank: int
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)
    classification: dict[str, Any] = field(default_factory=dict)
    citation_key: str | None = None


@dataclass(frozen=True)
class Citation:
    """Deterministic citation reference for a context item."""

    citation_key: str
    chunk_id: UUID
    document_record_id: UUID
    document_version_id: UUID
    collection_id: UUID | None
    chunk_key: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RetrievalResult:
    """Final retrieval orchestration result."""

    query: RetrievalQuery
    candidates: tuple[MergedRetrievalCandidate, ...]
    context: tuple[ContextItem, ...]
    citations: tuple[Citation, ...]
    metrics: dict[str, Any] = field(default_factory=dict)
