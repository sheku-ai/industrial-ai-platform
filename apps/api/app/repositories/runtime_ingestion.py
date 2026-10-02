from app.repositories.incremental_content import IncrementalContentRepository
from app.repositories.lexical_index import PostgreSqlLexicalIndexRepository


class RuntimeDocumentContentRepository:
    def __init__(self, session_factory):
        self.session_factory = session_factory

    def replace_document_version_content(self, batch):
        session = self.session_factory()
        try:
            result = IncrementalContentRepository(session).replace_document_version_content(batch)
            session.commit()
            return result
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()


class RuntimeLexicalIndexRepository:
    def __init__(self, session_factory):
        self.session_factory = session_factory

    def replace_document_version_index(self, batch):
        session = self.session_factory()
        try:
            result = PostgreSqlLexicalIndexRepository(session).replace_document_version_index(batch)
            session.commit()
            return result
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
