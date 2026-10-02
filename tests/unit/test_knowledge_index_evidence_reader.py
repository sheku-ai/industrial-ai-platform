from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

from sqlalchemy.orm import Session

from app.models.documents import DocumentVersion
from app.models.knowledge_index import KnowledgeDocument
from app.services.knowledge_index_evidence_reader import read_knowledge_index_evidence_v1


def _lineage(*, organization_id: uuid.UUID, knowledge_document_id: uuid.UUID):
    now = datetime.now(UTC)
    document_record_id = uuid.uuid4()
    document_version_id = uuid.uuid4()
    document = KnowledgeDocument(
        id=knowledge_document_id,
        artifact_id=str(uuid.uuid4()),
        document_record_id=str(document_record_id),
        document_version_id=str(document_version_id),
        publication_id="publication-1",
        status="indexed",
        version=1,
        content_signature="a" * 64,
        metadata_json={"organization_id": str(uuid.uuid4())},
        created_at=now,
        updated_at=now,
    )
    version = DocumentVersion(
        id=document_version_id,
        organization_id=organization_id,
        document_record_id=document_record_id,
        version_number=1,
        status="registered",
    )
    return document, version


def test_knowledge_index_evidence_reader_enforces_organization_in_persisted_query() -> None:
    organization_id = uuid.uuid4()
    knowledge_document_id = uuid.uuid4()
    document, version = _lineage(
        organization_id=organization_id,
        knowledge_document_id=knowledge_document_id,
    )
    session = MagicMock(spec=Session)
    session.execute.return_value = SimpleNamespace(first=lambda: (document, version))

    evidence = read_knowledge_index_evidence_v1(
        session,
        organization_id=organization_id,
        knowledge_document_id=knowledge_document_id,
    )

    assert evidence is not None
    assert evidence.knowledge_document_id == knowledge_document_id
    assert evidence.organization_id == organization_id
    assert evidence.organization_id != uuid.UUID(document.metadata_json["organization_id"])

    statement = session.execute.call_args.args[0]
    compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))
    assert "knowledge.documents.id" in compiled
    assert "documents.document_versions.organization_id" in compiled
    assert knowledge_document_id.hex in compiled
    assert organization_id.hex in compiled


def test_knowledge_index_evidence_reader_returns_none_without_scoped_document_lineage() -> None:
    session = MagicMock(spec=Session)
    session.execute.return_value = SimpleNamespace(first=lambda: None)

    evidence = read_knowledge_index_evidence_v1(
        session,
        organization_id=uuid.uuid4(),
        knowledge_document_id=uuid.uuid4(),
    )

    assert evidence is None
