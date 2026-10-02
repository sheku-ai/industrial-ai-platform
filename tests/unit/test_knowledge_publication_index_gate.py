from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock

from sqlalchemy.orm import Session

from app.contracts.knowledge_publication import KnowledgePublicationEvidenceV1
from app.services import knowledge_publication_index_gate as gate_module


def _evidence(*, organization_id: uuid.UUID, artifact_id: str) -> KnowledgePublicationEvidenceV1:
    now = datetime.now(UTC)
    return KnowledgePublicationEvidenceV1(
        evidence_id=uuid.uuid4(),
        organization_id=organization_id,
        execution_id="processing-session:1",
        artifact_id=artifact_id,
        processing_session_id="processing-session:1",
        publication_id="knowledge-publication:1",
        publication_status="completed",
        publication_completed=True,
        publication_succeeded=True,
        knowledge_published=True,
        published_chunk_count=2,
        record_persistence_status="persisted",
        occurred_at=now,
        persisted_at=now,
        payload={},
    )


def test_publication_index_gate_accepts_persisted_completed_evidence(monkeypatch) -> None:
    organization_id = uuid.uuid4()
    artifact_id = str(uuid.uuid4())
    evidence = _evidence(organization_id=organization_id, artifact_id=artifact_id)
    monkeypatch.setattr(
        gate_module,
        "read_knowledge_publication_evidence_v1",
        lambda *args, **kwargs: evidence,
    )

    gate = gate_module.evaluate_knowledge_publication_index_gate_v1(
        MagicMock(spec=Session),
        organization_id=organization_id,
        evidence_id=evidence.evidence_id,
        artifact_id=artifact_id,
    )

    assert gate.ready is True
    assert gate.blocking_issues == ()
    payload = gate_module.serialize_knowledge_publication_index_gate_v1(gate)
    assert payload["authority"] == "postgresql"
    assert payload["contract"] == "KnowledgePublicationEvidenceV1"


def test_publication_index_gate_blocks_mismatched_artifact(monkeypatch) -> None:
    organization_id = uuid.uuid4()
    evidence = _evidence(organization_id=organization_id, artifact_id=str(uuid.uuid4()))
    monkeypatch.setattr(
        gate_module,
        "read_knowledge_publication_evidence_v1",
        lambda *args, **kwargs: evidence,
    )

    gate = gate_module.evaluate_knowledge_publication_index_gate_v1(
        MagicMock(spec=Session),
        organization_id=organization_id,
        evidence_id=evidence.evidence_id,
        artifact_id=str(uuid.uuid4()),
    )

    assert gate.ready is False
    assert {item["code"] for item in gate.blocking_issues} == {"knowledge_publication_artifact_mismatch"}


def test_publication_index_gate_blocks_non_persisted_or_incomplete_evidence(monkeypatch) -> None:
    organization_id = uuid.uuid4()
    artifact_id = str(uuid.uuid4())
    now = datetime.now(UTC)
    evidence = KnowledgePublicationEvidenceV1(
        evidence_id=uuid.uuid4(),
        organization_id=organization_id,
        execution_id="processing-session:1",
        artifact_id=artifact_id,
        processing_session_id="processing-session:1",
        publication_id="knowledge-publication:1",
        publication_status="failed",
        publication_completed=False,
        publication_succeeded=False,
        knowledge_published=False,
        published_chunk_count=0,
        record_persistence_status="failed",
        occurred_at=now,
        persisted_at=now,
        payload={},
    )
    monkeypatch.setattr(
        gate_module,
        "read_knowledge_publication_evidence_v1",
        lambda *args, **kwargs: evidence,
    )

    gate = gate_module.evaluate_knowledge_publication_index_gate_v1(
        MagicMock(spec=Session),
        organization_id=organization_id,
        evidence_id=evidence.evidence_id,
        artifact_id=artifact_id,
    )

    codes = {item["code"] for item in gate.blocking_issues}
    assert gate.ready is False
    assert "knowledge_publication_not_completed" in codes
    assert "knowledge_publication_not_succeeded" in codes
    assert "knowledge_not_published" in codes
    assert "knowledge_publication_chunk_count_empty" in codes
    assert "knowledge_publication_not_persisted" in codes
