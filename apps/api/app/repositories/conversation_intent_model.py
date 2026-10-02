from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.conversation_intent_model import (
    ConversationIntentClassificationEvidence,
    ConversationIntentModel,
)


class ConversationIntentModelRepository:
    """PostgreSQL authority for intent models and immutable classification evidence."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_model(self, intent_model_id: uuid.UUID) -> ConversationIntentModel | None:
        return self.session.get(ConversationIntentModel, intent_model_id)

    def get_active_community_model(self, model_family: str) -> ConversationIntentModel | None:
        return self.session.scalar(
            select(ConversationIntentModel)
            .where(
                ConversationIntentModel.scope_type == "community",
                ConversationIntentModel.ownership_scope == "global",
                ConversationIntentModel.organization_id.is_(None),
                ConversationIntentModel.organization_node_id.is_(None),
                ConversationIntentModel.model_family == model_family,
                ConversationIntentModel.model_status == "active",
            )
            .limit(1)
        )

    def get_community_models_by_version(
        self,
        *,
        model_family: str,
        model_version: str,
    ) -> list[ConversationIntentModel]:
        return list(
            self.session.scalars(
                select(ConversationIntentModel).where(
                    ConversationIntentModel.scope_type == "community",
                    ConversationIntentModel.ownership_scope == "global",
                    ConversationIntentModel.organization_id.is_(None),
                    ConversationIntentModel.organization_node_id.is_(None),
                    ConversationIntentModel.model_family == model_family,
                    ConversationIntentModel.model_version == model_version,
                )
            ).all()
        )

    def create_community_model(
        self,
        *,
        model_family: str,
        provider: str,
        model_version: str,
        artifact_reference: str,
        artifact_hash: str,
        model_metadata: dict[str, Any],
    ) -> ConversationIntentModel:
        record = ConversationIntentModel(
            organization_id=None,
            organization_node_id=None,
            ownership_scope="global",
            scope_type="community",
            data_origin="operational",
            model_family=model_family,
            provider=provider,
            model_version=model_version,
            model_status="active",
            artifact_reference=artifact_reference,
            artifact_hash=artifact_hash,
            model_metadata=dict(model_metadata),
        )
        self.session.add(record)
        self.session.flush()
        return record

    def get_active_organization_model(
        self,
        organization_id: uuid.UUID,
        model_family: str,
    ) -> ConversationIntentModel | None:
        return self.session.scalar(
            select(ConversationIntentModel)
            .where(
                ConversationIntentModel.scope_type == "organization",
                ConversationIntentModel.ownership_scope == "organization",
                ConversationIntentModel.organization_id == organization_id,
                ConversationIntentModel.organization_node_id.is_(None),
                ConversationIntentModel.model_family == model_family,
                ConversationIntentModel.model_status == "active",
            )
            .limit(1)
        )

    def get_active_organization_node_model(
        self,
        organization_id: uuid.UUID,
        organization_node_id: uuid.UUID,
        model_family: str,
    ) -> ConversationIntentModel | None:
        return self.session.scalar(
            select(ConversationIntentModel)
            .where(
                ConversationIntentModel.scope_type == "organization_node",
                ConversationIntentModel.ownership_scope == "organization",
                ConversationIntentModel.organization_id == organization_id,
                ConversationIntentModel.organization_node_id == organization_node_id,
                ConversationIntentModel.model_family == model_family,
                ConversationIntentModel.model_status == "active",
            )
            .limit(1)
        )

    def resolve_effective_model(
        self,
        organization_id: uuid.UUID,
        organization_node_id: uuid.UUID | None = None,
        model_family: str = "conversation_intent",
    ) -> ConversationIntentModel | None:
        if organization_node_id is not None:
            node_model = self.get_active_organization_node_model(
                organization_id,
                organization_node_id,
                model_family,
            )
            if node_model is not None:
                return node_model
        organization_model = self.get_active_organization_model(organization_id, model_family)
        if organization_model is not None:
            return organization_model
        return self.get_active_community_model(model_family)

    def get_classification_for_turn(
        self,
        organization_id: uuid.UUID,
        conversation_turn_id: uuid.UUID,
    ) -> ConversationIntentClassificationEvidence | None:
        return self.session.scalar(
            select(ConversationIntentClassificationEvidence).where(
                ConversationIntentClassificationEvidence.organization_id == organization_id,
                ConversationIntentClassificationEvidence.conversation_turn_id == conversation_turn_id,
                ConversationIntentClassificationEvidence.ownership_scope == "organization",
            )
        )

    def create_classification_evidence(
        self,
        *,
        organization_id: uuid.UUID,
        conversation_id: uuid.UUID,
        conversation_turn_id: uuid.UUID,
        conversation_context_package_id: uuid.UUID,
        intent_model_id: uuid.UUID,
        model_family: str,
        artifact_reference: str,
        artifact_hash: str,
        predicted_intent: str,
        predicted_sub_intent: str | None,
        predicted_parameters: dict[str, Any],
        confidence: float,
        resolution_method: str,
        resolution_provider: str,
        model_version: str,
        model_scope_type: str,
        input_hash: str,
        classification_hash: str,
        data_origin: str,
        requested_organization_node_id: uuid.UUID | None = None,
    ) -> ConversationIntentClassificationEvidence:
        model = self.get_model(intent_model_id)
        if model is None:
            raise ValueError("intent model is unavailable")
        if model.model_status != "active":
            raise ValueError("intent model is not active")
        self._validate_model_scope(
            model,
            organization_id=organization_id,
            requested_organization_node_id=requested_organization_node_id,
        )
        if model.model_version != model_version:
            raise ValueError("classification model version lineage is inconsistent")
        if model.model_family != model_family:
            raise ValueError("classification model family lineage is inconsistent")
        if model.scope_type != model_scope_type:
            raise ValueError("classification model scope lineage is inconsistent")
        if model.provider != resolution_provider:
            raise ValueError("classification model provider lineage is inconsistent")
        if model.artifact_reference != artifact_reference:
            raise ValueError("classification model artifact reference lineage is inconsistent")
        if model.artifact_hash != artifact_hash:
            raise ValueError("classification model artifact hash lineage is inconsistent")
        if not 0.0 <= float(confidence) <= 1.0:
            raise ValueError("classification confidence must be between 0 and 1")

        record = ConversationIntentClassificationEvidence(
            organization_id=organization_id,
            ownership_scope="organization",
            data_origin=data_origin,
            conversation_id=conversation_id,
            conversation_turn_id=conversation_turn_id,
            conversation_context_package_id=conversation_context_package_id,
            intent_model_id=intent_model_id,
            predicted_intent=predicted_intent,
            predicted_sub_intent=predicted_sub_intent,
            predicted_parameters=dict(predicted_parameters),
            confidence=float(confidence),
            resolution_method=resolution_method,
            resolution_provider=resolution_provider,
            model_version=model_version,
            model_scope_type=model_scope_type,
            input_hash=input_hash,
            classification_hash=classification_hash,
        )
        self.session.add(record)
        self.session.flush()
        return record

    @staticmethod
    def _validate_model_scope(
        model: ConversationIntentModel,
        *,
        organization_id: uuid.UUID,
        requested_organization_node_id: uuid.UUID | None,
    ) -> None:
        if model.scope_type == "community":
            if (
                model.ownership_scope != "global"
                or model.organization_id is not None
                or model.organization_node_id is not None
            ):
                raise ValueError("community intent model scope is inconsistent")
            return
        if model.scope_type == "organization":
            if model.ownership_scope != "organization" or model.organization_id != organization_id:
                raise ValueError("intent model organization scope is inconsistent")
            if model.organization_node_id is not None:
                raise ValueError("organization intent model node scope is inconsistent")
            return
        if model.scope_type == "organization_node":
            if model.ownership_scope != "organization" or model.organization_id != organization_id:
                raise ValueError("intent model organization node scope is inconsistent")
            if model.organization_node_id is None:
                raise ValueError("intent model organization node is unavailable")
            if (
                requested_organization_node_id is not None
                and model.organization_node_id != requested_organization_node_id
            ):
                raise ValueError("intent model organization node scope is inconsistent")
            return
        raise ValueError("intent model scope type is unsupported")
