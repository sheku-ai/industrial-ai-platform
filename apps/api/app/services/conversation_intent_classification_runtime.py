from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.assistant_runtime import ConversationContextPackage
from app.models.conversation_intent_model import ConversationIntentClassificationEvidence
from app.repositories.assistant import AssistantRepository
from app.repositories.conversation_intent_model import ConversationIntentModelRepository
from app.services.conversation_intent_engine import IntentClassificationResult, classify_intent
from app.services.conversation_intent_model_runtime import EffectiveIntentModel, resolve_effective_intent_model

CLASSIFICATION_EVIDENCE_IDEMPOTENCY_CONSTRAINT = "uq_ai_intent_classification_evidence_org_turn"


def _canonical_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _integrity_constraint_name(exc: IntegrityError) -> str | None:
    diag = getattr(exc.orig, "diag", None)
    return getattr(diag, "constraint_name", None)


def _context_inputs(context_package: ConversationContextPackage) -> tuple[str, list[dict[str, Any]]]:
    retrieval_inputs = dict(context_package.retrieval_inputs or {})
    current_user_message = str(
        retrieval_inputs.get("current_user_message") or context_package.current_user_message or ""
    ).strip()
    conversation_history = [dict(item) for item in list(retrieval_inputs.get("conversation_history") or [])]
    return current_user_message, conversation_history


def _classification_text(
    *,
    current_user_message: str,
    conversation_history: list[dict[str, Any]],
) -> str:
    lines: list[str] = []
    history = [item for item in conversation_history if str(item.get("content") or "").strip()]
    if history:
        lines.append("[conversation]")
        for item in history:
            role = str(item.get("turn_role") or item.get("role") or "unknown").strip() or "unknown"
            content = " ".join(str(item.get("content") or "").split())
            lines.append(f"{role}: {content}")
    lines.append("[current]")
    lines.append(" ".join(current_user_message.split()))
    return "\n".join(lines)


def _classification_input_payload(
    *,
    context_package: ConversationContextPackage,
    effective_model: EffectiveIntentModel,
) -> dict[str, Any]:
    current_user_message, conversation_history = _context_inputs(context_package)
    return {
        "organization_id": str(context_package.organization_id),
        "conversation_id": str(context_package.conversation_id),
        "conversation_turn_id": str(context_package.conversation_turn_id),
        "conversation_context_package_id": str(context_package.conversation_context_package_id),
        "context_hash": str(context_package.context_hash),
        "current_user_message": current_user_message,
        "conversation_history": conversation_history,
        "intent_model_id": str(effective_model.intent_model_id),
        "artifact_hash": effective_model.artifact_hash,
        "model_version": effective_model.model_version,
        "scope_type": effective_model.scope_type,
        "provider": effective_model.provider,
    }


def _validate_evidence_lineage(
    evidence: ConversationIntentClassificationEvidence,
    *,
    context_package: ConversationContextPackage,
) -> None:
    expected = (
        ("organization_id", context_package.organization_id),
        ("conversation_id", context_package.conversation_id),
        ("conversation_turn_id", context_package.conversation_turn_id),
        ("conversation_context_package_id", context_package.conversation_context_package_id),
    )
    if evidence.ownership_scope != "organization":
        raise ValueError("classification evidence ownership scope is inconsistent")
    for field_name, expected_value in expected:
        if getattr(evidence, field_name) != expected_value:
            raise ValueError(f"classification evidence {field_name} lineage is inconsistent")


def _validate_classification_result(
    result: IntentClassificationResult,
    *,
    effective_model: EffectiveIntentModel,
) -> None:
    expected_identity = (
        ("intent_model_id", effective_model.intent_model_id),
        ("model_family", effective_model.model_family),
        ("provider", effective_model.provider),
        ("model_version", effective_model.model_version),
        ("model_scope_type", effective_model.scope_type),
        ("artifact_reference", effective_model.artifact_reference),
        ("artifact_hash", effective_model.artifact_hash),
    )
    for field_name, expected_value in expected_identity:
        if getattr(result, field_name) != expected_value:
            raise ValueError(f"classification result {field_name} lineage is inconsistent")


def _classification_hash_payload(
    *,
    organization_id: uuid.UUID,
    context_package: ConversationContextPackage,
    result: IntentClassificationResult,
) -> dict[str, Any]:
    return {
        "organization_id": str(organization_id),
        "conversation_id": str(context_package.conversation_id),
        "conversation_turn_id": str(context_package.conversation_turn_id),
        "conversation_context_package_id": str(context_package.conversation_context_package_id),
        "intent_model_id": str(result.intent_model_id),
        "model_family": result.model_family,
        "provider": result.provider,
        "model_version": result.model_version,
        "model_scope_type": result.model_scope_type,
        "artifact_reference": result.artifact_reference,
        "artifact_hash": result.artifact_hash,
        "intent": result.intent,
        "sub_intent": result.sub_intent,
        "intent_parameters": dict(result.intent_parameters),
        "confidence": float(result.confidence),
        "resolution_method": result.resolution_method,
    }


def resolve_conversation_intent_classification(
    db: Session,
    *,
    organization_id: uuid.UUID,
    conversation_turn_id: uuid.UUID,
    organization_node_id: uuid.UUID | None = None,
) -> ConversationIntentClassificationEvidence | None:
    context_package = AssistantRepository(db).get_scoped_conversation_context_package(
        conversation_turn_id=conversation_turn_id,
        organization_id=organization_id,
    )
    if context_package is None:
        return None
    if context_package.organization_id != organization_id:
        raise ValueError("classification context organization lineage is inconsistent")

    repository = ConversationIntentModelRepository(db)
    existing = repository.get_classification_for_turn(organization_id, conversation_turn_id)
    if existing is not None:
        _validate_evidence_lineage(existing, context_package=context_package)
        return existing

    effective_model = resolve_effective_intent_model(
        db,
        organization_id=organization_id,
        organization_node_id=organization_node_id,
    )
    if effective_model is None:
        return None

    current_user_message, conversation_history = _context_inputs(context_package)
    if not current_user_message:
        return None
    result = classify_intent(
        effective_model=effective_model,
        current_user_message=_classification_text(
            current_user_message=current_user_message,
            conversation_history=conversation_history,
        ),
    )
    if result is None:
        return None
    _validate_classification_result(result, effective_model=effective_model)

    input_hash = _canonical_hash(
        _classification_input_payload(
            context_package=context_package,
            effective_model=effective_model,
        )
    )
    classification_hash = _canonical_hash(
        _classification_hash_payload(
            organization_id=organization_id,
            context_package=context_package,
            result=result,
        )
    )
    try:
        with db.begin_nested():
            return repository.create_classification_evidence(
                organization_id=organization_id,
                conversation_id=context_package.conversation_id,
                conversation_turn_id=context_package.conversation_turn_id,
                conversation_context_package_id=context_package.conversation_context_package_id,
                intent_model_id=result.intent_model_id,
                model_family=result.model_family,
                artifact_reference=result.artifact_reference,
                artifact_hash=result.artifact_hash,
                predicted_intent=result.intent,
                predicted_sub_intent=result.sub_intent,
                predicted_parameters=dict(result.intent_parameters),
                confidence=float(result.confidence),
                resolution_method=result.resolution_method,
                resolution_provider=result.provider,
                model_version=result.model_version,
                model_scope_type=result.model_scope_type,
                input_hash=input_hash,
                classification_hash=classification_hash,
                data_origin=context_package.data_origin,
                requested_organization_node_id=organization_node_id,
            )
    except IntegrityError as exc:
        if _integrity_constraint_name(exc) != CLASSIFICATION_EVIDENCE_IDEMPOTENCY_CONSTRAINT:
            raise
        winner = repository.get_classification_for_turn(organization_id, conversation_turn_id)
        if winner is None:
            raise
        _validate_evidence_lineage(winner, context_package=context_package)
        return winner


def conversation_intent_classification_evidence_to_dict(
    record: ConversationIntentClassificationEvidence,
) -> dict[str, Any]:
    return {
        "classification_evidence_id": str(record.classification_evidence_id),
        "organization_id": str(record.organization_id),
        "ownership_scope": record.ownership_scope,
        "data_origin": record.data_origin,
        "conversation_id": str(record.conversation_id),
        "conversation_turn_id": str(record.conversation_turn_id),
        "conversation_context_package_id": str(record.conversation_context_package_id),
        "intent_model_id": str(record.intent_model_id) if record.intent_model_id else None,
        "predicted_intent": record.predicted_intent,
        "predicted_sub_intent": record.predicted_sub_intent,
        "predicted_parameters": dict(record.predicted_parameters or {}),
        "confidence": float(record.confidence),
        "resolution_method": record.resolution_method,
        "resolution_provider": record.resolution_provider,
        "model_version": record.model_version,
        "model_scope_type": record.model_scope_type,
        "input_hash": record.input_hash,
        "classification_hash": record.classification_hash,
        "created_at": record.created_at.isoformat() if record.created_at else None,
    }
