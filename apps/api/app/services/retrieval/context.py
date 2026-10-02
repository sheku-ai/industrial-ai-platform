"""Context assembly for Retrieval Orchestration."""

from __future__ import annotations

from app.services.retrieval.contracts import ContextItem, MergedRetrievalCandidate, RetrievalQuery
from app.services.retrieval.interfaces import ContextBuilder


class TokenBudgetContextBuilder(ContextBuilder):
    """Builds bounded context from ranked retrieval candidates."""

    def build(
        self,
        query: RetrievalQuery,
        candidates: tuple[MergedRetrievalCandidate, ...],
    ) -> tuple[ContextItem, ...]:
        context: list[ContextItem] = []
        used_budget = 0

        for index, candidate in enumerate(candidates, start=1):
            text = candidate.candidate.text
            estimated_tokens = max(1, len(text) // 4)
            if used_budget + estimated_tokens > query.context_token_budget:
                break

            citation_key = f"C{index}"
            context.append(
                ContextItem(
                    chunk_id=candidate.candidate.chunk_id,
                    document_record_id=candidate.candidate.document_record_id,
                    document_version_id=candidate.candidate.document_version_id,
                    collection_id=candidate.candidate.collection_id,
                    chunk_key=candidate.candidate.chunk_key,
                    text=text,
                    rank=index,
                    score=candidate.merged_score,
                    metadata=candidate.candidate.metadata,
                    classification=candidate.candidate.classification,
                    citation_key=citation_key,
                )
            )
            used_budget += estimated_tokens

        return tuple(context)
