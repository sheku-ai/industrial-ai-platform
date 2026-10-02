from sqlalchemy.orm import Session

from app.repositories.document_ingestion import SqlAlchemyDocumentIngestionRepository
from app.repositories.ingestion_configuration import SqlAlchemyIngestionConfigurationRepository
from app.services.document_content_persistence import DocumentContentPersistenceService
from app.services.ingestion_configuration import IngestionConfigurationService
from app.services.ingestion_post_processing import IngestionPostProcessingService
from app.services.lexical_indexing import LexicalIndexService


class SessionIngestionConfigurationService:
    def __init__(self, session_factory) -> None:
        self._session_factory = session_factory

    def get_profile(self, organization_id, profile_id):
        session: Session = self._session_factory()
        try:
            service = IngestionConfigurationService(SqlAlchemyIngestionConfigurationRepository(session))
            profile = service.get_profile(organization_id, profile_id)
            session.commit()
            return profile
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def resolve_for_adapter(self, profile, adapter_key):
        service = IngestionConfigurationService.__new__(IngestionConfigurationService)
        return service.resolve_for_adapter(profile, adapter_key)


class SessionIngestionPostProcessingService:
    def __init__(self, session_factory) -> None:
        self._session_factory = session_factory

    def process(self, **kwargs):
        session: Session = self._session_factory()
        try:
            repository = SqlAlchemyDocumentIngestionRepository(session)
            service = IngestionPostProcessingService(
                DocumentContentPersistenceService(repository),
                LexicalIndexService(repository),
            )
            result = service.process(**kwargs)
            session.commit()
            return result
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
