from __future__ import annotations

from types import SimpleNamespace

from app.services import conversation_interaction_runtime


def _configuration(*, enabled_intents: set[str], fallback_intent: str = "knowledge_query"):
    return SimpleNamespace(
        intent_catalog=[
            {"intent": intent, "enabled": intent in enabled_intents}
            for intent in conversation_interaction_runtime.INITIAL_INTENTS
        ],
        fallback_behavior={
            "intent": fallback_intent,
            "provider": "system.safe_fallback",
            "target_runtime": "assistant.enterprise_search",
        },
    )


def _context():
    return SimpleNamespace(
        included_turn_ids=["user-1", "assistant-1"],
        retrieval_inputs={
            "conversation_history": [
                {"conversation_turn_id": "user-1", "turn_role": "user"},
                {"conversation_turn_id": "assistant-1", "turn_role": "assistant"},
            ],
        },
    )


def test_fallback_cannot_select_disabled_intent() -> None:
    payload = conversation_interaction_runtime._fallback_decision_payload(
        configuration=_configuration(
            enabled_intents={"knowledge_query", "non_knowledge_interaction"},
            fallback_intent="citation_request",
        ),
        context_package=_context(),
        input_hash="a" * 64,
    )

    assert payload["classification_evidence_id"] is None
    assert payload["intent"] == "knowledge_query"
    assert payload["resolution_method"] == "configured.fallback"
    assert payload["resolution_provider"] == "system.safe_fallback"


def test_empty_catalog_preserves_safe_initial_contract() -> None:
    configuration = SimpleNamespace(intent_catalog=[])

    assert conversation_interaction_runtime._enabled_intents(configuration) == set(
        conversation_interaction_runtime.INITIAL_INTENTS
    )


def test_persisted_citation_evidence_drives_context_semantics() -> None:
    context = SimpleNamespace(
        organization_id="organization",
        conversation_id="conversation",
        conversation_turn_id="turn",
        conversation_context_package_id="context",
        included_turn_ids=["user-1", "assistant-1"],
        retrieval_inputs=_context().retrieval_inputs,
    )
    evidence = SimpleNamespace(
        classification_evidence_id="classification",
        organization_id=context.organization_id,
        conversation_id=context.conversation_id,
        conversation_turn_id=context.conversation_turn_id,
        conversation_context_package_id=context.conversation_context_package_id,
        predicted_intent="citation_request",
        predicted_sub_intent=None,
        predicted_parameters={},
        confidence=0.98,
        resolution_method="community.setfit.classification",
        resolution_provider="community.setfit",
    )

    payload = conversation_interaction_runtime._classification_evidence_decision_payload(
        classification_evidence=evidence,
        context_package=context,
        input_hash="b" * 64,
    )

    assert payload["referenced_turn_ids"] == ["assistant-1"]
    assert payload["conversation_context_required"] is True
    assert payload["retrieval_required"] is False
