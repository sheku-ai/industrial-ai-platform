from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func, text

from app.db.base import Base


class ConversationIntentModel(Base):
    __tablename__ = "conversation_intent_models"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "organization_node_id"],
            ["core.organization_nodes.organization_id", "core.organization_nodes.id"],
            name="fk_ai_conversation_intent_models_scoped_node",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "(scope_type = 'community' AND organization_id IS NULL "
            "AND organization_node_id IS NULL AND ownership_scope = 'global') OR "
            "(scope_type = 'organization' AND organization_id IS NOT NULL "
            "AND organization_node_id IS NULL AND ownership_scope = 'organization') OR "
            "(scope_type = 'organization_node' AND organization_id IS NOT NULL "
            "AND organization_node_id IS NOT NULL AND ownership_scope = 'organization')",
            name="ck_ai_conversation_intent_models_scope_ownership",
        ),
        CheckConstraint(
            "scope_type IN ('community','organization','organization_node')",
            name="ck_ai_conversation_intent_models_scope_type",
        ),
        CheckConstraint(
            "data_origin IN ('operational','reference','validation','legacy')",
            name="ck_ai_conversation_intent_models_origin",
        ),
        CheckConstraint(
            "model_status IN ('registered','candidate','active','retired','failed')",
            name="ck_ai_conversation_intent_models_status",
        ),
        CheckConstraint("length(trim(provider)) > 0", name="ck_ai_conversation_intent_models_provider"),
        CheckConstraint("length(trim(model_version)) > 0", name="ck_ai_conversation_intent_models_version"),
        CheckConstraint("char_length(artifact_hash) = 64", name="ck_ai_conversation_intent_models_artifact_hash"),
        Index("ix_ai_conversation_intent_models_family", "model_family"),
        Index("ix_ai_conversation_intent_models_provider", "provider"),
        Index("ix_ai_conversation_intent_models_status", "model_status"),
        Index("ix_ai_conversation_intent_models_organization", "organization_id"),
        Index("ix_ai_conversation_intent_models_organization_node", "organization_id", "organization_node_id"),
        Index(
            "uq_ai_conversation_intent_models_active_community_family",
            "model_family",
            unique=True,
            postgresql_where=text("scope_type = 'community' AND model_status = 'active'"),
        ),
        Index(
            "uq_ai_conversation_intent_models_active_organization_family",
            "organization_id",
            "model_family",
            unique=True,
            postgresql_where=text("scope_type = 'organization' AND model_status = 'active'"),
        ),
        Index(
            "uq_ai_conversation_intent_models_active_node_family",
            "organization_id",
            "organization_node_id",
            "model_family",
            unique=True,
            postgresql_where=text("scope_type = 'organization_node' AND model_status = 'active'"),
        ),
        {"schema": "ai"},
    )

    intent_model_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.organizations.id", ondelete="RESTRICT"), nullable=True
    )
    organization_node_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    ownership_scope: Mapped[str] = mapped_column(String(32), server_default="global", nullable=False)
    scope_type: Mapped[str] = mapped_column(String(32), nullable=False)
    data_origin: Mapped[str] = mapped_column(String(32), server_default="operational", nullable=False)
    model_family: Mapped[str] = mapped_column(String(64), server_default="conversation_intent", nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model_version: Mapped[str] = mapped_column(String(64), nullable=False)
    model_status: Mapped[str] = mapped_column(String(32), nullable=False)
    artifact_reference: Mapped[str] = mapped_column(String(512), nullable=False)
    artifact_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    model_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ConversationIntentClassificationEvidence(Base):
    __tablename__ = "conversation_intent_classification_evidence"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "conversation_turn_id",
            name="uq_ai_intent_classification_evidence_org_turn",
        ),
        ForeignKeyConstraint(
            ["conversation_turn_id", "conversation_id", "organization_id"],
            [
                "ai.conversation_turns.conversation_turn_id",
                "ai.conversation_turns.conversation_id",
                "ai.conversation_turns.organization_id",
            ],
            name="fk_ai_intent_classification_evidence_scoped_turn",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["conversation_context_package_id", "organization_id", "conversation_turn_id"],
            [
                "ai.conversation_context_packages.conversation_context_package_id",
                "ai.conversation_context_packages.organization_id",
                "ai.conversation_context_packages.conversation_turn_id",
            ],
            name="fk_ai_intent_classification_evidence_scoped_context",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "ownership_scope = 'organization' AND organization_id IS NOT NULL",
            name="ck_ai_intent_classification_evidence_ownership",
        ),
        CheckConstraint(
            "data_origin IN ('operational','reference','validation','legacy')",
            name="ck_ai_intent_classification_evidence_origin",
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_ai_intent_classification_evidence_confidence",
        ),
        Index(
            "ix_ai_intent_classification_evidence_conversation",
            "organization_id",
            "conversation_id",
        ),
        Index("ix_ai_intent_classification_evidence_model", "intent_model_id"),
        Index("ix_ai_intent_classification_evidence_intent", "predicted_intent"),
        Index("ix_ai_intent_classification_evidence_input_hash", "input_hash"),
        Index("ix_ai_intent_classification_evidence_hash", "classification_hash"),
        {"schema": "ai"},
    )

    classification_evidence_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.organizations.id", ondelete="RESTRICT"), nullable=False
    )
    ownership_scope: Mapped[str] = mapped_column(String(32), server_default="organization", nullable=False)
    data_origin: Mapped[str] = mapped_column(String(32), server_default="operational", nullable=False)
    conversation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    conversation_turn_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    conversation_context_package_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    intent_model_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ai.conversation_intent_models.intent_model_id", ondelete="RESTRICT"),
        nullable=True,
    )
    predicted_intent: Mapped[str] = mapped_column(String(64), nullable=False)
    predicted_sub_intent: Mapped[str | None] = mapped_column(String(64), nullable=True)
    predicted_parameters: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb"), nullable=False
    )
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    resolution_method: Mapped[str] = mapped_column(String(64), nullable=False)
    resolution_provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model_scope_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    classification_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
