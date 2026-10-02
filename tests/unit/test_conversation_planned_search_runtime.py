from __future__ import annotations

import uuid
from types import SimpleNamespace

from app.services import conversation_planned_search_runtime as runtime


def test_planned_search_requires_persisted_plan_and_propagates_evidence(monkeypatch):
    organization_id = uuid.uuid4()
    conversation_turn_id = uuid.uuid4()
    interaction_plan_id = uuid.uuid4()
    captured: dict[str, object] = {}

    def require_plan(db, *, organization_id, conversation_turn_id):
        captured["require"] = (db, organization_id, conversation_turn_id)
        return SimpleNamespace(
            interaction_plan_id=interaction_plan_id,
            planned_action="enterprise_search",
        )

    def execute_search(db, **kwargs):
        captured["search"] = (db, kwargs)
        return {"passed": True}

    monkeypatch.setattr(runtime, "require_enterprise_search_execution", require_plan)
    monkeypatch.setattr(runtime, "build_assistant_search_execution_runtime", execute_search)

    db = object()
    result = runtime.build_planned_conversation_search_runtime(
        db,
        organization_id=organization_id,
        conversation_turn_id=conversation_turn_id,
        execution_plan_id="execution-plan",
        top_k=7,
        search_config={"organization_id": "untrusted", "filters": {"organization_id": "untrusted"}},
        persist_snapshot=False,
    )

    assert captured["require"] == (db, organization_id, conversation_turn_id)
    _, search_kwargs = captured["search"]
    assert search_kwargs["execution_plan_id"] == "execution-plan"
    assert search_kwargs["top_k"] == 7
    assert search_kwargs["persist_snapshot"] is False
    assert search_kwargs["search_config"]["organization_id"] == str(organization_id)
    assert search_kwargs["search_config"]["filters"]["organization_id"] == str(organization_id)
    assert search_kwargs["search_config"]["interaction_plan_id"] == str(interaction_plan_id)
    assert search_kwargs["search_config"]["conversation_turn_id"] == str(conversation_turn_id)
    assert search_kwargs["search_config"]["planned_action"] == "enterprise_search"
    assert result == {
        "passed": True,
        "interaction_plan_id": str(interaction_plan_id),
        "conversation_turn_id": str(conversation_turn_id),
        "planned_action": "enterprise_search",
        "enterprise_search_authorized_by_plan": True,
    }


def test_planned_search_does_not_execute_when_plan_rejects(monkeypatch):
    def reject_plan(*args, **kwargs):
        raise ValueError("enterprise search is not authorized")

    def unexpected_search(*args, **kwargs):
        raise AssertionError("search must not execute without persisted authorization")

    monkeypatch.setattr(runtime, "require_enterprise_search_execution", reject_plan)
    monkeypatch.setattr(runtime, "build_assistant_search_execution_runtime", unexpected_search)

    try:
        runtime.build_planned_conversation_search_runtime(
            object(),
            organization_id=uuid.uuid4(),
            conversation_turn_id=uuid.uuid4(),
            execution_plan_id="execution-plan",
        )
    except ValueError as exc:
        assert str(exc) == "enterprise search is not authorized"
    else:
        raise AssertionError("plan rejection must propagate")
