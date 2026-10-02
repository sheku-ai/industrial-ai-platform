from types import SimpleNamespace

from app.services import conversation_interaction_runtime


def _configuration(**fallback_behavior):
    return SimpleNamespace(
        fallback_behavior=fallback_behavior,
        intent_catalog=[
            {"intent": intent, "enabled": True} for intent in conversation_interaction_runtime.INITIAL_INTENTS
        ],
    )


def _context(*included_turn_ids):
    return SimpleNamespace(included_turn_ids=list(included_turn_ids), retrieval_inputs={"conversation_history": []})


def test_fallback_uses_persisted_intent_and_runtime_with_safe_provider() -> None:
    payload = conversation_interaction_runtime._fallback_decision_payload(
        configuration=_configuration(
            intent="conversation_summary",
            provider="legacy.provider.is.ignored",
            target_runtime="assistant.conversation",
        ),
        context_package=_context("turn-1", "turn-2"),
        input_hash="a" * 64,
    )

    assert payload["intent"] == "conversation_summary"
    assert payload["resolution_method"] == "configured.fallback"
    assert payload["resolution_provider"] == "system.safe_fallback"
    assert payload["target_runtime"] == "assistant.conversation"
    assert payload["conversation_context_required"] is True
    assert payload["retrieval_required"] is False
    assert payload["generation_required"] is True
    assert payload["referenced_turn_ids"] == ["turn-1", "turn-2"]
    assert payload["embedding_used"] is False
    assert payload["slm_used"] is False


def test_fallback_knowledge_query_preserves_enterprise_search_compatibility() -> None:
    payload = conversation_interaction_runtime._fallback_decision_payload(
        configuration=_configuration(
            intent="knowledge_query",
            provider="system.safe_fallback",
            target_runtime="assistant.enterprise_search",
        ),
        context_package=_context("turn-1"),
        input_hash="b" * 64,
    )

    assert payload["intent"] == "knowledge_query"
    assert payload["conversation_context_required"] is False
    assert payload["retrieval_required"] is True
    assert payload["generation_required"] is True
    assert payload["referenced_turn_ids"] == []
    assert payload["resolution_provider"] == "system.safe_fallback"


def test_fallback_non_knowledge_disables_retrieval_and_generation() -> None:
    payload = conversation_interaction_runtime._fallback_decision_payload(
        configuration=_configuration(
            intent="non_knowledge_interaction",
            provider="system.safe_fallback",
            target_runtime="assistant.enterprise_search",
        ),
        context_package=_context(),
        input_hash="c" * 64,
    )

    assert payload["retrieval_required"] is False
    assert payload["generation_required"] is False
    assert payload["conversation_context_required"] is False


def test_invalid_fallback_values_degrade_to_safe_defaults() -> None:
    payload = conversation_interaction_runtime._fallback_decision_payload(
        configuration=_configuration(
            intent="unknown_intent",
            provider="unknown.provider",
            target_runtime="",
        ),
        context_package=_context(),
        input_hash="d" * 64,
    )

    assert payload["intent"] == "knowledge_query"
    assert payload["resolution_provider"] == "system.safe_fallback"
    assert payload["target_runtime"] == "assistant.enterprise_search"
    assert payload["retrieval_required"] is True
