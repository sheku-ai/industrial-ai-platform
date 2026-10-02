from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

from sqlalchemy.orm import Session

from app.models.documents import Artifact
from app.models.runtime import RuntimePersistenceRecord
from app.services import knowledge_index_runtime as runtime


def test_knowledge_index_does_not_run_when_persisted_publication_gate_is_blocked(monkeypatch) -> None:
    organization_id = uuid.uuid4()
    evidence_id = uuid.uuid4()
    artifact_id = uuid.uuid4()
    record = SimpleNamespace(
        runtime_domain="knowledge_publication",
        record_type="publication_result",
        artifact_id=str(artifact_id),
    )
    artifact = SimpleNamespace(id=artifact_id, organization_id=organization_id)
    db = MagicMock(spec=Session)
    db.get.side_effect = lambda model, key: (
        record if model is RuntimePersistenceRecord else artifact if model is Artifact else None
    )
    monkeypatch.setattr(
        runtime,
        "read_knowledge_publication_evidence_v1",
        lambda *args, **kwargs: SimpleNamespace(artifact_id=str(artifact_id)),
    )
    gate = SimpleNamespace(
        ready=False,
        publication_evidence=None,
        blocking_issues=(
            {
                "code": "knowledge_publication_not_persisted",
                "severity": "blocking",
                "component": "knowledge_publication_evidence",
                "message": "blocked",
            },
        ),
    )
    monkeypatch.setattr(runtime, "evaluate_knowledge_publication_index_gate_v1", lambda *args, **kwargs: gate)
    monkeypatch.setattr(
        runtime,
        "serialize_knowledge_publication_index_gate_v1",
        lambda value: {"ready": False, "authority": "postgresql"},
    )
    repository = MagicMock()
    monkeypatch.setattr(runtime, "KnowledgeIndexRepository", repository)

    result = runtime.build_knowledge_index_from_publication_evidence(
        db, evidence_id=evidence_id, organization_id=organization_id
    )

    assert result["index_status"] == "blocked"
    assert result["index_succeeded"] is False
    assert result["knowledge_publication_evidence_gate"]["authority"] == "postgresql"
    assert result["blocking_issues"][0]["code"] == "knowledge_publication_not_persisted"
    repository.assert_not_called()


def test_knowledge_index_rejects_evidence_outside_authorized_organization(monkeypatch) -> None:
    evidence_id = uuid.uuid4()
    organization_id = uuid.uuid4()
    db = MagicMock(spec=Session)
    db.scalar.return_value = None
    reader = MagicMock(wraps=runtime.read_knowledge_publication_evidence_v1)
    gate = MagicMock()
    repository = MagicMock()
    monkeypatch.setattr(runtime, "read_knowledge_publication_evidence_v1", reader)
    monkeypatch.setattr(runtime, "evaluate_knowledge_publication_index_gate_v1", gate)
    monkeypatch.setattr(runtime, "KnowledgeIndexRepository", repository)

    result = runtime.build_knowledge_index_from_publication_evidence(
        db, evidence_id=evidence_id, organization_id=organization_id
    )

    assert result["index_status"] == "blocked"
    assert result["blocking_issues"][0]["code"] == "knowledge_publication_evidence_missing"
    reader.assert_called_once_with(db, organization_id=organization_id, evidence_id=evidence_id)
    db.scalar.assert_called_once()
    db.get.assert_not_called()
    gate.assert_not_called()
    repository.assert_not_called()


def test_knowledge_index_rejects_persisted_chunk_with_other_publication(monkeypatch) -> None:
    organization_id = uuid.uuid4()
    evidence_id = uuid.uuid4()
    artifact_id = uuid.uuid4()
    document_record_id = uuid.uuid4()
    document_version_id = uuid.uuid4()
    record = SimpleNamespace(
        runtime_domain="knowledge_publication",
        record_type="publication_result",
        artifact_id=str(artifact_id),
        record_key="publication:expected",
    )
    artifact = SimpleNamespace(
        id=artifact_id,
        organization_id=organization_id,
        document_record_id=document_record_id,
        document_version_id=document_version_id,
    )
    db = MagicMock(spec=Session)
    db.get.side_effect = lambda model, key: (
        record if model is RuntimePersistenceRecord else artifact if model is Artifact else None
    )
    monkeypatch.setattr(
        runtime,
        "read_knowledge_publication_evidence_v1",
        lambda *args, **kwargs: SimpleNamespace(artifact_id=str(artifact_id)),
    )
    publication_id = "publication:expected"
    payload = {
        "artifact_id": str(artifact_id),
        "document_record_id": str(document_record_id),
        "document_version_id": str(document_version_id),
        "processing_session_id": "processing:1",
        "publication_id": publication_id,
        "published_chunks": [
            {
                "artifact_id": str(artifact_id),
                "document_record_id": str(document_record_id),
                "document_version_id": str(document_version_id),
                "publication_id": "publication:other",
            }
        ],
    }
    evidence = SimpleNamespace(
        organization_id=organization_id,
        processing_session_id="processing:1",
        publication_id=publication_id,
        published_chunk_count=1,
        payload=payload,
    )
    gate_result = SimpleNamespace(ready=True, publication_evidence=evidence, blocking_issues=())
    monkeypatch.setattr(runtime, "evaluate_knowledge_publication_index_gate_v1", lambda *args, **kwargs: gate_result)
    monkeypatch.setattr(runtime, "serialize_knowledge_publication_index_gate_v1", lambda value: {"ready": True})
    monkeypatch.setattr(runtime, "build_knowledge_index_gateway", lambda value: {"blocking_issues": []})
    monkeypatch.setattr(runtime, "validate_publication_lineage", lambda *args, **kwargs: [])
    repository = MagicMock()
    monkeypatch.setattr(runtime, "KnowledgeIndexRepository", repository)

    result = runtime.build_knowledge_index_from_publication_evidence(
        db, evidence_id=evidence_id, organization_id=organization_id
    )

    assert result["index_status"] == "blocked"
    assert result["blocking_issues"][0]["code"] == "RESOURCE_LINEAGE_INCOMPLETE"
    repository.assert_not_called()


def test_legacy_payload_converges_to_persisted_evidence_path(monkeypatch) -> None:
    organization_id = uuid.uuid4()
    evidence_id = uuid.uuid4()
    artifact_id = uuid.uuid4()
    db = MagicMock(spec=Session)
    db.get.return_value = SimpleNamespace(id=artifact_id, organization_id=organization_id)
    payload = {"artifact_id": str(artifact_id)}
    monkeypatch.setattr(runtime, "build_knowledge_index_gateway", lambda value: {"blocking_issues": []})
    monkeypatch.setattr(runtime, "validate_publication_lineage", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        runtime,
        "_persist_publication_evidence",
        lambda *args, **kwargs: ({"persistence_status": "completed"}, evidence_id),
    )
    canonical = MagicMock(return_value={"index_status": "completed", "index_succeeded": True})
    monkeypatch.setattr(runtime, "build_knowledge_index_from_publication_evidence", canonical)

    result = runtime.build_knowledge_index(db, payload, organization_id=organization_id)

    assert result["index_succeeded"] is True
    canonical.assert_called_once_with(db, evidence_id=evidence_id, organization_id=organization_id)


def test_retry_from_same_evidence_does_not_persist_publication_again(monkeypatch) -> None:
    organization_id = uuid.uuid4()
    evidence_id = uuid.uuid4()
    artifact_id = uuid.uuid4()
    record = SimpleNamespace(
        runtime_domain="knowledge_publication",
        record_type="publication_result",
        artifact_id=str(artifact_id),
    )
    artifact = SimpleNamespace(id=artifact_id, organization_id=organization_id)
    db = MagicMock(spec=Session)
    db.get.side_effect = lambda model, key: (
        record if model is RuntimePersistenceRecord else artifact if model is Artifact else None
    )
    monkeypatch.setattr(
        runtime,
        "read_knowledge_publication_evidence_v1",
        lambda *args, **kwargs: SimpleNamespace(artifact_id=str(artifact_id)),
    )
    payload = {
        "artifact_id": str(artifact_id),
        "publication_id": "publication:1",
        "published_chunks": [
            {"published_chunk_id": "chunk:1", "chunk_index": 0, "content_hash": "hash:1", "text": "text"}
        ],
    }
    evidence = SimpleNamespace(payload=payload, publication_id="publication:1")
    gate_result = SimpleNamespace(ready=True, publication_evidence=evidence, blocking_issues=())
    monkeypatch.setattr(runtime, "evaluate_knowledge_publication_index_gate_v1", lambda *args, **kwargs: gate_result)
    monkeypatch.setattr(runtime, "serialize_knowledge_publication_index_gate_v1", lambda value: {"ready": True})
    monkeypatch.setattr(runtime, "build_knowledge_index_gateway", lambda value: {"blocking_issues": []})
    monkeypatch.setattr(runtime, "_persisted_publication_lineage_issues", lambda *args, **kwargs: [])
    persist_publication = MagicMock()
    monkeypatch.setattr(runtime, "_persist_publication_evidence", persist_publication)
    repository = MagicMock()
    repository.upsert_document.return_value = (MagicMock(), False, False)
    repository.upsert_chunk.return_value = (MagicMock(), False, False)
    repository.mark_missing_chunks_superseded.return_value = 0
    monkeypatch.setattr(runtime, "KnowledgeIndexRepository", lambda session: repository)

    first = runtime.build_knowledge_index_from_publication_evidence(
        db, evidence_id=evidence_id, organization_id=organization_id
    )
    second = runtime.build_knowledge_index_from_publication_evidence(
        db, evidence_id=evidence_id, organization_id=organization_id
    )

    assert first["idempotent"] is True
    assert second["idempotent"] is True
    persist_publication.assert_not_called()
    assert db.commit.call_count == 2
