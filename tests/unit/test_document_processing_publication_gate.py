from __future__ import annotations

import uuid
from unittest.mock import MagicMock

from sqlalchemy.orm import Session

from app.services import document_processing_control_plane as control_plane


def _prepare_blocked_gate(monkeypatch):
    gate = MagicMock()
    gate.ready = False
    gate_payload = {
        "gate_version": "v1",
        "artifact_id": str(uuid.uuid4()),
        "organization_id": str(uuid.uuid4()),
        "document_record_id": str(uuid.uuid4()),
        "document_version_id": str(uuid.uuid4()),
        "processing_evidence_id": None,
        "processing_status": None,
        "processing_completed_at": None,
        "processing_chunk_count": None,
        "ready": False,
        "blocking_issues": [
            {
                "code": "processing_evidence_missing",
                "severity": "blocking",
                "component": "processing_evidence",
                "message": "missing",
            }
        ],
        "authority": "postgresql",
        "contract": "ProcessingEvidenceV1",
    }
    monkeypatch.setattr(
        control_plane,
        "build_upload_session_status",
        lambda db, *, artifact_id: {"processing_session": {"processing_session_id": "processing:test"}},
    )
    monkeypatch.setattr(
        control_plane,
        "build_storage_execution_status",
        lambda db, *, artifact_id: {"storage_verified": True},
    )
    monkeypatch.setattr(
        control_plane,
        "build_document_processing_handoff",
        lambda **kwargs: {"processing_handoff_ready": True},
    )
    monkeypatch.setattr(
        control_plane,
        "evaluate_processing_publication_gate_v1",
        lambda *args, **kwargs: gate,
    )
    monkeypatch.setattr(
        control_plane,
        "serialize_processing_publication_gate_v1",
        lambda value: gate_payload,
    )
    monkeypatch.setattr(
        control_plane,
        "persist_runtime_outputs",
        lambda *args, **kwargs: {"status": "persisted"},
    )
    return gate_payload


def test_knowledge_publication_does_not_execute_when_processing_evidence_gate_is_blocked(
    monkeypatch,
) -> None:
    gate_payload = _prepare_blocked_gate(monkeypatch)
    publication_runtime = MagicMock()
    monkeypatch.setattr(
        control_plane,
        "build_document_processing_chunk_and_publication_execution",
        publication_runtime,
    )

    response = control_plane.build_document_processing_knowledge_publish(
        MagicMock(spec=Session),
        artifact_id=uuid.uuid4(),
    )

    assert response is not None
    assert response["publication_completed"] is False
    assert response["knowledge_published"] is False
    assert response["processing_evidence_gate"] == gate_payload
    assert response["knowledge_publication"]["publication_status"] == "blocked"
    publication_runtime.assert_not_called()


def test_enterprise_search_does_not_execute_when_processing_evidence_gate_is_blocked(
    monkeypatch,
) -> None:
    gate_payload = _prepare_blocked_gate(monkeypatch)
    search_runtime = MagicMock()
    persistence = MagicMock(return_value={"status": "persisted"})
    monkeypatch.setattr(
        control_plane,
        "build_document_processing_publication_and_search_execution",
        search_runtime,
    )
    monkeypatch.setattr(control_plane, "persist_runtime_outputs", persistence)

    response = control_plane.build_document_processing_enterprise_search(
        MagicMock(spec=Session),
        artifact_id=uuid.uuid4(),
        query="pump maintenance",
    )

    assert response is not None
    assert response["knowledge_published"] is False
    assert response["enterprise_search"]["search_status"] == "blocked"
    assert response["processing_evidence_gate"] == gate_payload
    search_runtime.assert_not_called()

    runtime_outputs = persistence.call_args.kwargs["runtime_outputs"]
    assert "knowledge_publication" in runtime_outputs
    assert "enterprise_search" not in runtime_outputs
