"""Authoritative persisted Conversation interaction decisions."""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.assistant_runtime import ConversationInteractionDecision, ConversationRoutingConfiguration
from app.repositories.assistant import AssistantRepository
from app.services.conversation_context_runtime import resolve_conversation_context_package
from app.services.conversation_intent_classification_runtime import resolve_conversation_intent_classification
from app.services.conversation_intent_engine import COMMUNITY_INTENT_PROVIDER
from app.services.conversation_interaction_plan_runtime import resolve_persisted_interaction_plan

ROUTING_CONFIGURATION_VERSION = "conversation-routing.v2"
ROUTER_VERSION = "conversation-router.contract.v2"
DECISION_IDEMPOTENCY_CONSTRAINT = "uq_ai_conversation_interaction_decisions_org_turn"
INITIAL_INTENTS = (
    "knowledge_query",
    "contextual_follow_up",
    "new_topic",
    "response_refinement",
    "citation_request",
    "conversation_summary",
    "non_knowledge_interaction",
)
ROUTING_PROVIDERS = (COMMUNITY_INTENT_PROVIDER,)


def _canonical_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _integrity_constraint_name(exc: IntegrityError) -> str | None:
    diag = getattr(exc.orig, "diag", None)
    return getattr(diag, "constraint_name", None)


def _decision_hash_payload(decision_payload: dict[str, Any]) -> dict[str, Any]:
    classification_evidence_id = decision_payload.get("classification_evidence_id")
    return {
        **decision_payload,
        "classification_evidence_id": (
            str(classification_evidence_id) if classification_evidence_id is not None else None
        ),
    }


def _default_configuration_payload() -> dict[str, Any]:
    return {
        "configuration_version": ROUTING_CONFIGURATION_VERSION,
        "intent_catalog": [
            {"intent": intent, "enabled": True, "catalog_version": "community.v1"} for intent in INITIAL_INTENTS
        ],
        "provider_chain": [
            {"provider": COMMUNITY_INTENT_PROVIDER, "enabled": True, "required": False},
        ],
        "confidence_thresholds": {
            "minimum_confidence": 0.65,
        },
        "fallback_behavior": {
            "intent": "knowledge_query",
            "provider": "system.safe_fallback",
            "target_runtime": "assistant.enterprise_search",
        },
        "context_window_policy": {
            "policy_version": "conversation-context.v1",
            "max_prior_turns": 20,
        },
        "semantic_configuration": {
            "provider": COMMUNITY_INTENT_PROVIDER,
            "local_files_only": True,
            "max_history_turns": 6,
            "embedding_infrastructure_required": False,
            "vector_database_required": False,
            "llm_required": False,
            "slm_required": False,
        },
    }


def resolve_routing_configuration(
    db: Session,
    *,
    organization_id: uuid.UUID,
    data_origin: str,
) -> ConversationRoutingConfiguration:
    repository = AssistantRepository(db)
    existing = repository.get_active_conversation_routing_configuration(organization_id=organization_id)
    if existing is not None:
        return existing
    organization = repository.lock_conversation_routing_configuration_scope(organization_id=organization_id)
    if organization is None:
        raise ValueError("organization routing configuration scope is unavailable")
    existing = repository.get_active_conversation_routing_configuration(organization_id=organization_id)
    if existing is not None:
        return existing
    payload = _default_configuration_payload()
    return repository.create_conversation_routing_configuration(
        organization_id=organization_id,
        data_origin=data_origin,
        configuration_hash=_canonical_hash(payload),
        **payload,
    )


def _context_history(context_package: Any) -> list[dict[str, Any]]:
    retrieval_inputs = dict(getattr(context_package, "retrieval_inputs", None) or {})
    return list(retrieval_inputs.get("conversation_history") or [])


def _effective_semantic_configuration(configuration: ConversationRoutingConfiguration) -> dict[str, Any]:
    persisted = dict(configuration.semantic_configuration or {})
    defaults = dict(_default_configuration_payload()["semantic_configuration"])
    return {**defaults, **persisted, "provider": COMMUNITY_INTENT_PROVIDER}


def _effective_routing_input_payload(
    *,
    organization_id: uuid.UUID,
    context_package: Any,
    configuration: ConversationRoutingConfiguration,
) -> dict[str, Any]:
    return {
        "organization_id": str(organization_id),
        "conversation_id": str(context_package.conversation_id),
        "conversation_turn_id": str(context_package.conversation_turn_id),
        "conversation_context_package_id": str(context_package.conversation_context_package_id),
        "context_hash": context_package.context_hash,
        "routing_configuration_id": str(configuration.routing_configuration_id),
        "configuration_version": configuration.configuration_version,
        "configuration_hash": configuration.configuration_hash,
        "intent_catalog": list(configuration.intent_catalog or []),
        "provider_chain": list(configuration.provider_chain or []),
        "confidence_thresholds": dict(configuration.confidence_thresholds or {}),
        "fallback_behavior": dict(configuration.fallback_behavior or {}),
        "semantic_configuration": _effective_semantic_configuration(configuration),
        "router_version": ROUTER_VERSION,
    }


def _enabled_intents(configuration: ConversationRoutingConfiguration) -> set[str]:
    enabled = {
        str(entry.get("intent") or "")
        for entry in list(configuration.intent_catalog or [])
        if bool(entry.get("enabled")) and str(entry.get("intent") or "") in INITIAL_INTENTS
    }
    return enabled or set(INITIAL_INTENTS)


def _routing_semantics(intent: str) -> tuple[bool, bool, bool]:
    context_required = intent in {
        "citation_request",
        "conversation_summary",
        "response_refinement",
        "contextual_follow_up",
    }
    retrieval_required = intent in {"knowledge_query", "contextual_follow_up", "new_topic"}
    generation_required = intent != "non_knowledge_interaction"
    return context_required, retrieval_required, generation_required


def _history_turn_ids(context_package: Any) -> list[tuple[str, str]]:
    conversation_history = _context_history(context_package)
    result: list[tuple[str, str]] = []
    for item in conversation_history:
        turn_id = str(item.get("conversation_turn_id") or "").strip()
        if not turn_id:
            continue
        result.append((turn_id, str(item.get("turn_role") or "").strip()))
    return result


def _referenced_turn_ids_for_intent(*, intent: str, context_package: Any) -> list[str]:
    history = _history_turn_ids(context_package)
    included_turn_ids = list(getattr(context_package, "included_turn_ids", None) or [])
    if not history:
        history = [(str(turn_id), "") for turn_id in included_turn_ids]

    if intent == "conversation_summary":
        return [turn_id for turn_id, _role in history]

    if intent in {"citation_request", "response_refinement"}:
        for turn_id, role in reversed(history):
            if role == "assistant":
                return [turn_id]
        return [history[-1][0]] if history else []

    if intent == "contextual_follow_up":
        return [turn_id for turn_id, _role in history[-2:]]

    return []


def _fallback_decision_payload(
    *,
    configuration: ConversationRoutingConfiguration,
    context_package: Any,
    input_hash: str,
) -> dict[str, Any]:
    fallback = dict(configuration.fallback_behavior or {})
    enabled_intents = _enabled_intents(configuration)
    intent = str(fallback.get("intent") or "knowledge_query")
    if intent not in enabled_intents:
        intent = "knowledge_query" if "knowledge_query" in enabled_intents else sorted(enabled_intents)[0]
    target_runtime = str(fallback.get("target_runtime") or "assistant.enterprise_search")
    context_required, retrieval_required, generation_required = _routing_semantics(intent)
    return {
        "classification_evidence_id": None,
        "intent": intent,
        "sub_intent": None,
        "intent_parameters": {},
        "confidence": 0.0,
        "resolution_method": "configured.fallback",
        "resolution_provider": "system.safe_fallback",
        "referenced_turn_ids": _referenced_turn_ids_for_intent(
            intent=intent,
            context_package=context_package,
        ),
        "conversation_context_required": context_required,
        "retrieval_required": retrieval_required,
        "generation_required": generation_required,
        "target_runtime": target_runtime,
        "embedding_used": False,
        "slm_used": False,
        "router_version": ROUTER_VERSION,
        "input_hash": input_hash,
    }


def _classification_evidence_decision_payload(
    *,
    classification_evidence: Any,
    context_package: Any,
    input_hash: str,
) -> dict[str, Any]:
    expected_lineage = (
        ("organization_id", context_package.organization_id),
        ("conversation_id", context_package.conversation_id),
        ("conversation_turn_id", context_package.conversation_turn_id),
        ("conversation_context_package_id", context_package.conversation_context_package_id),
    )
    for field_name, expected_value in expected_lineage:
        if getattr(classification_evidence, field_name) != expected_value:
            raise ValueError(f"classification evidence {field_name} lineage is inconsistent")
    intent = str(classification_evidence.predicted_intent)
    context_required, retrieval_required, generation_required = _routing_semantics(intent)
    return {
        "classification_evidence_id": classification_evidence.classification_evidence_id,
        "intent": intent,
        "sub_intent": classification_evidence.predicted_sub_intent,
        "intent_parameters": dict(classification_evidence.predicted_parameters or {}),
        "confidence": float(classification_evidence.confidence),
        "resolution_method": classification_evidence.resolution_method,
        "resolution_provider": classification_evidence.resolution_provider,
        "referenced_turn_ids": _referenced_turn_ids_for_intent(
            intent=intent,
            context_package=context_package,
        ),
        "conversation_context_required": context_required,
        "retrieval_required": retrieval_required,
        "generation_required": generation_required,
        "target_runtime": "assistant.enterprise_search",
        "embedding_used": False,
        "slm_used": False,
        "router_version": ROUTER_VERSION,
        "input_hash": input_hash,
    }


def _validate_decision_lineage(
    decision: ConversationInteractionDecision,
    *,
    context_package: Any,
) -> None:
    expected_lineage = (
        ("organization_id", context_package.organization_id),
        ("conversation_id", context_package.conversation_id),
        ("conversation_turn_id", context_package.conversation_turn_id),
        ("conversation_context_package_id", context_package.conversation_context_package_id),
    )
    for field_name, expected_value in expected_lineage:
        if getattr(decision, field_name) != expected_value:
            raise ValueError(f"interaction decision {field_name} lineage is inconsistent")


def resolve_interaction_decision(
    db: Session,
    *,
    conversation_turn_id: uuid.UUID,
    organization_id: uuid.UUID,
) -> ConversationInteractionDecision | None:
    repository = AssistantRepository(db)
    existing = repository.get_scoped_conversation_interaction_decision(
        conversation_turn_id=conversation_turn_id,
        organization_id=organization_id,
    )
    if existing is not None:
        context_package = repository.get_scoped_conversation_context_package(
            conversation_turn_id=conversation_turn_id,
            organization_id=organization_id,
        )
        if context_package is None:
            context_package = resolve_conversation_context_package(
                db,
                conversation_turn_id=conversation_turn_id,
                organization_id=organization_id,
            )
        if context_package is None:
            raise RuntimeError("persisted interaction decision context package is unavailable")
        _validate_decision_lineage(existing, context_package=context_package)
        resolve_persisted_interaction_plan(
            db,
            context_package=context_package,
            interaction_decision=existing,
        )
        return existing

    context_package = repository.get_scoped_conversation_context_package(
        conversation_turn_id=conversation_turn_id,
        organization_id=organization_id,
    )
    if context_package is None:
        context_package = resolve_conversation_context_package(
            db,
            conversation_turn_id=conversation_turn_id,
            organization_id=organization_id,
        )
    if context_package is None:
        return None
    if context_package.organization_id != organization_id:
        raise ValueError("interaction decision context organization lineage is inconsistent")

    classification_evidence = resolve_conversation_intent_classification(
        db,
        organization_id=organization_id,
        conversation_turn_id=conversation_turn_id,
    )
    configuration = resolve_routing_configuration(
        db,
        organization_id=organization_id,
        data_origin=context_package.data_origin,
    )
    input_hash = _canonical_hash(
        _effective_routing_input_payload(
            organization_id=organization_id,
            context_package=context_package,
            configuration=configuration,
        )
    )

    if classification_evidence is None:
        decision_payload = _fallback_decision_payload(
            configuration=configuration,
            context_package=context_package,
            input_hash=input_hash,
        )
    else:
        decision_payload = _classification_evidence_decision_payload(
            classification_evidence=classification_evidence,
            context_package=context_package,
            input_hash=input_hash,
        )
    try:
        with db.begin_nested():
            decision = repository.create_conversation_interaction_decision(
                organization_id=organization_id,
                data_origin=context_package.data_origin,
                conversation_id=context_package.conversation_id,
                conversation_turn_id=context_package.conversation_turn_id,
                conversation_context_package_id=context_package.conversation_context_package_id,
                routing_configuration_id=configuration.routing_configuration_id,
                decision_hash=_canonical_hash(_decision_hash_payload(decision_payload)),
                **decision_payload,
            )
    except IntegrityError as exc:
        if _integrity_constraint_name(exc) != DECISION_IDEMPOTENCY_CONSTRAINT:
            raise
        decision = repository.get_scoped_conversation_interaction_decision(
            conversation_turn_id=conversation_turn_id,
            organization_id=organization_id,
        )
        if decision is None:
            raise
        _validate_decision_lineage(decision, context_package=context_package)
    resolve_persisted_interaction_plan(
        db,
        context_package=context_package,
        interaction_decision=decision,
    )
    return decision


def routing_configuration_to_dict(record: ConversationRoutingConfiguration) -> dict[str, Any]:
    return {
        "routing_configuration_id": str(record.routing_configuration_id),
        "organization_id": str(record.organization_id),
        "ownership_scope": record.ownership_scope,
        "data_origin": record.data_origin,
        "configuration_version": record.configuration_version,
        "configuration_status": record.configuration_status,
        "intent_catalog": list(record.intent_catalog or []),
        "provider_chain": list(record.provider_chain or []),
        "confidence_thresholds": dict(record.confidence_thresholds or {}),
        "fallback_behavior": dict(record.fallback_behavior or {}),
        "context_window_policy": dict(record.context_window_policy or {}),
        "semantic_configuration": _effective_semantic_configuration(record),
        "configuration_hash": record.configuration_hash,
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
    }


def interaction_decision_to_dict(record: ConversationInteractionDecision) -> dict[str, Any]:
    return {
        "interaction_decision_id": str(record.interaction_decision_id),
        "organization_id": str(record.organization_id),
        "ownership_scope": record.ownership_scope,
        "data_origin": record.data_origin,
        "conversation_id": str(record.conversation_id),
        "conversation_turn_id": str(record.conversation_turn_id),
        "conversation_context_package_id": str(record.conversation_context_package_id),
        "routing_configuration_id": str(record.routing_configuration_id),
        "classification_evidence_id": (
            str(getattr(record, "classification_evidence_id", None))
            if getattr(record, "classification_evidence_id", None)
            else None
        ),
        "intent": record.intent,
        "sub_intent": getattr(record, "sub_intent", None),
        "intent_parameters": dict(getattr(record, "intent_parameters", None) or {}),
        "confidence": float(record.confidence),
        "resolution_method": record.resolution_method,
        "resolution_provider": record.resolution_provider,
        "referenced_turn_ids": list(record.referenced_turn_ids or []),
        "conversation_context_required": bool(record.conversation_context_required),
        "retrieval_required": bool(record.retrieval_required),
        "generation_required": bool(record.generation_required),
        "target_runtime": record.target_runtime,
        "embedding_used": bool(record.embedding_used),
        "slm_used": bool(record.slm_used),
        "router_version": record.router_version,
        "input_hash": record.input_hash,
        "decision_hash": record.decision_hash,
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
    }
