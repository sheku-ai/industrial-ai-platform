from types import SimpleNamespace

import pytest

from app.repositories.document_content import SqlAlchemyDocumentContentRepository
from app.services.document_ingestion_bootstrap import (
    TransactionalIngestionPostProcessing,
    build_document_ingestion_runtime_adapter,
)
from app.services.processing_revision_runtime import ProcessingRevisionRuntime


class FakeSession:
    def __init__(self):
        self.commits = 0
        self.rollbacks = 0
        self.closes = 0

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closes += 1


class SessionFactory:
    def __init__(self):
        self.sessions = []

    def __call__(self):
        session = FakeSession()
        self.sessions.append(session)
        return session


def test_bootstrap_composes_sql_persistence_and_revision_runtime():
    sessions = SessionFactory()
    adapter = build_document_ingestion_runtime_adapter(
        acquisition=object(),
        configuration=object(),
        pipeline=object(),
        session_factory=sessions,
        lexical_repository_factory=lambda session: SimpleNamespace(),
    )
    assert isinstance(adapter._post_processing, TransactionalIngestionPostProcessing)
    assert isinstance(adapter._processing_revisions, ProcessingRevisionRuntime)


def test_post_processing_commits_and_closes(monkeypatch):
    sessions = SessionFactory()
    runtime = TransactionalIngestionPostProcessing(sessions, lambda session: SimpleNamespace())

    def fake_process(self, **kwargs):
        assert isinstance(self._persistence._repository, SqlAlchemyDocumentContentRepository)
        return "ok"

    monkeypatch.setattr(
        "app.services.document_ingestion_bootstrap.IngestionPostProcessingService.process", fake_process
    )
    assert runtime.process(value=1) == "ok"
    session = sessions.sessions[0]
    assert (session.commits, session.rollbacks, session.closes) == (1, 0, 1)


def test_post_processing_rolls_back_and_closes(monkeypatch):
    sessions = SessionFactory()
    runtime = TransactionalIngestionPostProcessing(sessions, lambda session: SimpleNamespace())

    def fail(self, **kwargs):
        raise RuntimeError("failed")

    monkeypatch.setattr("app.services.document_ingestion_bootstrap.IngestionPostProcessingService.process", fail)
    with pytest.raises(RuntimeError, match="failed"):
        runtime.process(value=1)
    session = sessions.sessions[0]
    assert (session.commits, session.rollbacks, session.closes) == (0, 1, 1)
