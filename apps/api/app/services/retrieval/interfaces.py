"""Retrieval Orchestration service interfaces."""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.services.retrieval.contracts import (
    Citation,
    ContextItem,
    MergedRetrievalCandidate,
    RetrievalCandidate,
    RetrievalQuery,
    RetrievalResult,
)


class LexicalRetriever(ABC):
    """Retrieves candidates from PostgreSQL full text search."""

    @abstractmethod
    def retrieve(self, query: RetrievalQuery) -> tuple[RetrievalCandidate, ...]:
        raise NotImplementedError


class VectorRetriever(ABC):
    """Retrieves candidates from a vector index."""

    @abstractmethod
    def retrieve(self, query: RetrievalQuery) -> tuple[RetrievalCandidate, ...]:
        raise NotImplementedError


class HybridMerger(ABC):
    """Merges lexical and vector candidates."""

    @abstractmethod
    def merge(
        self,
        query: RetrievalQuery,
        lexical: tuple[RetrievalCandidate, ...],
        vector: tuple[RetrievalCandidate, ...],
    ) -> tuple[MergedRetrievalCandidate, ...]:
        raise NotImplementedError


class Reranker(ABC):
    """Optional reranking dependency."""

    @abstractmethod
    def rerank(
        self,
        query: RetrievalQuery,
        candidates: tuple[MergedRetrievalCandidate, ...],
    ) -> tuple[MergedRetrievalCandidate, ...]:
        raise NotImplementedError


class DiversitySelector(ABC):
    """Selects diverse candidates for context assembly."""

    @abstractmethod
    def select(
        self,
        query: RetrievalQuery,
        candidates: tuple[MergedRetrievalCandidate, ...],
    ) -> tuple[MergedRetrievalCandidate, ...]:
        raise NotImplementedError


class ContextBuilder(ABC):
    """Builds bounded context from selected candidates."""

    @abstractmethod
    def build(
        self,
        query: RetrievalQuery,
        candidates: tuple[MergedRetrievalCandidate, ...],
    ) -> tuple[ContextItem, ...]:
        raise NotImplementedError


class CitationBuilder(ABC):
    """Builds deterministic citations for context items."""

    @abstractmethod
    def build(self, context: tuple[ContextItem, ...]) -> tuple[Citation, ...]:
        raise NotImplementedError


class RetrievalOrchestrator(ABC):
    """Coordinates retrieval, merge, rerank, context, and citations."""

    @abstractmethod
    def retrieve(self, query: RetrievalQuery) -> RetrievalResult:
        raise NotImplementedError
