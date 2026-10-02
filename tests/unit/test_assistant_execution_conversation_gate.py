from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

from sqlalchemy.orm import Session

from app.contracts.assistant_execution import AssistantExecutionEvidenceV1
from app.services import assistant_execution_conversation_gate as gate_runtime


def _evidence(
    *,
    organization_id: uuid.UUID,
    assistant_id: uuid.UUID,
    assistant_session_id: uuid.UUID,
    assistant_run_id: uuid.UUID,
    run_status: str = "planned",
) -> AssistantExecutionEvidenceV1:
    now = datetime.now(UTC)
    return AssistantExecutionEvidenceV1(
        assistant_run_id=assistant_run_id,
        organization_id=organization_id,
        assistant_id=assistant_id,
        assistant_session_id=assistant_session_id,
        ownership_scope="organization",
        data_origin="operational",
        run_status=run_status,
        requested_query="pump maintenance",
        selected_search_mode="enterprise_search",
        selected_runtime_domain="enterprise_search",
        execution_state="metadata_only" if run_status == "planned" else run_status,
        started_at=None,
        completed_at=None,
        failed_at=None,
        failure_reason=None,
        created_at=now,
        updated_at=now,
        runtime_metadata={},
    )


def test_gate_accepts_persisted_scoped_assistant_execution_lineage(monkeypatch) -> None:
    organization_id = uuid.uuid4()
    assistant_id = uuid.uuid4()
    assistant_session_id = uuid.uuid4()
    assistant_run_id = uuid.uuid4()
    conversation = SimpleNamespace(
        conversation_id=uuid.uuid4(),
        organization_id=organization_id,
        assistant_id=assistant_id,
        assistant_session_id=assistant_session_id,
    )
    evidence = _evidence(
        organization_id=organization_id,
        assistant_id=assistant_id,
        assistant_session_id=assistant_session_id,
        assistant_run_id=assistant_run_id,
    )
    monkeypatch.setattr(gate_runtime, "read_assistant_execution_evidence_v1", lambda *args, **kwargs: evidence)

    gate = gate_runtime.evaluate_assistant_execution_conversation_gate_v1(
        MagicMock(spec=Session),
        organization_id=organization_id,
        conversation=conversation,
        assistant_run_id=assistant_run_id,
    )

    assert gate.ready is True
    assert gate.blocking_issues == ()
    payload = gate_runtime.serialize_assistant_execution_conversation_gate_v1(gate)
    assert payload["authority"] == "postgresql"
    assert payload["contract"] == "AssistantExecutionEvidenceV1"


def test_gate_blocks_cross_session_assistant_execution(monkeypatch) -> None:
    organization_id = uuid.uuid4()
    assistant_id = uuid.uuid4()
    assistant_run_id = uuid.uuid4()
    evidence = _evidence(
        organization_id=organization_id,
        assistant_id=assistant_id,
        assistant_session_id=uuid.uuid4(),
        assistant_run_id=assistant_run_id,
    )
    conversation = SimpleNamespace(
        conversation_id=uuid.uuid4(),
        organization_id=organization_id,
        assistant_id=assistant_id,
        assistant_session_id=uuid.uuid4(),
    )
    monkeypatch.setattr(gate_runtime, "read_assistant_execution_evidence_v1", lambda *args, **kwargs: evidence)

    gate = gate_runtime.evaluate_assistant_execution_conversation_gate_v1(
        MagicMock(spec=Session),
        organization_id=organization_id,
        conversation=conversation,
        assistant_run_id=assistant_run_id,
    )

    assert gate.ready is False
    assert gate.blocking_issues[0]["code"] == "assistant_execution_session_mismatch"
