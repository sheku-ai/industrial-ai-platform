from __future__ import annotations

import uuid
from types import SimpleNamespace

from app.services import conversation_interaction_runtime


def _configuration(**overrides):
    values = {
        "routing_configuration_id": uuid.uuid4(),
        "configuration_version": "conversation-routing.v2",
        "configuration_hash": "a" * 64,
        "intent_catalog": [{"intent": "knowledge_query", "enabled": True}],
        "provider_chain": [
            {"provider": "community.setfit", "enabled": True, "required": False},
        ],
        "confidence_thresholds": {"minimum_confidence": 0.65},
        "fallback_behavior": {
            "intent": "knowledge_query",
            "provider": "system.safe_fallback",
            "target_runtime": "assistant.enterprise_search",
        },
        "semantic_configuration": {
            "provider": "community.setfit",
            "local_files_only": True,
            "embedding_infrastructure_required": False,
            "slm_required": False,
        },
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _context(**overrides):
    organization_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    turn_id = uuid.uuid4()
    values = {
        "organization_id": organization_id,
        "conversation_id": conversation_id,
        "conversation_turn_id": turn_id,
        "conversation_context_package_id": uuid.uuid4(),
        "context_hash": "c" * 64,
        "current_user_message": "Who approves this request?",
        "included_turn_ids": [],
        "retrieval_inputs": {
            "current_user_message": "Who approves this request?",
            "conversation_history": [
                {
                    "conversation_turn_id": str(uuid.uuid4()),
                    "turn_index": 1,
                    "turn_role": "assistant",
                    "content": "The request requires an approval step.",
                }
            ],
        },
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _input_hash(*, organization_id, context, configuration):
    payload = conversation_interaction_runtime._effective_routing_input_payload(
        organization_id=organization_id,
        context_package=context,
        configuration=configuration,
    )
    return conversation_interaction_runtime._canonical_hash(payload)


def test_effective_routing_input_hash_is_stable_for_same_evidence() -> None:
    context = _context()
    configuration = _configuration()

    first = _input_hash(
        organization_id=context.organization_id,
        context=context,
        configuration=configuration,
    )
    second = _input_hash(
        organization_id=context.organization_id,
        context=context,
        configuration=configuration,
    )

    assert first == second
    assert len(first) == 64


def test_input_hash_changes_when_persisted_context_identity_changes() -> None:
    context = _context()
    configuration = _configuration()
    original = _input_hash(
        organization_id=context.organization_id,
        context=context,
        configuration=configuration,
    )

    changed_context = _context(
        organization_id=context.organization_id,
        conversation_id=context.conversation_id,
        conversation_turn_id=context.conversation_turn_id,
        conversation_context_package_id=context.conversation_context_package_id,
        context_hash="d" * 64,
        retrieval_inputs={
            "current_user_message": "Who approves this request?",
            "conversation_history": [
                {
                    "conversation_turn_id": str(uuid.uuid4()),
                    "turn_index": 1,
                    "turn_role": "assistant",
                    "content": "A different persisted answer participates in routing.",
                }
            ],
        },
    )
    changed = _input_hash(
        organization_id=context.organization_id,
        context=changed_context,
        configuration=configuration,
    )

    assert changed != original


def test_decision_input_hash_does_not_reinterpret_free_text() -> None:
    context = _context()
    configuration = _configuration()
    baseline = _input_hash(
        organization_id=context.organization_id,
        context=context,
        configuration=configuration,
    )
    changed_text = _context(
        organization_id=context.organization_id,
        conversation_id=context.conversation_id,
        conversation_turn_id=context.conversation_turn_id,
        conversation_context_package_id=context.conversation_context_package_id,
        context_hash=context.context_hash,
        current_user_message="unrelated free text",
        retrieval_inputs={
            "current_user_message": "unrelated free text",
            "conversation_history": [{"content": "different free text"}],
        },
    )

    assert (
        _input_hash(
            organization_id=context.organization_id,
            context=changed_text,
            configuration=configuration,
        )
        == baseline
    )


def test_input_hash_changes_when_effective_configuration_changes() -> None:
    context = _context()
    configuration = _configuration()
    original = _input_hash(
        organization_id=context.organization_id,
        context=context,
        configuration=configuration,
    )

    changed_configuration = _configuration(
        routing_configuration_id=configuration.routing_configuration_id,
        configuration_hash=configuration.configuration_hash,
        confidence_thresholds={"minimum_confidence": 0.95},
    )
    changed = _input_hash(
        organization_id=context.organization_id,
        context=context,
        configuration=changed_configuration,
    )

    assert changed != original


def test_decision_hash_is_stable_for_same_decision_payload() -> None:
    context = _context()
    configuration = _configuration()
    input_hash = _input_hash(
        organization_id=context.organization_id,
        context=context,
        configuration=configuration,
    )
    evidence = SimpleNamespace(
        classification_evidence_id=uuid.uuid4(),
        organization_id=context.organization_id,
        conversation_id=context.conversation_id,
        conversation_turn_id=context.conversation_turn_id,
        conversation_context_package_id=context.conversation_context_package_id,
        predicted_intent="knowledge_query",
        predicted_sub_intent=None,
        predicted_parameters={},
        confidence=0.82,
        resolution_method="community.setfit.classification",
        resolution_provider="community.setfit",
    )
    payload = conversation_interaction_runtime._classification_evidence_decision_payload(
        classification_evidence=evidence,
        context_package=context,
        input_hash=input_hash,
    )

    first = conversation_interaction_runtime._canonical_hash(
        conversation_interaction_runtime._decision_hash_payload(payload)
    )
    second = conversation_interaction_runtime._canonical_hash(
        conversation_interaction_runtime._decision_hash_payload(dict(payload))
    )

    assert first == second
    assert len(first) == 64


def test_decision_hash_canonicalizes_only_classification_evidence_uuid() -> None:
    classification_evidence_id = uuid.uuid4()
    payload = {
        "classification_evidence_id": classification_evidence_id,
        "intent": "response_refinement",
        "intent_parameters": {"structured": True},
    }

    canonical_payload = conversation_interaction_runtime._decision_hash_payload(payload)
    decision_hash = conversation_interaction_runtime._canonical_hash(canonical_payload)

    assert payload["classification_evidence_id"] is classification_evidence_id
    assert canonical_payload["classification_evidence_id"] == str(classification_evidence_id)
    assert len(decision_hash) == 64


def test_decision_hash_changes_with_structured_classification_fields() -> None:
    baseline = {
        "classification_evidence_id": uuid.uuid4(),
        "intent": "response_refinement",
        "sub_intent": None,
        "intent_parameters": {},
    }

    def digest(payload):
        return conversation_interaction_runtime._canonical_hash(
            conversation_interaction_runtime._decision_hash_payload(payload)
        )

    baseline_hash = digest(baseline)

    assert digest(dict(baseline)) == baseline_hash
    assert digest({**baseline, "classification_evidence_id": uuid.uuid4()}) != baseline_hash
    assert digest({**baseline, "intent": "knowledge_query"}) != baseline_hash
    assert digest({**baseline, "sub_intent": "structured-sub-intent"}) != baseline_hash
    assert digest({**baseline, "intent_parameters": {"structured": True}}) != baseline_hash


def test_persisted_decision_is_reused_before_recomputing_routing(monkeypatch) -> None:
    organization_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    turn_id = uuid.uuid4()
    context_package_id = uuid.uuid4()
    persisted = SimpleNamespace(
        conversation_turn_id=turn_id,
        organization_id=organization_id,
        conversation_id=conversation_id,
        conversation_context_package_id=context_package_id,
    )
    context = SimpleNamespace(
        conversation_turn_id=turn_id,
        organization_id=organization_id,
        conversation_id=conversation_id,
        conversation_context_package_id=context_package_id,
    )

    class _Repository:
        def __init__(self, session) -> None:
            self.session = session

        def get_scoped_conversation_interaction_decision(self, *, conversation_turn_id, organization_id):
            assert conversation_turn_id == turn_id
            assert organization_id == persisted.organization_id
            return persisted

        def get_scoped_conversation_context_package(self, **kwargs):
            return context

    monkeypatch.setattr(conversation_interaction_runtime, "AssistantRepository", _Repository)
    monkeypatch.setattr(
        conversation_interaction_runtime,
        "resolve_conversation_intent_classification",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("persisted decision must not be reclassified")),
    )
    monkeypatch.setattr(
        conversation_interaction_runtime,
        "resolve_persisted_interaction_plan",
        lambda *args, **kwargs: SimpleNamespace(),
    )

    result = conversation_interaction_runtime.resolve_interaction_decision(
        object(),
        conversation_turn_id=turn_id,
        organization_id=organization_id,
    )

    assert result is persisted
