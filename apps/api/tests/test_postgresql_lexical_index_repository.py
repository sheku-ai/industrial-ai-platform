from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.repositories.lexical_index import PostgreSqlLexicalIndexRepository
from app.services.lexical_indexing import LexicalIndexBatch, LexicalIndexDocument


class ScalarResult:
    def __init__(self, values):
        self._values = values

    def all(self):
        return list(self._values)


class FakeSession:
    def __init__(self, chunks):
        self.chunks = chunks
        self.executed = []
        self.flush_count = 0

    def scalars(self, statement):
        return ScalarResult(self.chunks)

    def execute(self, statement):
        self.executed.append(statement)

    def flush(self):
        self.flush_count += 1


def _batch():
    organization_id = uuid4()
    document_id = uuid4()
    version_id = uuid4()
    document = LexicalIndexDocument(
        organization_id=organization_id,
        document_id=document_id,
        document_version_id=version_id,
        unit_key="u:0",
        ordinal=0,
        content_hash="a" * 64,
        search_text="alpha beta",
        language_config="simple",
        attributes={},
    )
    return LexicalIndexBatch(
        organization_id=organization_id,
        document_id=document_id,
        document_version_id=version_id,
        execution_id=uuid4(),
        pipeline_profile_revision="rev-1",
        documents=(document,),
    )


def test_repository_updates_fts_vector_for_persisted_chunk():
    batch = _batch()
    session = FakeSession([SimpleNamespace(id=uuid4(), chunk_index=0)])

    result = PostgreSqlLexicalIndexRepository(session).replace_document_version_index(batch)

    assert result.indexed_documents == 1
    assert result.unchanged_documents == 0
    assert result.idempotency_key == batch.idempotency_key
    assert len(session.executed) == 1
    assert session.flush_count == 1


def test_repository_rejects_lexical_document_without_chunk():
    batch = _batch()
    session = FakeSession([])

    with pytest.raises(ValueError, match="no persisted chunk"):
        PostgreSqlLexicalIndexRepository(session).replace_document_version_index(batch)
