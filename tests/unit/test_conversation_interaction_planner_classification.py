from __future__ import annotations

import uuid
from types import SimpleNamespace

from app.services import conversation_interaction_planner
from app.services.conversation_interaction_planner import build_interaction_plan


def _evidence(*, sub_intent: str | None = None, intent_parameters: dict | None = None):
    organization_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    conversation_turn_id = uuid.uuid4()
    context_package_id = uuid.uuid4()
    classification_evidence_id = uuid.uuid4()
    context = SimpleNamespace(
        organization_id=organization_id,
        conversation_id=conversation_id,
        conversation_turn_id=conversation_turn_id,
        conversation_context_package_id=context_package_id,
        context_hash="c" * 64,
        current_user_message="original text is not planner input",
        included_turn_ids=[],
    )
    decision = SimpleNamespace(
        interaction_decision_id=uuid.uuid4(),
        organization_id=organization_id,
        conversation_id=conversation_id,
        conversation_turn_id=conversation_turn_id,
        conversation_context_package_id=context_package_id,
        classification_evidence_id=classification_evidence_id,
        intent="response_refinement",
        sub_intent=sub_intent,
        intent_parameters=dict(intent_parameters or {}),
        target_runtime="assistant.enterprise_search",
        referenced_turn_ids=[],
        conversation_context_required=True,
        retrieval_required=False,
        generation_required=True,
        decision_hash="d" * 64,
    )
    return context, decision


def test_plan_hash_changes_when_structured_classification_changes() -> None:
    context, decision = _evidence(
        sub_intent="structured-sub-intent",
        intent_parameters={"structured": True},
    )
    baseline = build_interaction_plan(context_package=context, interaction_decision=decision)

    changed_sub_intent = SimpleNamespace(**{**vars(decision), "sub_intent": "other-structured-sub-intent"})
    changed_parameters = SimpleNamespace(**{**vars(decision), "intent_parameters": {"structured": False}})
    changed_intent = SimpleNamespace(
        **{
            **vars(decision),
            "intent": "knowledge_query",
            "conversation_context_required": False,
            "retrieval_required": True,
        }
    )

    sub_intent_plan = build_interaction_plan(
        context_package=context,
        interaction_decision=changed_sub_intent,
    )
    parameters_plan = build_interaction_plan(
        context_package=context,
        interaction_decision=changed_parameters,
    )
    intent_plan = build_interaction_plan(
        context_package=context,
        interaction_decision=changed_intent,
    )

    assert sub_intent_plan.input_hash != baseline.input_hash
    assert sub_intent_plan.plan_hash != baseline.plan_hash
    assert parameters_plan.input_hash != baseline.input_hash
    assert parameters_plan.plan_hash != baseline.plan_hash
    assert intent_plan.input_hash != baseline.input_hash
    assert intent_plan.plan_hash != baseline.plan_hash


def test_plan_metadata_carries_classification_identity_and_structured_fields() -> None:
    context, decision = _evidence(
        sub_intent="structured-sub-intent",
        intent_parameters={"structured": True},
    )

    plan = build_interaction_plan(context_package=context, interaction_decision=decision)

    assert plan.plan_metadata["classification_evidence_id"] == str(decision.classification_evidence_id)
    assert plan.plan_metadata["intent"] == "response_refinement"
    assert plan.plan_metadata["sub_intent"] == "structured-sub-intent"
    assert plan.plan_metadata["intent_parameters"] == {"structured": True}


def test_planner_does_not_reinterpret_conversation_text() -> None:
    context, decision = _evidence(sub_intent="structured-sub-intent")
    baseline = build_interaction_plan(context_package=context, interaction_decision=decision)
    changed_text_context = SimpleNamespace(**{**vars(context), "current_user_message": "completely different wording"})

    changed = build_interaction_plan(
        context_package=changed_text_context,
        interaction_decision=decision,
    )

    assert changed.input_hash == baseline.input_hash
    assert changed.plan_hash == baseline.plan_hash
    assert not hasattr(conversation_interaction_planner, "classify_intent")
