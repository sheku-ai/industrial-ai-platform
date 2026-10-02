from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from app.services import conversation_no_search_runtime as runtime


class _ScalarResult:
    def __init__(self, records: list[Any]) -> None:
        self.records = records

    def all(self) -> list[Any]:
        return self.records


class _FakeDb:
    def __init__(self, records: list[Any]) -> None:
        self.records = records

    def scalars(self, statement: Any) -> _ScalarResult:
        return _ScalarResult(self.records)


class _Repository:
    decision: Any = None
    current_turn: Any = None

    def __init__(self, db: Any) -> None:
        self.db = db

    def get_scoped_conversation_interaction_decision(
        self, *, conversation_turn_id: uuid.UUID, organization_id: uuid.UUID
    ) -> Any:
        assert self.decision.conversation_turn_id == conversation_turn_id
        assert self.decision.organization_id == organization_id
        return self.decision

    def get_scoped_conversation_turn(self, conversation_turn_id: uuid.UUID, *, organization_id: uuid.UUID) -> Any:
        if self.current_turn is None:
            return None
        assert self.current_turn.conversation_turn_id == conversation_turn_id
        assert self.current_turn.organization_id == organization_id
        return self.current_turn


def _directive(
    *, organization_id: uuid.UUID, conversation_turn_id: uuid.UUID, planned_action: str = "reuse_persisted_citations"
) -> Any:
    return SimpleNamespace(
        interaction_plan_id=uuid.uuid4(),
        organization_id=organization_id,
        conversation_turn_id=conversation_turn_id,
        planned_action=planned_action,
        target_runtime="assistant.enterprise_search",
        enterprise_search_required=False,
        generation_required=True,
        deterministic_response_allowed=False,
    )


def test_citation_request_reuses_only_persisted_referenced_turn_citations(monkeypatch: Any) -> None:
    organization_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    current_turn_id = uuid.uuid4()
    referenced_turn_id = uuid.uuid4()
    directive = _directive(organization_id=organization_id, conversation_turn_id=current_turn_id)
    _Repository.decision = SimpleNamespace(
        interaction_decision_id=uuid.uuid4(),
        organization_id=organization_id,
        conversation_id=conversation_id,
        conversation_turn_id=current_turn_id,
        intent="citation_request",
        referenced_turn_ids=[str(referenced_turn_id)],
    )
    referenced_turn = SimpleNamespace(
        conversation_turn_id=referenced_turn_id,
        organization_id=organization_id,
        conversation_id=conversation_id,
        ordered_citations=[{"document_id": "doc-1", "chunk_id": "chunk-1"}],
    )
    monkeypatch.setattr(runtime, "AssistantRepository", _Repository)
    monkeypatch.setattr(runtime, "resolve_interaction_execution_directive", lambda *args, **kwargs: directive)

    result = runtime.build_persisted_citation_response_runtime(
        _FakeDb([referenced_turn]),
        organization_id=organization_id,
        conversation_turn_id=current_turn_id,
    )

    assert result["planned_action"] == "reuse_persisted_citations"
    assert result["intent"] == "citation_request"
    assert result["referenced_turn_ids"] == [str(referenced_turn_id)]
    assert result["evidence_turn_ids"] == [str(referenced_turn_id)]
    assert result["ordered_citations"] == [{"document_id": "doc-1", "chunk_id": "chunk-1"}]
    assert result["citation_count"] == 1
    assert result["enterprise_search_bypassed"] is True
    assert result["deterministic_response"] is True
    assert result["postgresql_source_of_truth"] is True
    assert result["llm_used"] is False


def test_citation_request_does_not_fallback_to_search_when_no_citations_exist(monkeypatch: Any) -> None:
    organization_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    current_turn_id = uuid.uuid4()
    referenced_turn_id = uuid.uuid4()
    directive = _directive(organization_id=organization_id, conversation_turn_id=current_turn_id)
    _Repository.decision = SimpleNamespace(
        interaction_decision_id=uuid.uuid4(),
        organization_id=organization_id,
        conversation_id=conversation_id,
        conversation_turn_id=current_turn_id,
        intent="citation_request",
        referenced_turn_ids=[str(referenced_turn_id)],
    )
    referenced_turn = SimpleNamespace(
        conversation_turn_id=referenced_turn_id,
        organization_id=organization_id,
        conversation_id=conversation_id,
        ordered_citations=[],
    )
    monkeypatch.setattr(runtime, "AssistantRepository", _Repository)
    monkeypatch.setattr(runtime, "resolve_interaction_execution_directive", lambda *args, **kwargs: directive)

    result = runtime.build_persisted_citation_response_runtime(
        _FakeDb([referenced_turn]),
        organization_id=organization_id,
        conversation_turn_id=current_turn_id,
    )

    assert result["citation_count"] == 0
    assert result["ordered_citations"] == []
    assert result["enterprise_search_required"] is False
    assert result["enterprise_search_bypassed"] is True
    assert result["provider_called"] is False


def test_citation_request_rejects_plan_not_authorized_for_citation_reuse(monkeypatch: Any) -> None:
    organization_id = uuid.uuid4()
    current_turn_id = uuid.uuid4()
    directive = _directive(
        organization_id=organization_id,
        conversation_turn_id=current_turn_id,
        planned_action="summarize_conversation_evidence",
    )
    monkeypatch.setattr(runtime, "resolve_interaction_execution_directive", lambda *args, **kwargs: directive)

    with pytest.raises(runtime.ConversationNoSearchExecutionError, match="does not authorize citation reuse"):
        runtime.build_persisted_citation_response_runtime(
            _FakeDb([]),
            organization_id=organization_id,
            conversation_turn_id=current_turn_id,
        )


def test_citation_request_rejects_missing_referenced_evidence(monkeypatch: Any) -> None:
    organization_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    current_turn_id = uuid.uuid4()
    referenced_turn_id = uuid.uuid4()
    directive = _directive(organization_id=organization_id, conversation_turn_id=current_turn_id)
    _Repository.decision = SimpleNamespace(
        interaction_decision_id=uuid.uuid4(),
        organization_id=organization_id,
        conversation_id=conversation_id,
        conversation_turn_id=current_turn_id,
        intent="citation_request",
        referenced_turn_ids=[str(referenced_turn_id)],
    )
    monkeypatch.setattr(runtime, "AssistantRepository", _Repository)
    monkeypatch.setattr(runtime, "resolve_interaction_execution_directive", lambda *args, **kwargs: directive)

    with pytest.raises(runtime.ConversationNoSearchExecutionError, match="authorized organization scope"):
        runtime.build_persisted_citation_response_runtime(
            _FakeDb([]),
            organization_id=organization_id,
            conversation_turn_id=current_turn_id,
        )


def test_conversation_summary_uses_only_persisted_referenced_turns(monkeypatch: Any) -> None:
    organization_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    current_turn_id = uuid.uuid4()
    user_turn_id = uuid.uuid4()
    assistant_turn_id = uuid.uuid4()
    directive = _directive(
        organization_id=organization_id,
        conversation_turn_id=current_turn_id,
        planned_action="summarize_conversation_evidence",
    )
    _Repository.decision = SimpleNamespace(
        interaction_decision_id=uuid.uuid4(),
        organization_id=organization_id,
        conversation_id=conversation_id,
        conversation_turn_id=current_turn_id,
        intent="conversation_summary",
        referenced_turn_ids=[str(user_turn_id), str(assistant_turn_id)],
    )
    records = [
        SimpleNamespace(
            conversation_turn_id=user_turn_id,
            organization_id=organization_id,
            conversation_id=conversation_id,
            turn_role="user",
            input_text="What changed?",
            output_text=None,
            ordered_citations=[],
        ),
        SimpleNamespace(
            conversation_turn_id=assistant_turn_id,
            organization_id=organization_id,
            conversation_id=conversation_id,
            turn_role="assistant",
            input_text=None,
            output_text="The runtime now persists the plan.",
            ordered_citations=[{"document_id": "doc-1"}],
        ),
    ]
    monkeypatch.setattr(runtime, "AssistantRepository", _Repository)
    monkeypatch.setattr(runtime, "resolve_interaction_execution_directive", lambda *args, **kwargs: directive)

    result = runtime.build_conversation_summary_response_runtime(
        _FakeDb(records),
        organization_id=organization_id,
        conversation_turn_id=current_turn_id,
    )

    assert result["planned_action"] == "summarize_conversation_evidence"
    assert result["intent"] == "conversation_summary"
    assert result["referenced_turn_ids"] == [str(user_turn_id), str(assistant_turn_id)]
    assert result["evidence_turn_ids"] == [str(user_turn_id), str(assistant_turn_id)]
    assert "- user: What changed?" in result["response_text"]
    assert "- assistant: The runtime now persists the plan." in result["response_text"]
    assert result["ordered_citations"] == [{"document_id": "doc-1"}]
    assert result["generation_required"] is True
    assert result["generation_mode"] == "deterministic_persisted_evidence"
    assert result["enterprise_search_bypassed"] is True
    assert result["llm_used"] is False
    assert result["provider_called"] is False


def test_conversation_summary_does_not_search_when_no_history_is_available(monkeypatch: Any) -> None:
    organization_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    current_turn_id = uuid.uuid4()
    directive = _directive(
        organization_id=organization_id,
        conversation_turn_id=current_turn_id,
        planned_action="summarize_conversation_evidence",
    )
    _Repository.decision = SimpleNamespace(
        interaction_decision_id=uuid.uuid4(),
        organization_id=organization_id,
        conversation_id=conversation_id,
        conversation_turn_id=current_turn_id,
        intent="conversation_summary",
        referenced_turn_ids=[],
    )
    monkeypatch.setattr(runtime, "AssistantRepository", _Repository)
    monkeypatch.setattr(runtime, "resolve_interaction_execution_directive", lambda *args, **kwargs: directive)

    result = runtime.build_conversation_summary_response_runtime(
        _FakeDb([]),
        organization_id=organization_id,
        conversation_turn_id=current_turn_id,
    )

    assert result["response_text"] == "No persisted conversation evidence is available to summarize."
    assert result["enterprise_search_required"] is False
    assert result["enterprise_search_bypassed"] is True
    assert result["llm_used"] is False


def test_response_refinement_shortens_only_persisted_prior_assistant_response(monkeypatch: Any) -> None:
    organization_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    current_turn_id = uuid.uuid4()
    prior_turn_id = uuid.uuid4()
    directive = _directive(
        organization_id=organization_id,
        conversation_turn_id=current_turn_id,
        planned_action="refine_prior_response",
    )
    _Repository.decision = SimpleNamespace(
        interaction_decision_id=uuid.uuid4(),
        organization_id=organization_id,
        conversation_id=conversation_id,
        conversation_turn_id=current_turn_id,
        intent="response_refinement",
        referenced_turn_ids=[str(prior_turn_id)],
    )
    _Repository.current_turn = SimpleNamespace(
        conversation_turn_id=current_turn_id,
        organization_id=organization_id,
        conversation_id=conversation_id,
        turn_role="user",
        input_text="Hazlo más corto",
    )
    prior_text = " ".join(f"word{index}" for index in range(60))
    prior_turn = SimpleNamespace(
        conversation_turn_id=prior_turn_id,
        organization_id=organization_id,
        conversation_id=conversation_id,
        turn_role="assistant",
        input_text=None,
        output_text=prior_text,
        response_format="markdown",
        ordered_citations=[{"document_id": "doc-1"}],
    )
    monkeypatch.setattr(runtime, "AssistantRepository", _Repository)
    monkeypatch.setattr(runtime, "resolve_interaction_execution_directive", lambda *args, **kwargs: directive)

    result = runtime.build_response_refinement_runtime(
        _FakeDb([prior_turn]),
        organization_id=organization_id,
        conversation_turn_id=current_turn_id,
    )

    assert result["planned_action"] == "refine_prior_response"
    assert result["refinement_mode"] == "shorten"
    assert result["deterministic_response"] is True
    assert result["configured_generation_required"] is False
    assert result["generation_mode"] == "deterministic_shorten_persisted_response"
    assert result["response_text"].endswith("…")
    assert len(result["response_text"].split()) < len(prior_text.split())
    assert result["ordered_citations"] == [{"document_id": "doc-1"}]
    assert result["enterprise_search_bypassed"] is True
    assert result["llm_used"] is False


def test_response_refinement_requires_configured_generation_for_non_deterministic_transform(monkeypatch: Any) -> None:
    organization_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    current_turn_id = uuid.uuid4()
    prior_turn_id = uuid.uuid4()
    directive = _directive(
        organization_id=organization_id,
        conversation_turn_id=current_turn_id,
        planned_action="refine_prior_response",
    )
    _Repository.decision = SimpleNamespace(
        interaction_decision_id=uuid.uuid4(),
        organization_id=organization_id,
        conversation_id=conversation_id,
        conversation_turn_id=current_turn_id,
        intent="response_refinement",
        referenced_turn_ids=[str(prior_turn_id)],
    )
    _Repository.current_turn = SimpleNamespace(
        conversation_turn_id=current_turn_id,
        organization_id=organization_id,
        conversation_id=conversation_id,
        turn_role="user",
        input_text="Tradúcelo al inglés",
    )
    prior_turn = SimpleNamespace(
        conversation_turn_id=prior_turn_id,
        organization_id=organization_id,
        conversation_id=conversation_id,
        turn_role="assistant",
        input_text=None,
        output_text="Respuesta persistida.",
        response_format="markdown",
        ordered_citations=[],
    )
    monkeypatch.setattr(runtime, "AssistantRepository", _Repository)
    monkeypatch.setattr(runtime, "resolve_interaction_execution_directive", lambda *args, **kwargs: directive)

    result = runtime.build_response_refinement_runtime(
        _FakeDb([prior_turn]),
        organization_id=organization_id,
        conversation_turn_id=current_turn_id,
    )

    assert result["refinement_mode"] is None
    assert result["response_text"] is None
    assert result["configured_generation_required"] is True
    assert result["generation_mode"] == "configured_generation_required"
    assert result["deterministic_response"] is False
    assert result["enterprise_search_bypassed"] is True
    assert result["provider_called"] is False


def test_response_refinement_rejects_non_assistant_reference(monkeypatch: Any) -> None:
    organization_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    current_turn_id = uuid.uuid4()
    prior_turn_id = uuid.uuid4()
    directive = _directive(
        organization_id=organization_id,
        conversation_turn_id=current_turn_id,
        planned_action="refine_prior_response",
    )
    _Repository.decision = SimpleNamespace(
        interaction_decision_id=uuid.uuid4(),
        organization_id=organization_id,
        conversation_id=conversation_id,
        conversation_turn_id=current_turn_id,
        intent="response_refinement",
        referenced_turn_ids=[str(prior_turn_id)],
    )
    _Repository.current_turn = SimpleNamespace(
        conversation_turn_id=current_turn_id,
        organization_id=organization_id,
        conversation_id=conversation_id,
        turn_role="user",
        input_text="Hazlo más corto",
    )
    prior_turn = SimpleNamespace(
        conversation_turn_id=prior_turn_id,
        organization_id=organization_id,
        conversation_id=conversation_id,
        turn_role="user",
        input_text="Prior user message",
        output_text=None,
        response_format="markdown",
        ordered_citations=[],
    )
    monkeypatch.setattr(runtime, "AssistantRepository", _Repository)
    monkeypatch.setattr(runtime, "resolve_interaction_execution_directive", lambda *args, **kwargs: directive)

    with pytest.raises(runtime.ConversationNoSearchExecutionError, match="prior assistant response"):
        runtime.build_response_refinement_runtime(
            _FakeDb([prior_turn]),
            organization_id=organization_id,
            conversation_turn_id=current_turn_id,
        )
