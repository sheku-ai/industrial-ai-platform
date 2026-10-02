from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

from sqlalchemy.orm import Session

from app.models.assistant_runtime import AssistantRetrievalExecutionPlan, AssistantRetrievalPlan
from app.services import assistant_search_execution_runtime as runtime


def test_assistant_search_does_not_persist_execution_when_search_evidence_gate_blocks(monkeypatch) -> None:
    organization_id = uuid.uuid4()
    evidence_id = uuid.uuid4()
    execution_plan_id = uuid.uuid4()
    retrieval_plan_id = uuid.uuid4()
    assistant_id = uuid.uuid4()
    assistant_session_id = uuid.uuid4()

    execution_plan = SimpleNamespace(
        execution_plan_id=execution_plan_id,
        retrieval_plan_id=retrieval_plan_id,
        assistant_id=assistant_id,
        assistant_session_id=assistant_session_id,
        organization_id=organization_id,
        ownership_scope="organization",
    )
    retrieval_plan = SimpleNamespace(
        retrieval_plan_id=retrieval_plan_id,
        assistant_id=assistant_id,
        assistant_session_id=assistant_session_id,
        organization_id=organization_id,
        ownership_scope="organization",
        requested_query="pump maintenance",
        runtime_metadata={"organization_id": str(organization_id)},
    )
    assistant = SimpleNamespace(assistant_id=assistant_id)
    assistant_session = SimpleNamespace(assistant_session_id=assistant_session_id, assistant_id=assistant_id)

    repository = MagicMock()

    def scoped_artifact(model, *_args, **_kwargs):
        if model is AssistantRetrievalExecutionPlan:
            return execution_plan
        if model is AssistantRetrievalPlan:
            return retrieval_plan
        return None

    repository.get_scoped_artifact.side_effect = scoped_artifact
    repository.get_scoped_assistant_definition.return_value = assistant
    repository.get_scoped_assistant_session.return_value = assistant_session

    monkeypatch.setattr(runtime, "AssistantRepository", lambda db: repository)
    monkeypatch.setattr(
        runtime,
        "build_assistant_search_execution_gateway",
        lambda *args, **kwargs: {"blocking_issues": [], "warnings": []},
    )
    monkeypatch.setattr(runtime, "assistant_to_dict", lambda value: {"assistant_id": str(value.assistant_id)})
    monkeypatch.setattr(
        runtime,
        "assistant_session_to_dict",
        lambda value: {"assistant_session_id": str(value.assistant_session_id)},
    )
    monkeypatch.setattr(runtime, "assistant_retrieval_plan_to_dict", lambda value: {})
    monkeypatch.setattr(runtime, "assistant_retrieval_execution_plan_to_dict", lambda value: {})
    monkeypatch.setattr(
        runtime,
        "build_enterprise_search",
        lambda **kwargs: {
            "organization_id": str(organization_id),
            "search_status": "completed",
            "search_completed": True,
            "search_uses_postgresql": True,
            "search_uses_postgresql_fts": True,
            "result_count": 1,
            "results": [{"search_result_id": "result-1"}],
            "citations": [],
            "blocking_issues": [],
            "warnings": [],
            "runtime_persistence": {
                "persisted_records": [
                    {
                        "id": str(evidence_id),
                        "runtime_domain": "enterprise_search",
                        "record_type": "search_result_set",
                    }
                ]
            },
        },
    )
    gate = SimpleNamespace(
        ready=False,
        blocking_issues=(
            {
                "code": "enterprise_search_not_persisted",
                "severity": "blocking",
                "component": "enterprise_search_evidence",
                "item_id": None,
                "message": "blocked",
            },
        ),
    )
    monkeypatch.setattr(runtime, "evaluate_enterprise_search_assistant_gate_v1", lambda *args, **kwargs: gate)
    monkeypatch.setattr(
        runtime,
        "serialize_enterprise_search_assistant_gate_v1",
        lambda value: {"ready": False, "authority": "postgresql"},
    )

    result = runtime.build_assistant_search_execution_runtime(
        MagicMock(spec=Session),
        execution_plan_id=str(execution_plan_id),
        organization_id=organization_id,
    )

    assert result is not None
    assert result["assistant_search_execution_prepared"] is False
    assert result["search_execution_id"] is None
    assert result["enterprise_search_evidence_gate"]["authority"] == "postgresql"
    assert result["blocking_issues"][0]["code"] == "enterprise_search_not_persisted"
    repository.create_assistant_search_execution.assert_not_called()
