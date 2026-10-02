"""Knowledge Indexing orchestrator boundary."""

from __future__ import annotations

from datetime import UTC, datetime

from app.services.indexing.contracts import (
    ChunkIndexingBatch,
    EmbeddingRequest,
    IndexingExecutionResult,
    IndexingJobStatus,
    IndexOperationType,
    LexicalIndexUpdate,
    VectorUpsertRequest,
)
from app.services.indexing.interfaces import (
    EmbeddingProvider,
    IndexingOrchestrator,
    IndexingPlanner,
    LexicalIndexClient,
    VectorIndexClient,
)


class BoundaryIndexingOrchestrator(IndexingOrchestrator):
    """Executes planned indexing operations through explicit dependencies.

    This boundary does not own retrieval orchestration, public APIs, model serving,
    or persistent repository implementation. It only coordinates indexing clients.
    """

    def __init__(
        self,
        planner: IndexingPlanner,
        lexical_client: LexicalIndexClient | None = None,
        embedding_provider: EmbeddingProvider | None = None,
        vector_client: VectorIndexClient | None = None,
    ) -> None:
        self.planner = planner
        self.lexical_client = lexical_client
        self.embedding_provider = embedding_provider
        self.vector_client = vector_client

    def execute(self, batch: ChunkIndexingBatch) -> IndexingExecutionResult:
        try:
            plan = self.planner.plan(batch)
            indexed_count = 0
            failed_count = 0
            vectors = ()

            for operation in plan.operations:
                if operation.operation_type == IndexOperationType.UPDATE_LEXICAL:
                    if self.lexical_client is None:
                        raise RuntimeError("Lexical index client is required for lexical operations.")
                    indexed_count += self.lexical_client.update(
                        LexicalIndexUpdate(
                            organization_id=batch.organization_id,
                            collection_id=batch.collection_id,
                            chunk_ids=tuple(chunk.chunk_id for chunk in batch.chunks),
                            lexical_language=batch.profile.lexical_language,
                        )
                    )

                elif operation.operation_type == IndexOperationType.EMBED_CHUNKS:
                    if self.embedding_provider is None:
                        raise RuntimeError("Embedding provider is required for vector operations.")
                    vectors = self.embedding_provider.embed(
                        EmbeddingRequest(
                            organization_id=batch.organization_id,
                            embedding_model_id=batch.profile.embedding_model_id,  # type: ignore[arg-type]
                            chunks=batch.chunks,
                            input_texts=tuple(chunk.text for chunk in batch.chunks),
                        )
                    )

                elif operation.operation_type == IndexOperationType.UPSERT_VECTORS:
                    if self.vector_client is None:
                        raise RuntimeError("Vector index client is required for vector operations.")
                    indexed_count += self.vector_client.upsert(
                        VectorUpsertRequest(
                            organization_id=batch.organization_id,
                            collection_id=batch.collection_id,
                            vector_provider=batch.profile.vector_provider or "",
                            vector_collection_name=batch.profile.vector_collection_name or "",
                            vectors=vectors,
                            payloads=tuple(self._vector_payload(chunk) for chunk in batch.chunks),
                        )
                    )

            return IndexingExecutionResult(
                indexing_job_id=batch.indexing_job_id,
                status=IndexingJobStatus.SUCCEEDED,
                indexed_chunk_count=indexed_count,
                failed_chunk_count=failed_count,
                metrics={"operation_count": len(plan.operations), "chunk_count": len(batch.chunks)},
                finished_at=datetime.now(UTC),
            )

        except Exception as exc:  # noqa: BLE001 - boundary converts execution errors to product result
            return IndexingExecutionResult(
                indexing_job_id=batch.indexing_job_id,
                status=IndexingJobStatus.FAILED_TERMINAL,
                indexed_chunk_count=0,
                failed_chunk_count=len(batch.chunks),
                error_code=exc.__class__.__name__,
                error_message=str(exc),
                finished_at=datetime.now(UTC),
            )

    def _vector_payload(self, chunk):  # type: ignore[no-untyped-def]
        return {
            "chunk_id": str(chunk.chunk_id),
            "organization_id": str(chunk.organization_id),
            "document_record_id": str(chunk.document_record_id),
            "document_version_id": str(chunk.document_version_id),
            "collection_id": str(chunk.collection_id) if chunk.collection_id else None,
            "chunk_key": chunk.chunk_key,
            "content_hash": chunk.content_hash,
            "metadata": chunk.metadata,
            "classification": chunk.classification,
        }
