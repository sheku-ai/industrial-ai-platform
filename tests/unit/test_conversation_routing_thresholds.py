from __future__ import annotations

from types import SimpleNamespace

from app.services import conversation_interaction_runtime


def test_threshold_remains_persisted_configuration_metadata() -> None:
    payload = conversation_interaction_runtime._default_configuration_payload()

    assert payload["confidence_thresholds"] == {"minimum_confidence": 0.65}


def test_downstream_decision_copies_persisted_confidence_without_reclassification() -> None:
    context = SimpleNamespace(
        organization_id="organization",
        conversation_id="conversation",
        conversation_turn_id="turn",
        conversation_context_package_id="context",
        included_turn_ids=[],
        retrieval_inputs={"conversation_history": []},
    )
    evidence = SimpleNamespace(
        classification_evidence_id="classification",
        organization_id=context.organization_id,
        conversation_id=context.conversation_id,
        conversation_turn_id=context.conversation_turn_id,
        conversation_context_package_id=context.conversation_context_package_id,
        predicted_intent="knowledge_query",
        predicted_sub_intent=None,
        predicted_parameters={},
        confidence=0.37,
        resolution_method="community.setfit.classification",
        resolution_provider="community.setfit",
    )

    payload = conversation_interaction_runtime._classification_evidence_decision_payload(
        classification_evidence=evidence,
        context_package=context,
        input_hash="i" * 64,
    )

    assert payload["confidence"] == 0.37
    assert payload["intent"] == "knowledge_query"
