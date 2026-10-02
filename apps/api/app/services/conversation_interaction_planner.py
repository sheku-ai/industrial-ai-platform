"""Pure deterministic planning from persisted conversation evidence."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

PLANNER_VERSION = "conversation-interaction-planner.v1"

INTENT_ACTIONS: dict[str, str] = {
    "knowledge_query": "enterprise_search",
    "contextual_follow_up": "contextual_enterprise_search",
    "new_topic": "new_topic_runtime",
    "response_refinement": "refine_prior_response",
    "citation_request": "reuse_persisted_citations",
    "conversation_summary": "summarize_conversation_evidence",
    "non_knowledge_interaction": "deterministic_or_configured_generation",
}


@dataclass(frozen=True)
class InteractionPlanDraft:
    intent: str
    planned_action: str
    target_runtime: str
    context_required: bool
    retrieval_required: bool
    generation_required: bool
    use_persisted_citations: bool
    use_conversation_evidence: bool
    use_conversation_context: bool
    enterprise_search_required: bool
    deterministic_response_allowed: bool
    planner_version: str
    input_hash: str
    plan_hash: str
    plan_metadata: dict[str, Any]


def _canonical_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _effective_input_payload(*, context_package: Any, interaction_decision: Any) -> dict[str, Any]:
    classification_evidence_id = getattr(interaction_decision, "classification_evidence_id", None)
    return {
        "organization_id": str(interaction_decision.organization_id),
        "conversation_id": str(interaction_decision.conversation_id),
        "conversation_turn_id": str(interaction_decision.conversation_turn_id),
        "conversation_context_package_id": str(interaction_decision.conversation_context_package_id),
        "interaction_decision_id": str(interaction_decision.interaction_decision_id),
        "context_hash": str(context_package.context_hash),
        "decision_hash": str(interaction_decision.decision_hash),
        "classification_evidence_id": (
            str(classification_evidence_id) if classification_evidence_id is not None else None
        ),
        "intent": str(interaction_decision.intent),
        "sub_intent": getattr(interaction_decision, "sub_intent", None),
        "intent_parameters": dict(getattr(interaction_decision, "intent_parameters", None) or {}),
        "target_runtime": str(interaction_decision.target_runtime),
        "referenced_turn_ids": list(interaction_decision.referenced_turn_ids or []),
        "conversation_context_required": bool(interaction_decision.conversation_context_required),
        "retrieval_required": bool(interaction_decision.retrieval_required),
        "generation_required": bool(interaction_decision.generation_required),
        "planner_version": PLANNER_VERSION,
    }


def _validate_lineage(*, context_package: Any, interaction_decision: Any) -> None:
    if interaction_decision.organization_id != context_package.organization_id:
        raise ValueError("interaction planner organization lineage is inconsistent")
    if interaction_decision.conversation_id != context_package.conversation_id:
        raise ValueError("interaction planner conversation lineage is inconsistent")
    if interaction_decision.conversation_turn_id != context_package.conversation_turn_id:
        raise ValueError("interaction planner turn lineage is inconsistent")
    if interaction_decision.conversation_context_package_id != context_package.conversation_context_package_id:
        raise ValueError("interaction planner context lineage is inconsistent")


def _planned_action(intent: str) -> str:
    try:
        return INTENT_ACTIONS[intent]
    except KeyError as exc:
        raise ValueError(f"unsupported persisted conversation intent: {intent}") from exc


def _plan_semantics(*, context_package: Any, interaction_decision: Any) -> dict[str, Any]:
    intent = str(interaction_decision.intent)
    planned_action = _planned_action(intent)
    referenced_turn_ids = list(interaction_decision.referenced_turn_ids or [])
    included_turn_ids = list(context_package.included_turn_ids or [])

    context_required = bool(interaction_decision.conversation_context_required)
    retrieval_required = bool(interaction_decision.retrieval_required)
    generation_required = bool(interaction_decision.generation_required)

    use_persisted_citations = intent == "citation_request"
    use_conversation_evidence = intent in {
        "citation_request",
        "conversation_summary",
        "response_refinement",
        "contextual_follow_up",
    }
    use_conversation_context = context_required and bool(included_turn_ids or referenced_turn_ids)
    enterprise_search_required = retrieval_required
    deterministic_response_allowed = intent == "non_knowledge_interaction" and not generation_required

    if intent == "citation_request":
        enterprise_search_required = False
        retrieval_required = False
    elif intent == "conversation_summary":
        enterprise_search_required = False
        retrieval_required = False
    elif intent == "response_refinement" and not bool(interaction_decision.retrieval_required):
        enterprise_search_required = False
    elif intent == "non_knowledge_interaction":
        enterprise_search_required = False
        retrieval_required = False

    return {
        "intent": intent,
        "planned_action": planned_action,
        "target_runtime": str(interaction_decision.target_runtime),
        "context_required": context_required,
        "retrieval_required": retrieval_required,
        "generation_required": generation_required,
        "use_persisted_citations": use_persisted_citations,
        "use_conversation_evidence": use_conversation_evidence,
        "use_conversation_context": use_conversation_context,
        "enterprise_search_required": enterprise_search_required,
        "deterministic_response_allowed": deterministic_response_allowed,
    }


def build_interaction_plan(*, context_package: Any, interaction_decision: Any) -> InteractionPlanDraft:
    """Build a plan without executing retrieval, generation, tools, or workflows."""
    _validate_lineage(context_package=context_package, interaction_decision=interaction_decision)
    input_payload = _effective_input_payload(
        context_package=context_package,
        interaction_decision=interaction_decision,
    )
    input_hash = _canonical_hash(input_payload)
    semantics = _plan_semantics(
        context_package=context_package,
        interaction_decision=interaction_decision,
    )
    classification_evidence_id = getattr(interaction_decision, "classification_evidence_id", None)
    plan_metadata = {
        "source": "persisted_evidence",
        "planned_action": semantics["planned_action"],
        "intent": semantics["intent"],
        "context_hash": str(context_package.context_hash),
        "decision_hash": str(interaction_decision.decision_hash),
        "classification_evidence_id": (
            str(classification_evidence_id) if classification_evidence_id is not None else None
        ),
        "sub_intent": getattr(interaction_decision, "sub_intent", None),
        "intent_parameters": dict(getattr(interaction_decision, "intent_parameters", None) or {}),
        "referenced_turn_ids": list(interaction_decision.referenced_turn_ids or []),
        "included_turn_ids": list(context_package.included_turn_ids or []),
    }
    plan_payload = {
        **semantics,
        "planner_version": PLANNER_VERSION,
        "input_hash": input_hash,
        "plan_metadata": plan_metadata,
    }
    return InteractionPlanDraft(
        **semantics,
        planner_version=PLANNER_VERSION,
        input_hash=input_hash,
        plan_hash=_canonical_hash(plan_payload),
        plan_metadata=plan_metadata,
    )
