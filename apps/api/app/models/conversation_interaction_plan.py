from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ConversationInteractionPlan(Base):
    __tablename__ = "conversation_interaction_plans"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "conversation_turn_id",
            name="uq_ai_conversation_interaction_plans_org_turn",
        ),
        UniqueConstraint(
            "interaction_plan_id",
            "organization_id",
            name="uq_ai_conversation_interaction_plans_id_organization",
        ),
        UniqueConstraint(
            "interaction_plan_id",
            "organization_id",
            "conversation_id",
            name="uq_ai_conversation_interaction_plans_id_org_conversation",
        ),
        ForeignKeyConstraint(
            ["conversation_id", "organization_id"],
            ["ai.conversations.conversation_id", "ai.conversations.organization_id"],
            name="fk_ai_conversation_interaction_plans_scoped_conversation",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["conversation_turn_id", "conversation_id", "organization_id"],
            [
                "ai.conversation_turns.conversation_turn_id",
                "ai.conversation_turns.conversation_id",
                "ai.conversation_turns.organization_id",
            ],
            name="fk_ai_conversation_interaction_plans_scoped_turn",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["conversation_context_package_id", "organization_id", "conversation_turn_id"],
            [
                "ai.conversation_context_packages.conversation_context_package_id",
                "ai.conversation_context_packages.organization_id",
                "ai.conversation_context_packages.conversation_turn_id",
            ],
            name="fk_ai_conversation_interaction_plans_scoped_context",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["interaction_decision_id", "organization_id", "conversation_turn_id"],
            [
                "ai.conversation_interaction_decisions.interaction_decision_id",
                "ai.conversation_interaction_decisions.organization_id",
                "ai.conversation_interaction_decisions.conversation_turn_id",
            ],
            name="fk_ai_conversation_interaction_plans_scoped_decision",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "ownership_scope = 'organization' AND organization_id IS NOT NULL",
            name="ck_ai_conversation_interaction_plans_ownership",
        ),
        CheckConstraint(
            "data_origin IN ('operational','reference','validation','legacy')",
            name="ck_ai_conversation_interaction_plans_origin",
        ),
        Index(
            "ix_ai_conversation_interaction_plans_conversation",
            "organization_id",
            "conversation_id",
            "created_at",
        ),
        Index(
            "ix_ai_conversation_interaction_plans_decision",
            "organization_id",
            "interaction_decision_id",
        ),
        Index("ix_ai_conversation_interaction_plans_input_hash", "input_hash"),
        Index("ix_ai_conversation_interaction_plans_plan_hash", "plan_hash"),
        {"schema": "ai"},
    )

    interaction_plan_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.organizations.id", ondelete="RESTRICT"), nullable=False
    )
    ownership_scope: Mapped[str] = mapped_column(String(32), server_default="organization", nullable=False)
    data_origin: Mapped[str] = mapped_column(String(32), server_default="operational", nullable=False)
    conversation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    conversation_turn_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    conversation_context_package_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    interaction_decision_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    intent: Mapped[str] = mapped_column(String(64), nullable=False)
    planned_action: Mapped[str] = mapped_column(String(128), nullable=False)
    target_runtime: Mapped[str] = mapped_column(String(128), nullable=False)
    context_required: Mapped[bool] = mapped_column(Boolean, nullable=False)
    retrieval_required: Mapped[bool] = mapped_column(Boolean, nullable=False)
    generation_required: Mapped[bool] = mapped_column(Boolean, nullable=False)
    use_persisted_citations: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
    use_conversation_evidence: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
    use_conversation_context: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
    enterprise_search_required: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
    deterministic_response_allowed: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
    planner_version: Mapped[str] = mapped_column(String(64), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    plan_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    plan_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
