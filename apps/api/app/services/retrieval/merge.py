"""Hybrid merge for Retrieval Orchestration."""

from __future__ import annotations

from uuid import UUID

from app.services.retrieval.contracts import (
    MergedRetrievalCandidate,
    RetrievalCandidate,
    RetrievalQuery,
    RetrievalSource,
)
from app.services.retrieval.interfaces import HybridMerger


class WeightedHybridMerger(HybridMerger):
    """Merges lexical and vector candidates by chunk identity.

    Scores are combined using query-level weights. The merge keeps resolvable
    PostgreSQL chunk references and never treats vector payloads as source of truth.
    """

    def merge(
        self,
        query: RetrievalQuery,
        lexical: tuple[RetrievalCandidate, ...],
        vector: tuple[RetrievalCandidate, ...],
    ) -> tuple[MergedRetrievalCandidate, ...]:
        by_chunk: dict[UUID, dict[str, object]] = {}

        for candidate in lexical:
            slot = by_chunk.setdefault(candidate.chunk_id, {"candidate": candidate})
            slot["lexical_score"] = max(float(slot.get("lexical_score", 0.0)), candidate.score)

        for candidate in vector:
            slot = by_chunk.setdefault(candidate.chunk_id, {"candidate": candidate})
            slot["vector_score"] = max(float(slot.get("vector_score", 0.0)), candidate.score)

        merged: list[MergedRetrievalCandidate] = []
        for slot in by_chunk.values():
            candidate = slot["candidate"]
            assert isinstance(candidate, RetrievalCandidate)
            lexical_score = slot.get("lexical_score")
            vector_score = slot.get("vector_score")
            lexical_value = float(lexical_score or 0.0)
            vector_value = float(vector_score or 0.0)
            score = (query.lexical_weight * lexical_value) + (query.vector_weight * vector_value)
            merged.append(
                MergedRetrievalCandidate(
                    candidate=RetrievalCandidate(
                        chunk_id=candidate.chunk_id,
                        organization_id=candidate.organization_id,
                        document_record_id=candidate.document_record_id,
                        document_version_id=candidate.document_version_id,
                        collection_id=candidate.collection_id,
                        chunk_key=candidate.chunk_key,
                        text=candidate.text,
                        source=RetrievalSource.HYBRID,
                        score=score,
                        content_hash=candidate.content_hash,
                        metadata=candidate.metadata,
                        classification=candidate.classification,
                    ),
                    lexical_score=lexical_value if lexical_score is not None else None,
                    vector_score=vector_value if vector_score is not None else None,
                    merged_score=score,
                )
            )

        ranked = sorted(merged, key=lambda item: item.merged_score, reverse=True)[: query.candidate_k]
        return tuple(
            MergedRetrievalCandidate(
                candidate=item.candidate,
                lexical_score=item.lexical_score,
                vector_score=item.vector_score,
                merged_score=item.merged_score,
                rank=index + 1,
            )
            for index, item in enumerate(ranked)
        )
