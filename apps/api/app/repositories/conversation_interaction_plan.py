from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.assistant_runtime import ConversationContextPackage, ConversationInteractionDecision
from app.models.conversation_interaction_plan import ConversationInteractionPlan
from app.services.conversation_interaction_planner import InteractionPlanDraft


class ConversationInteractionPlanRepository:
    """Organization-scoped persistence for authoritative interaction plans."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_for_turn(
        self,
        *,
        organization_id: uuid.UUID,
        conversation_turn_id: uuid.UUID,
    ) -> ConversationInteractionPlan | None:
        return self.session.scalar(
            select(ConversationInteractionPlan).where(
                ConversationInteractionPlan.organization_id == organization_id,
                ConversationInteractionPlan.conversation_turn_id == conversation_turn_id,
                ConversationInteractionPlan.ownership_scope == "organization",
            )
        )

    def create(
        self,
        *,
        context_package: ConversationContextPackage,
        interaction_decision: ConversationInteractionDecision,
        plan: InteractionPlanDraft,
    ) -> ConversationInteractionPlan:
        if context_package.organization_id != interaction_decision.organization_id:
            raise ValueError("interaction plan organization lineage is inconsistent")
        if context_package.conversation_id != interaction_decision.conversation_id:
            raise ValueError("interaction plan conversation lineage is inconsistent")
        if context_package.conversation_turn_id != interaction_decision.conversation_turn_id:
            raise ValueError("interaction plan turn lineage is inconsistent")
        if context_package.conversation_context_package_id != interaction_decision.conversation_context_package_id:
            raise ValueError("interaction plan context lineage is inconsistent")

        record = ConversationInteractionPlan(
            organization_id=interaction_decision.organization_id,
            ownership_scope="organization",
            data_origin=interaction_decision.data_origin,
            conversation_id=interaction_decision.conversation_id,
            conversation_turn_id=interaction_decision.conversation_turn_id,
            conversation_context_package_id=context_package.conversation_context_package_id,
            interaction_decision_id=interaction_decision.interaction_decision_id,
            intent=plan.intent,
            planned_action=plan.planned_action,
            target_runtime=plan.target_runtime,
            context_required=plan.context_required,
            retrieval_required=plan.retrieval_required,
            generation_required=plan.generation_required,
            use_persisted_citations=plan.use_persisted_citations,
            use_conversation_evidence=plan.use_conversation_evidence,
            use_conversation_context=plan.use_conversation_context,
            enterprise_search_required=plan.enterprise_search_required,
            deterministic_response_allowed=plan.deterministic_response_allowed,
            planner_version=plan.planner_version,
            input_hash=plan.input_hash,
            plan_hash=plan.plan_hash,
            plan_metadata=dict(plan.plan_metadata),
        )
        self.session.add(record)
        self.session.flush()
        return record
