from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

from sqlalchemy.orm import Session

from app.services import knowledge_index_search_gate as gate_runtime


def test_knowledge_index_search_gate_reads_scoped_persisted_evidence(monkeypatch) -> None:
    organization_id = uuid.uuid4()
    knowledge_document_id = uuid.uuid4()
    artifact_id = str(uuid.uuid4())
    publication_id = "knowledge-publication:1"
    session = MagicMock(spec=Session)
    session.scalar.return_value = knowledge_document_id
    evidence = SimpleNamespace(
        knowledge_document_id=knowledge_document_id,
        organization_id=organization_id,
        artifact_id=artifact_id,
        publication_id=publication_id,
        status="indexed",
        index_version=2,
    )
    reader = MagicMock(return_value=evidence)
    monkeypatch.setattr(gate_runtime, "read_knowledge_index_evidence_v1", reader)

    gate = gate_runtime.evaluate_knowledge_index_search_gate_v1(
        session,
        organization_id=organization_id,
        artifact_id=artifact_id,
        publication_id=publication_id,
        knowledge_document_id=str(knowledge_document_id),
    )

    assert gate.ready is True
    assert gate.knowledge_index_evidence is evidence
    assert gate.blocking_issues == ()
    reader.assert_called_once_with(
        session,
        organization_id=organization_id,
        knowledge_document_id=knowledge_document_id,
    )

    statement = session.scalar.call_args.args[0]
    compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))
    assert "documents.document_versions.organization_id" in compiled
    assert "knowledge.documents.status = 'indexed'" in compiled
    assert "knowledge.chunks.status = 'indexed'" in compiled
    assert organization_id.hex in compiled
    assert artifact_id in compiled
    assert publication_id in compiled
    assert knowledge_document_id.hex in compiled


def test_knowledge_index_search_gate_blocks_when_no_indexed_evidence_exists() -> None:
    session = MagicMock(spec=Session)
    session.scalar.return_value = None

    gate = gate_runtime.evaluate_knowledge_index_search_gate_v1(
        session,
        organization_id=uuid.uuid4(),
    )

    assert gate.ready is False
    assert gate.knowledge_index_evidence is None
    assert gate.blocking_issues[0]["code"] == "knowledge_index_evidence_missing"


def test_knowledge_index_search_gate_rejects_invalid_document_filter() -> None:
    session = MagicMock(spec=Session)

    gate = gate_runtime.evaluate_knowledge_index_search_gate_v1(
        session,
        organization_id=uuid.uuid4(),
        knowledge_document_id="not-a-uuid",
    )

    assert gate.ready is False
    assert gate.blocking_issues[0]["code"] == "knowledge_document_scope_invalid"
    session.scalar.assert_not_called()
