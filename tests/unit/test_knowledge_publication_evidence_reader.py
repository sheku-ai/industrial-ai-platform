from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock

from sqlalchemy.orm import Session

from app.models.runtime import RuntimePersistenceRecord
from app.services.knowledge_publication_evidence_reader import (
    read_knowledge_publication_evidence_v1,
)


def _record(*, organization_id: uuid.UUID, evidence_id: uuid.UUID) -> RuntimePersistenceRecord:
    now = datetime.now(UTC)
    return RuntimePersistenceRecord(
        id=evidence_id,
        execution_id="processing-session:1",
        runtime_domain="knowledge_publication",
        record_type="publication_result",
        record_key="knowledge-publication:1",
        artifact_id=str(uuid.uuid4()),
        processing_session_id="processing-session:1",
        execution_status="completed",
        summary={},
        payload={
            "organization_id": str(organization_id),
            "publication_id": "knowledge-publication:1",
            "publication_status": "completed",
            "publication_completed": True,
            "publication_succeeded": True,
            "knowledge_published": True,
            "published_chunk_count": 2,
        },
        validation={},
        metrics={},
        persistence_status="persisted",
        occurred_at=now,
        persisted_at=now,
        created_at=now,
        updated_at=now,
    )


def test_knowledge_publication_reader_projects_scoped_persisted_publication() -> None:
    organization_id = uuid.uuid4()
    evidence_id = uuid.uuid4()
    record = _record(organization_id=organization_id, evidence_id=evidence_id)
    session = MagicMock(spec=Session)
    session.scalar.return_value = record

    evidence = read_knowledge_publication_evidence_v1(
        session,
        organization_id=organization_id,
        evidence_id=evidence_id,
    )

    assert evidence is not None
    assert evidence.evidence_id == evidence_id
    assert evidence.organization_id == organization_id
    assert evidence.artifact_id == record.artifact_id

    statement = session.scalar.call_args.args[0]
    compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))
    assert "persistence_records.id" in compiled
    assert "knowledge_publication" in compiled
    assert "publication_result" in compiled
    assert "organization_id" in compiled
    assert evidence_id.hex in compiled


def test_knowledge_publication_reader_returns_none_when_scoped_publication_is_absent() -> None:
    session = MagicMock(spec=Session)
    session.scalar.return_value = None

    evidence = read_knowledge_publication_evidence_v1(
        session,
        organization_id=uuid.uuid4(),
        evidence_id=uuid.uuid4(),
    )

    assert evidence is None
