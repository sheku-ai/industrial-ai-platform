from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.models.conversation_intent_model import ConversationIntentModel
from app.repositories.conversation_intent_model import ConversationIntentModelRepository


@dataclass(frozen=True)
class EffectiveIntentModel:
    intent_model_id: uuid.UUID
    model_family: str
    provider: str
    model_version: str
    scope_type: str
    organization_id: uuid.UUID | None
    organization_node_id: uuid.UUID | None
    artifact_reference: str
    artifact_hash: str


def resolve_effective_intent_model(
    db: Session,
    *,
    organization_id: uuid.UUID,
    organization_node_id: uuid.UUID | None = None,
) -> EffectiveIntentModel | None:
    record = ConversationIntentModelRepository(db).resolve_effective_model(
        organization_id,
        organization_node_id=organization_node_id,
        model_family="conversation_intent",
    )
    if record is None:
        return None
    return EffectiveIntentModel(
        intent_model_id=record.intent_model_id,
        model_family=record.model_family,
        provider=record.provider,
        model_version=record.model_version,
        scope_type=record.scope_type,
        organization_id=record.organization_id,
        organization_node_id=record.organization_node_id,
        artifact_reference=record.artifact_reference,
        artifact_hash=record.artifact_hash,
    )


def effective_intent_model_to_dict(model: EffectiveIntentModel) -> dict[str, Any]:
    return {
        "intent_model_id": str(model.intent_model_id),
        "model_family": model.model_family,
        "provider": model.provider,
        "model_version": model.model_version,
        "scope_type": model.scope_type,
        "organization_id": str(model.organization_id) if model.organization_id else None,
        "organization_node_id": str(model.organization_node_id) if model.organization_node_id else None,
        "artifact_reference": model.artifact_reference,
        "artifact_hash": model.artifact_hash,
        "postgresql_source_of_truth": True,
    }


def conversation_intent_model_to_dict(record: ConversationIntentModel) -> dict[str, Any]:
    return {
        "intent_model_id": str(record.intent_model_id),
        "organization_id": str(record.organization_id) if record.organization_id else None,
        "organization_node_id": str(record.organization_node_id) if record.organization_node_id else None,
        "ownership_scope": record.ownership_scope,
        "scope_type": record.scope_type,
        "data_origin": record.data_origin,
        "model_family": record.model_family,
        "provider": record.provider,
        "model_version": record.model_version,
        "model_status": record.model_status,
        "artifact_reference": record.artifact_reference,
        "artifact_hash": record.artifact_hash,
        "model_metadata": dict(record.model_metadata or {}),
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
        "postgresql_source_of_truth": True,
    }
