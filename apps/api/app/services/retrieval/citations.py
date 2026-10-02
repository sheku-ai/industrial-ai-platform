"""Citation packaging for Retrieval Orchestration."""

from __future__ import annotations

from app.services.retrieval.contracts import Citation, ContextItem
from app.services.retrieval.interfaces import CitationBuilder


class DeterministicCitationBuilder(CitationBuilder):
    """Builds deterministic citations from context items."""

    def build(self, context: tuple[ContextItem, ...]) -> tuple[Citation, ...]:
        citations: list[Citation] = []
        for index, item in enumerate(context, start=1):
            citation_key = item.citation_key or f"C{index}"
            citations.append(
                Citation(
                    citation_key=citation_key,
                    chunk_id=item.chunk_id,
                    document_record_id=item.document_record_id,
                    document_version_id=item.document_version_id,
                    collection_id=item.collection_id,
                    chunk_key=item.chunk_key,
                    metadata=item.metadata,
                )
            )
        return tuple(citations)
