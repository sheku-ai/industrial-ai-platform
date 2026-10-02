from __future__ import annotations

from collections.abc import Callable

from app.repositories.document_content import SqlAlchemyDocumentContentRepository
from app.services.document_content_persistence import DocumentContentPersistenceService
from app.services.document_ingestion_runtime_adapter import DocumentIngestionRuntimeAdapter
from app.services.ingestion_post_processing import IngestionPostProcessingService
from app.services.lexical_indexing import LexicalIndexService
from app.services.processing_revision_runtime import ProcessingRevisionRuntime


class TransactionalIngestionPostProcessing:
    """Run content persistence and lexical indexing in one owned transaction."""

    def __init__(self, session_factory, lexical_repository_factory: Callable) -> None:
        self._session_factory = session_factory
        self._lexical_repository_factory = lexical_repository_factory

    def process(self, **kwargs):
        session = self._session_factory()
        try:
            service = IngestionPostProcessingService(
                persistence=DocumentContentPersistenceService(SqlAlchemyDocumentContentRepository(session)),
                lexical_index=LexicalIndexService(self._lexical_repository_factory(session)),
            )
            result = service.process(**kwargs)
            session.commit()
            return result
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()


def build_document_ingestion_runtime_adapter(
    *,
    acquisition,
    configuration,
    pipeline,
    session_factory,
    lexical_repository_factory: Callable,
) -> DocumentIngestionRuntimeAdapter:
    """Compose the production document-ingestion adapter from platform services.

    The lexical repository remains an explicit provider dependency. AI, vector
    databases, embeddings and external inference services are not required.
    """

    return DocumentIngestionRuntimeAdapter(
        acquisition=acquisition,
        configuration=configuration,
        pipeline=pipeline,
        post_processing=TransactionalIngestionPostProcessing(
            session_factory,
            lexical_repository_factory,
        ),
        processing_revisions=ProcessingRevisionRuntime(session_factory),
    )
