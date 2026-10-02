import uuid
from types import SimpleNamespace

import pytest

from app.services import conversation_interaction_runtime


def _context_package():
    return SimpleNamespace(
        organization_id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        conversation_turn_id=uuid.uuid4(),
        conversation_context_package_id=uuid.uuid4(),
        included_turn_ids=["u1", "a1", "u2", "a2"],
        retrieval_inputs={
            "current_user_message": "current",
            "conversation_history": [
                {"conversation_turn_id": "u1", "turn_role": "user", "content": "first question"},
                {"conversation_turn_id": "a1", "turn_role": "assistant", "content": "first answer"},
                {"conversation_turn_id": "u2", "turn_role": "user", "content": "follow up"},
                {"conversation_turn_id": "a2", "turn_role": "assistant", "content": "second answer"},
            ],
        },
    )


def _fallback_configuration():
    return SimpleNamespace(
        fallback_behavior={
            "intent": "conversation_summary",
            "provider": "system.safe_fallback",
            "target_runtime": "assistant.enterprise_search",
        },
        intent_catalog=[
            {"intent": intent, "enabled": True} for intent in conversation_interaction_runtime.INITIAL_INTENTS
        ],
    )


@pytest.mark.parametrize(
    ("intent", "context_required", "retrieval_required", "generation_required"),
    [
        ("knowledge_query", False, True, True),
        ("contextual_follow_up", True, True, True),
        ("new_topic", False, True, True),
        ("response_refinement", True, False, True),
        ("citation_request", True, False, True),
        ("conversation_summary", True, False, True),
        ("non_knowledge_interaction", False, False, False),
    ],
)
def test_all_initial_intents_have_explicit_routing_semantics(
    intent,
    context_required,
    retrieval_required,
    generation_required,
) -> None:
    assert conversation_interaction_runtime._routing_semantics(intent) == (
        context_required,
        retrieval_required,
        generation_required,
    )


def test_conversation_summary_references_full_persisted_context_window() -> None:
    assert conversation_interaction_runtime._referenced_turn_ids_for_intent(
        intent="conversation_summary",
        context_package=_context_package(),
    ) == ["u1", "a1", "u2", "a2"]


@pytest.mark.parametrize("intent", ["citation_request", "response_refinement"])
def test_citation_and_refinement_reference_latest_assistant_turn(intent) -> None:
    assert conversation_interaction_runtime._referenced_turn_ids_for_intent(
        intent=intent,
        context_package=_context_package(),
    ) == ["a2"]


def test_contextual_follow_up_references_minimum_recent_context() -> None:
    assert conversation_interaction_runtime._referenced_turn_ids_for_intent(
        intent="contextual_follow_up",
        context_package=_context_package(),
    ) == ["u2", "a2"]


@pytest.mark.parametrize("intent", ["knowledge_query", "new_topic", "non_knowledge_interaction"])
def test_non_contextual_intents_do_not_reference_prior_turns(intent) -> None:
    assert (
        conversation_interaction_runtime._referenced_turn_ids_for_intent(
            intent=intent,
            context_package=_context_package(),
        )
        == []
    )


def test_classification_evidence_payload_uses_intent_specific_evidence() -> None:
    context = _context_package()
    evidence = SimpleNamespace(
        classification_evidence_id=uuid.uuid4(),
        organization_id=context.organization_id,
        conversation_id=context.conversation_id,
        conversation_turn_id=context.conversation_turn_id,
        conversation_context_package_id=context.conversation_context_package_id,
        predicted_intent="citation_request",
        predicted_sub_intent=None,
        predicted_parameters={},
        confidence=0.99,
        resolution_method="community.setfit.classification",
        resolution_provider="community.setfit",
    )
    payload = conversation_interaction_runtime._classification_evidence_decision_payload(
        classification_evidence=evidence,
        context_package=context,
        input_hash="i" * 64,
    )

    assert payload["referenced_turn_ids"] == ["a2"]
    assert payload["conversation_context_required"] is True
    assert payload["retrieval_required"] is False
    assert payload["generation_required"] is True
    assert payload["resolution_provider"] == "community.setfit"
    assert payload["embedding_used"] is False
    assert payload["slm_used"] is False


def test_fallback_payload_uses_same_intent_evidence_semantics() -> None:
    payload = conversation_interaction_runtime._fallback_decision_payload(
        configuration=_fallback_configuration(),
        context_package=_context_package(),
        input_hash="i" * 64,
    )

    assert payload["referenced_turn_ids"] == ["u1", "a1", "u2", "a2"]
    assert payload["conversation_context_required"] is True
    assert payload["retrieval_required"] is False
    assert payload["generation_required"] is True
    assert payload["resolution_provider"] == "system.safe_fallback"
