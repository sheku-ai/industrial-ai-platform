from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

from sqlalchemy.orm import Session

from app.services import enterprise_search_runtime as runtime


def test_enterprise_search_does_not_execute_when_knowledge_index_gate_is_blocked(monkeypatch) -> None:
    organization_id = uuid.uuid4()
    db = MagicMock(spec=Session)
    db.get.return_value = SimpleNamespace(id=organization_id)

    repository = MagicMock()
    repository.indexed_chunk_count.return_value = 1
    monkeypatch.setattr(runtime, "KnowledgeIndexRepository", lambda session: repository)
    monkeypatch.setattr(
        runtime,
        "build_enterprise_search_gateway",
        lambda **kwargs: {
            "search_session": {
                "search_session_id": "enterprise-search:test",
                "normalized_query": "pump maintenance",
                "top_k": 5,
            },
            "blocking_issues": [],
            "warnings": [],
        },
    )
    gate = SimpleNamespace(
        ready=False,
        blocking_issues=(
            {
                "code": "knowledge_index_evidence_missing",
                "severity": "blocking",
                "component": "knowledge_index_evidence",
                "item_id": None,
                "message": "blocked",
            },
        ),
    )
    gate_reader = MagicMock(return_value=gate)
    monkeypatch.setattr(runtime, "evaluate_knowledge_index_search_gate_v1", gate_reader)
    monkeypatch.setattr(
        runtime,
        "serialize_knowledge_index_search_gate_v1",
        lambda value: {
            "ready": False,
            "authority": "postgresql",
            "contract": "KnowledgeIndexEvidenceV1",
        },
    )

    result = runtime.build_enterprise_search(
        db=db,
        query="pump maintenance",
        search_config={"filters": {"organization_id": str(organization_id)}},
    )

    assert result["search_status"] == "blocked"
    assert result["search_succeeded"] is False
    assert result["search_uses_postgresql_fts"] is False
    assert result["knowledge_index_evidence_gate"]["authority"] == "postgresql"
    assert result["blocking_issues"][0]["code"] == "knowledge_index_evidence_missing"
    gate_reader.assert_called_once_with(
        db,
        organization_id=organization_id,
        artifact_id=None,
        publication_id=None,
        knowledge_document_id=None,
    )
