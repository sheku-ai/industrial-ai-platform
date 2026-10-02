from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock

from sqlalchemy.orm import Session

from app.contracts.enterprise_search import EnterpriseSearchEvidenceV1
from app.services import enterprise_search_assistant_gate as gate_runtime


def _evidence(*, organization_id: uuid.UUID, evidence_id: uuid.UUID) -> EnterpriseSearchEvidenceV1:
    now = datetime.now(UTC)
    return EnterpriseSearchEvidenceV1(
        evidence_id=evidence_id,
        organization_id=organization_id,
        execution_id="enterprise-search:test",
        search_session_id="search-session:test",
        query="pump maintenance",
        normalized_query="pump maintenance",
        search_status="completed",
        ranking_model="postgres_ts_rank_cd_simple_v1",
        total_count=2,
        result_count=2,
        offset=0,
        limit=5,
        has_more=False,
        search_uses_postgresql=True,
        search_uses_postgresql_fts=True,
        semantic_search_used=False,
        embeddings_required=False,
        ai_required=False,
        persistence_status="persisted",
        occurred_at=now,
        persisted_at=now,
        payload={},
    )


def test_enterprise_search_assistant_gate_accepts_persisted_completed_search(monkeypatch) -> None:
    organization_id = uuid.uuid4()
    evidence_id = uuid.uuid4()
    evidence = _evidence(organization_id=organization_id, evidence_id=evidence_id)
    monkeypatch.setattr(
        gate_runtime,
        "read_enterprise_search_evidence_v1",
        lambda *args, **kwargs: evidence,
    )

    gate = gate_runtime.evaluate_enterprise_search_assistant_gate_v1(
        MagicMock(spec=Session),
        organization_id=organization_id,
        evidence_id=evidence_id,
        expected_query="pump maintenance",
    )

    assert gate.ready is True
    assert gate.blocking_issues == ()
    payload = gate_runtime.serialize_enterprise_search_assistant_gate_v1(gate)
    assert payload["authority"] == "postgresql"
    assert payload["contract"] == "EnterpriseSearchEvidenceV1"


def test_enterprise_search_assistant_gate_rejects_query_mismatch(monkeypatch) -> None:
    organization_id = uuid.uuid4()
    evidence_id = uuid.uuid4()
    evidence = _evidence(organization_id=organization_id, evidence_id=evidence_id)
    monkeypatch.setattr(
        gate_runtime,
        "read_enterprise_search_evidence_v1",
        lambda *args, **kwargs: evidence,
    )

    gate = gate_runtime.evaluate_enterprise_search_assistant_gate_v1(
        MagicMock(spec=Session),
        organization_id=organization_id,
        evidence_id=evidence_id,
        expected_query="different query",
    )

    assert gate.ready is False
    assert any(item["code"] == "enterprise_search_query_mismatch" for item in gate.blocking_issues)
