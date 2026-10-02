"""Deterministic Knowledge Indexing planner."""

from __future__ import annotations

from app.services.indexing.contracts import (
    ChunkIndexingBatch,
    IndexingPlan,
    IndexOperation,
    IndexOperationType,
    IndexTargetType,
)
from app.services.indexing.interfaces import IndexingPlanner


class DeterministicIndexingPlanner(IndexingPlanner):
    """Builds operation descriptors from a configurable indexing profile."""

    def plan(self, batch: ChunkIndexingBatch) -> IndexingPlan:
        operations: list[IndexOperation] = []
        target = batch.profile.index_target

        if target in (IndexTargetType.LEXICAL_POSTGRES, IndexTargetType.HYBRID):
            operations.append(
                IndexOperation(
                    operation_type=IndexOperationType.UPDATE_LEXICAL,
                    batch=batch,
                    payload={"lexical_language": batch.profile.lexical_language},
                )
            )

        if target in (IndexTargetType.VECTOR_STORE, IndexTargetType.HYBRID):
            self._validate_vector_profile(batch)
            operations.append(
                IndexOperation(
                    operation_type=IndexOperationType.EMBED_CHUNKS,
                    batch=batch,
                    payload={"embedding_model_id": str(batch.profile.embedding_model_id)},
                )
            )
            operations.append(
                IndexOperation(
                    operation_type=IndexOperationType.UPSERT_VECTORS,
                    batch=batch,
                    payload={
                        "vector_provider": batch.profile.vector_provider,
                        "vector_collection_name": batch.profile.vector_collection_name,
                    },
                )
            )

        return IndexingPlan(
            indexing_job_id=batch.indexing_job_id,
            organization_id=batch.organization_id,
            collection_id=batch.collection_id,
            operations=tuple(operations),
        )

    def _validate_vector_profile(self, batch: ChunkIndexingBatch) -> None:
        if batch.profile.embedding_model_id is None:
            raise ValueError("Vector indexing requires embedding_model_id.")
        if not batch.profile.vector_provider:
            raise ValueError("Vector indexing requires vector_provider.")
        if not batch.profile.vector_collection_name:
            raise ValueError("Vector indexing requires vector_collection_name.")
