from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

from app.services import chat_runtime


class _FakeDb:
    def __init__(self) -> None:
        self.commits = 0

    def commit(self) -> None:
        self.commits += 1


class _FakeRepository:
    conversation: Any = None

    def __init__(self, db: _FakeDb) -> None:
        self.session = db

    def get_scoped_conversation(self, conversation_id: uuid.UUID, *, organization_id: uuid.UUID) -> Any:
        assert self.conversation.conversation_id == conversation_id
        assert self.conversation.organization_id == organization_id
        return self.conversation

    def get_conversation(self, conversation_id: uuid.UUID) -> Any:
        assert self.conversation.conversation_id == conversation_id
        return self.conversation


def _context_package(*, organization_id: uuid.UUID, conversation_id: uuid.UUID, conversation_turn_id: uuid.UUID) -> Any:
    return SimpleNamespace(
        conversation_context_package_id=uuid.uuid4(),
        organization_id=organization_id,
        ownership_scope="organization",
        conversation_id=conversation_id,
        conversation_turn_id=conversation_turn_id,
        context_hash="context-hash",
        included_turn_ids=[],
        excluded_turns=[],
        context_window_policy={},
        context_policy_version="conversation-context.v1",
        retrieval_inputs={},
        current_user_message="request",
        data_origin="operational",
        created_at=None,
        updated_at=None,
    )


def _interaction_decision(
    *,
    organization_id: uuid.UUID,
    conversation_id: uuid.UUID,
    conversation_turn_id: uuid.UUID,
    context_package_id: uuid.UUID,
    intent: str,
) -> Any:
    return SimpleNamespace(
        interaction_decision_id=uuid.uuid4(),
        organization_id=organization_id,
        ownership_scope="organization",
        data_origin="operational",
        conversation_id=conversation_id,
        conversation_turn_id=conversation_turn_id,
        conversation_context_package_id=context_package_id,
        routing_configuration_id=uuid.uuid4(),
        intent=intent,
        confidence=1.0,
        resolution_method="builtin.deterministic",
        resolution_provider="builtin.deterministic",
        referenced_turn_ids=[],
        conversation_context_required=True,
        retrieval_required=False,
        generation_required=True,
        target_runtime="assistant.enterprise_search",
        embedding_used=False,
        slm_used=False,
        router_version="conversation-router.contract.v1",
        input_hash="input-hash",
        decision_hash="decision-hash",
        created_at=None,
        updated_at=None,
    )


def _configure_common_chat(
    monkeypatch: Any,
    *,
    db: _FakeDb,
    organization_id: uuid.UUID,
    assistant_id: uuid.UUID,
    conversation_id: uuid.UUID,
    conversation_turn_id: uuid.UUID,
    intent: str,
    planned_action: str,
) -> tuple[Any, uuid.UUID]:
    interaction_plan_id = uuid.uuid4()
    _FakeRepository.conversation = SimpleNamespace(
        conversation_id=conversation_id,
        organization_id=organization_id,
        assistant_session_id=None,
        conversation_title="Conversation",
        runtime_context={"organization_id": str(organization_id)},
    )
    monkeypatch.setattr(chat_runtime, "AssistantRepository", _FakeRepository)
    monkeypatch.setattr(
        chat_runtime,
        "validate_chat_request",
        lambda *args, **kwargs: {"blocking_issues": [], "warnings": []},
    )
    context_package = _context_package(
        organization_id=organization_id,
        conversation_id=conversation_id,
        conversation_turn_id=conversation_turn_id,
    )
    interaction_decision = _interaction_decision(
        organization_id=organization_id,
        conversation_id=conversation_id,
        conversation_turn_id=conversation_turn_id,
        context_package_id=context_package.conversation_context_package_id,
        intent=intent,
    )
    monkeypatch.setattr(chat_runtime, "resolve_conversation_context_package", lambda *args, **kwargs: context_package)
    monkeypatch.setattr(chat_runtime, "resolve_interaction_decision", lambda *args, **kwargs: interaction_decision)

    def resolve_directive(*args: Any, **kwargs: Any) -> Any:
        assert db.commits >= 1
        assert kwargs["organization_id"] == organization_id
        assert kwargs["conversation_turn_id"] == conversation_turn_id
        return SimpleNamespace(
            interaction_plan_id=interaction_plan_id,
            organization_id=organization_id,
            conversation_turn_id=conversation_turn_id,
            planned_action=planned_action,
            target_runtime="assistant.enterprise_search",
            enterprise_search_required=False,
            generation_required=True,
            deterministic_response_allowed=False,
        )

    monkeypatch.setattr(chat_runtime, "resolve_interaction_execution_directive", resolve_directive)
    monkeypatch.setattr(
        chat_runtime,
        "interaction_execution_directive_to_dict",
        lambda directive: {
            "interaction_plan_id": str(directive.interaction_plan_id),
            "organization_id": str(directive.organization_id),
            "conversation_turn_id": str(directive.conversation_turn_id),
            "planned_action": directive.planned_action,
            "enterprise_search_required": directive.enterprise_search_required,
            "postgresql_source_of_truth": True,
        },
    )
    return interaction_decision, interaction_plan_id


def _unexpected_search_downstream(*args: Any, **kwargs: Any) -> Any:
    raise AssertionError("no-Search plan must bypass Assistant Run, Retrieval, Readiness, and Search")


def test_no_search_plan_bypasses_all_search_downstream_after_commit(monkeypatch: Any) -> None:
    organization_id = uuid.uuid4()
    assistant_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    user_turn_id = uuid.uuid4()
    assistant_turn_id = uuid.uuid4()
    db = _FakeDb()

    _decision, interaction_plan_id = _configure_common_chat(
        monkeypatch,
        db=db,
        organization_id=organization_id,
        assistant_id=assistant_id,
        conversation_id=conversation_id,
        conversation_turn_id=user_turn_id,
        intent="conversation_summary",
        planned_action="summarize_conversation_evidence",
    )

    turn_calls: list[dict[str, Any]] = []

    def build_turn(*args: Any, **kwargs: Any) -> dict[str, Any]:
        turn_calls.append(kwargs)
        if kwargs["turn_role"] == "user":
            return {
                "conversation_id": str(conversation_id),
                "conversation_turn_id": str(user_turn_id),
                "conversation_turn_created": True,
                "passed": True,
                "blocking_issues": [],
                "warnings": [],
            }
        assert kwargs["turn_role"] == "assistant"
        assert kwargs["output_text"] == "Conversation summary from persisted evidence."
        assert kwargs["response_format"] == "markdown"
        assert kwargs["ordered_citations"] == [{"document_id": "doc-1"}]
        assert kwargs["citation_summary"] == {
            "citation_verification_passed": True,
            "verified_citation_count": 1,
            "missing_citation_count": 0,
            "invalid_citation_count": 0,
        }
        assert kwargs["turn_metadata"]["conversation_no_search_runtime"] is True
        assert kwargs["turn_metadata"]["deterministic_response"] is True
        assert kwargs["turn_metadata"]["conversation_summary"] is True
        return {
            "conversation_id": str(conversation_id),
            "conversation_turn_id": str(assistant_turn_id),
            "conversation_turn_created": True,
            "assistant_runtime_trace_available": False,
            "passed": True,
            "blocking_issues": [],
            "warnings": [],
        }

    monkeypatch.setattr(
        chat_runtime,
        "build_conversation_turn_runtime",
        build_turn,
    )
    summary_calls: list[dict[str, Any]] = []

    def build_summary(*args: Any, **kwargs: Any) -> dict[str, Any]:
        assert args == (db,)
        assert kwargs["organization_id"] == organization_id
        assert kwargs["conversation_turn_id"] == user_turn_id
        summary_calls.append(kwargs)
        return {
            "interaction_plan_id": str(interaction_plan_id),
            "response_text": "Conversation summary from persisted evidence.",
            "response_format": "markdown",
            "ordered_citations": [{"document_id": "doc-1"}],
            "citation_count": 1,
            "enterprise_search_required": False,
            "enterprise_search_bypassed": True,
            "deterministic_response": True,
            "passed": True,
            "blocking_issues": [],
            "warnings": [],
        }

    monkeypatch.setattr(
        chat_runtime,
        "build_conversation_summary_response_runtime",
        build_summary,
    )
    monkeypatch.setattr(chat_runtime, "build_assistant_session_runtime", _unexpected_search_downstream)
    monkeypatch.setattr(chat_runtime, "build_assistant_run_runtime", _unexpected_search_downstream)
    monkeypatch.setattr(chat_runtime, "build_assistant_retrieval_runtime", _unexpected_search_downstream)
    monkeypatch.setattr(
        chat_runtime, "build_assistant_retrieval_execution_readiness_runtime", _unexpected_search_downstream
    )
    monkeypatch.setattr(chat_runtime, "build_planned_conversation_search_runtime", _unexpected_search_downstream)

    result = chat_runtime.build_chat_runtime(
        db,
        assistant_id=str(assistant_id),
        conversation_id=str(conversation_id),
        message="summarize this conversation",
        organization_id=organization_id,
        persist_snapshot=False,
    )

    assert len(summary_calls) == 1
    assert len(turn_calls) == 2
    assert turn_calls[1]["turn_role"] == "assistant"
    assert result["passed"] is True
    assert result["chat_completed"] is True
    assert result["interaction_plan_routed"] is True
    assert result["interaction_plan_id"] == str(interaction_plan_id)
    assert result["planned_action"] == "summarize_conversation_evidence"
    assert result["enterprise_search_required"] is False
    assert result["enterprise_search_bypassed"] is True
    assert result["deterministic_response"] is True
    assert result["assistant_run_id"] is None
    assert result["retrieval_plan_id"] is None
    assert result["execution_plan_id"] is None
    assert result["search_execution_id"] is None
    assert result["llm_used"] is False
    assert result["ordered_citations"] == [{"document_id": "doc-1"}]
    assert result["runtime_chain"]["conversation_no_search_runtime"]["citation_count"] == 1


def test_citation_request_completes_from_persisted_evidence_without_search(monkeypatch: Any) -> None:
    organization_id = uuid.uuid4()
    assistant_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    user_turn_id = uuid.uuid4()
    assistant_turn_id = uuid.uuid4()
    db = _FakeDb()
    _decision, interaction_plan_id = _configure_common_chat(
        monkeypatch,
        db=db,
        organization_id=organization_id,
        assistant_id=assistant_id,
        conversation_id=conversation_id,
        conversation_turn_id=user_turn_id,
        intent="citation_request",
        planned_action="reuse_persisted_citations",
    )

    turn_calls = 0

    def build_turn(*args: Any, **kwargs: Any) -> dict[str, Any]:
        nonlocal turn_calls
        turn_calls += 1
        if kwargs["turn_role"] == "user":
            return {
                "conversation_id": str(conversation_id),
                "conversation_turn_id": str(user_turn_id),
                "conversation_turn_created": True,
                "passed": True,
                "blocking_issues": [],
                "warnings": [],
            }
        assert kwargs["turn_role"] == "assistant"
        assert kwargs["ordered_citations"] == [{"document_id": "doc-1"}]
        assert kwargs.get("assistant_run_id", True)
        return {
            "conversation_id": str(conversation_id),
            "conversation_turn_id": str(assistant_turn_id),
            "conversation_turn_created": True,
            "assistant_runtime_trace_available": False,
            "passed": True,
            "blocking_issues": [],
            "warnings": [],
        }

    monkeypatch.setattr(chat_runtime, "build_conversation_turn_runtime", build_turn)
    monkeypatch.setattr(
        chat_runtime,
        "build_persisted_citation_response_runtime",
        lambda *args, **kwargs: {
            "interaction_plan_id": str(interaction_plan_id),
            "response_text": "Persisted citations from the referenced response are available in ordered_citations.",
            "response_format": "markdown",
            "ordered_citations": [{"document_id": "doc-1"}],
            "citation_count": 1,
            "enterprise_search_required": False,
            "enterprise_search_bypassed": True,
            "deterministic_response": True,
            "passed": True,
            "blocking_issues": [],
            "warnings": [],
        },
    )
    monkeypatch.setattr(chat_runtime, "build_assistant_session_runtime", _unexpected_search_downstream)
    monkeypatch.setattr(chat_runtime, "build_assistant_run_runtime", _unexpected_search_downstream)
    monkeypatch.setattr(chat_runtime, "build_assistant_retrieval_runtime", _unexpected_search_downstream)
    monkeypatch.setattr(
        chat_runtime, "build_assistant_retrieval_execution_readiness_runtime", _unexpected_search_downstream
    )
    monkeypatch.setattr(chat_runtime, "build_planned_conversation_search_runtime", _unexpected_search_downstream)

    result = chat_runtime.build_chat_runtime(
        db,
        assistant_id=str(assistant_id),
        conversation_id=str(conversation_id),
        message="show citations",
        organization_id=organization_id,
        persist_snapshot=False,
    )

    assert turn_calls == 2
    assert result["passed"] is True
    assert result["chat_completed"] is True
    assert result["interaction_plan_routed"] is True
    assert result["interaction_plan_id"] == str(interaction_plan_id)
    assert result["planned_action"] == "reuse_persisted_citations"
    assert result["enterprise_search_required"] is False
    assert result["enterprise_search_bypassed"] is True
    assert result["deterministic_response"] is True
    assert result["assistant_run_id"] is None
    assert result["retrieval_plan_id"] is None
    assert result["execution_plan_id"] is None
    assert result["search_execution_id"] is None
    assert result["ordered_citations"] == [{"document_id": "doc-1"}]
    assert result["citation_summary"]["verified_citation_count"] == 1
    assert result["runtime_chain"]["conversation_no_search_runtime"]["citation_count"] == 1
