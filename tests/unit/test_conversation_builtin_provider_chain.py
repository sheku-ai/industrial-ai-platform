from __future__ import annotations

import uuid
from types import SimpleNamespace

from app.services import conversation_interaction_runtime


def _context() -> SimpleNamespace:
    organization_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    conversation_turn_id = uuid.uuid4()
    context_package_id = uuid.uuid4()
    return SimpleNamespace(
        organization_id=organization_id,
        conversation_id=conversation_id,
        conversation_turn_id=conversation_turn_id,
        conversation_context_package_id=context_package_id,
        included_turn_ids=[],
        retrieval_inputs={
            "current_user_message": "free text is not classified in decision runtime",
            "conversation_history": [],
        },
    )


def test_interaction_runtime_has_no_direct_intent_engine_boundary() -> None:
    assert not hasattr(conversation_interaction_runtime, "classify_intent")
    assert not hasattr(conversation_interaction_runtime, "_resolve_configured_intent_candidate")


def test_decision_payload_consumes_persisted_classification_evidence_only() -> None:
    context = _context()
    evidence = SimpleNamespace(
        classification_evidence_id=uuid.uuid4(),
        organization_id=context.organization_id,
        conversation_id=context.conversation_id,
        conversation_turn_id=context.conversation_turn_id,
        conversation_context_package_id=context.conversation_context_package_id,
        predicted_intent="response_refinement",
        predicted_sub_intent="structured-sub-intent",
        predicted_parameters={"structured": True},
        confidence=0.92,
        resolution_method="community.setfit.classification",
        resolution_provider="community.setfit",
    )

    payload = conversation_interaction_runtime._classification_evidence_decision_payload(
        classification_evidence=evidence,
        context_package=context,
        input_hash="i" * 64,
    )

    assert payload["classification_evidence_id"] == evidence.classification_evidence_id
    assert payload["intent"] == evidence.predicted_intent
    assert payload["sub_intent"] == evidence.predicted_sub_intent
    assert payload["intent_parameters"] == evidence.predicted_parameters
    assert payload["confidence"] == evidence.confidence
    assert payload["resolution_provider"] == evidence.resolution_provider
    assert payload["embedding_used"] is False
    assert payload["slm_used"] is False
