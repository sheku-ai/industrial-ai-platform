"""Retrieval Orchestration service package."""

from app.services.retrieval.citations import DeterministicCitationBuilder
from app.services.retrieval.context import TokenBudgetContextBuilder
from app.services.retrieval.contracts import (
    Citation,
    ContextItem,
    MergedRetrievalCandidate,
    RerankedCandidate,
    RetrievalCandidate,
    RetrievalFilters,
    RetrievalQuery,
    RetrievalResult,
    RetrievalSource,
)
from app.services.retrieval.diversity import ContentAwareDiversitySelector
from app.services.retrieval.merge import WeightedHybridMerger
from app.services.retrieval.orchestrator import BoundaryRetrievalOrchestrator
from app.services.retrieval.postgres_fts import DisabledVectorRetriever, PostgresFtsRetriever

__all__ = [
    "BoundaryRetrievalOrchestrator",
    "Citation",
    "ContentAwareDiversitySelector",
    "ContextItem",
    "DeterministicCitationBuilder",
    "DisabledVectorRetriever",
    "MergedRetrievalCandidate",
    "PostgresFtsRetriever",
    "RerankedCandidate",
    "RetrievalCandidate",
    "RetrievalFilters",
    "RetrievalQuery",
    "RetrievalResult",
    "RetrievalSource",
    "TokenBudgetContextBuilder",
    "WeightedHybridMerger",
]
