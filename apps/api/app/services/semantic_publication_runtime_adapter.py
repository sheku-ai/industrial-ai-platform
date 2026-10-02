from __future__ import annotations

from sqlalchemy import select

from app.models.documents import Chunk
from app.services.runtime_worker import RuntimeAdapterResult


class SemanticPublicationRuntimeAdapter:
    execution_type = "document.ingestion"

    def __init__(self, delegate, session_factory, semantic_publication) -> None:
        self._delegate = delegate
        self._session_factory = session_factory
        self._semantic_publication = semantic_publication

    def execute(self, item, heartbeat) -> RuntimeAdapterResult:
        result = self._delegate.execute(item, heartbeat)
        session = self._session_factory()
        try:
            texts = list(
                session.scalars(
                    select(Chunk.text)
                    .where(
                        Chunk.organization_id == item.organization_id,
                        Chunk.document_version_id == item.subject_id,
                    )
                    .order_by(Chunk.chunk_index)
                ).all()
            )
        finally:
            session.close()

        outcome = self._semantic_publication.publish(
            organization_id=item.organization_id,
            document_version_id=item.subject_id,
            execution_id=item.execution_id,
            texts=texts,
        )
        metrics = dict(result.metrics)
        metrics.update(
            {
                "semantic_publication_connected": outcome.connected,
                "semantic_publication_enabled": outcome.enabled,
                "semantic_documents_published": outcome.published_documents,
                "semantic_publication_provider": outcome.provider,
            }
        )
        return RuntimeAdapterResult(metrics=metrics)
