"""Retrieval Orchestration boundary."""

from __future__ import annotations

from app.services.retrieval.contracts import RetrievalQuery, RetrievalResult
from app.services.retrieval.interfaces import (
    CitationBuilder,
    ContextBuilder,
    DiversitySelector,
    HybridMerger,
    LexicalRetriever,
    Reranker,
    RetrievalOrchestrator,
    VectorRetriever,
)


class BoundaryRetrievalOrchestrator(RetrievalOrchestrator):
    """Coordinates retrieval, merge, optional rerank, diversity, context, and citations."""

    def __init__(
        self,
        lexical: LexicalRetriever,
        vector: VectorRetriever,
        merger: HybridMerger,
        diversity: DiversitySelector,
        context_builder: ContextBuilder,
        citation_builder: CitationBuilder,
        reranker: Reranker | None = None,
    ) -> None:
        self.lexical = lexical
        self.vector = vector
        self.merger = merger
        self.diversity = diversity
        self.context_builder = context_builder
        self.citation_builder = citation_builder
        self.reranker = reranker

    def retrieve(self, query: RetrievalQuery) -> RetrievalResult:
        lexical_candidates = self.lexical.retrieve(query)
        vector_candidates = self.vector.retrieve(query)
        merged = self.merger.merge(query, lexical_candidates, vector_candidates)

        ranked = merged
        if query.enable_rerank and self.reranker is not None:
            ranked = self.reranker.rerank(query, merged)

        selected = self.diversity.select(query, ranked)
        context = self.context_builder.build(query, selected)
        citations = self.citation_builder.build(context)

        return RetrievalResult(
            query=query,
            candidates=ranked,
            context=context,
            citations=citations,
            metrics={
                "lexical_candidates": len(lexical_candidates),
                "vector_candidates": len(vector_candidates),
                "merged_candidates": len(merged),
                "selected_context_items": len(context),
                "citations": len(citations),
                "rerank_enabled": query.enable_rerank and self.reranker is not None,
            },
        )
