from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.assistant_runtime import ConversationContextPackage, ConversationInteractionDecision
from app.models.conversation_interaction_plan import ConversationInteractionPlan
from app.repositories.conversation_interaction_plan import ConversationInteractionPlanRepository
from app.services.conversation_interaction_planner import build_interaction_plan

INTERACTION_PLAN_IDEMPOTENCY_CONSTRAINT = "uq_ai_conversation_interaction_plans_org_turn"


@dataclass(frozen=True)
class InteractionExecutionDirective:
    interaction_plan_id: uuid.UUID
    organization_id: uuid.UUID
    conversation_turn_id: uuid.UUID
    planned_action: str
    target_runtime: str
    enterprise_search_required: bool
    generation_required: bool
    deterministic_response_allowed: bool


class InteractionExecutionNotPlannedError(RuntimeError):
    """Raised when a downstream runtime is requested without persisted authorization."""


def interaction_execution_directive_to_dict(
    directive: InteractionExecutionDirective,
) -> dict[str, Any]:
    """Serialize persisted routing authority without deriving new execution state."""
    return {
        "interaction_plan_id": str(directive.interaction_plan_id),
        "organization_id": str(directive.organization_id),
        "conversation_turn_id": str(directive.conversation_turn_id),
        "planned_action": directive.planned_action,
        "target_runtime": directive.target_runtime,
        "enterprise_search_required": directive.enterprise_search_required,
        "generation_required": directive.generation_required,
        "deterministic_response_allowed": directive.deterministic_response_allowed,
        "postgresql_source_of_truth": True,
    }


def _integrity_constraint_name(exc: IntegrityError) -> str | None:
    diag = getattr(exc.orig, "diag", None)
    return getattr(diag, "constraint_name", None)


def resolve_persisted_interaction_plan(
    session: Session,
    *,
    context_package: ConversationContextPackage,
    interaction_decision: ConversationInteractionDecision,
) -> ConversationInteractionPlan:
    """Return the authoritative plan for a turn, creating it once when absent."""
    organization_id = interaction_decision.organization_id
    conversation_turn_id = interaction_decision.conversation_turn_id
    if organization_id is None:
        raise ValueError("interaction plan requires organization-scoped evidence")

    repository = ConversationInteractionPlanRepository(session)
    existing = repository.get_for_turn(
        organization_id=organization_id,
        conversation_turn_id=conversation_turn_id,
    )
    if existing is not None:
        _validate_existing_plan(
            existing,
            context_package=context_package,
            interaction_decision=interaction_decision,
        )
        return existing

    draft = build_interaction_plan(
        context_package=context_package,
        interaction_decision=interaction_decision,
    )
    try:
        with session.begin_nested():
            return repository.create(
                context_package=context_package,
                interaction_decision=interaction_decision,
                plan=draft,
            )
    except IntegrityError as exc:
        if _integrity_constraint_name(exc) != INTERACTION_PLAN_IDEMPOTENCY_CONSTRAINT:
            raise
        winner = repository.get_for_turn(
            organization_id=organization_id,
            conversation_turn_id=conversation_turn_id,
        )
        if winner is None:
            raise
        _validate_existing_plan(
            winner,
            context_package=context_package,
            interaction_decision=interaction_decision,
        )
        return winner


def resolve_interaction_execution_directive(
    session: Session,
    *,
    organization_id: uuid.UUID,
    conversation_turn_id: uuid.UUID,
) -> InteractionExecutionDirective:
    """Read the persisted plan as the sole execution-routing authority for a turn."""
    plan = ConversationInteractionPlanRepository(session).get_for_turn(
        organization_id=organization_id,
        conversation_turn_id=conversation_turn_id,
    )
    if plan is None:
        raise ValueError("authoritative persisted interaction plan is unavailable")
    return InteractionExecutionDirective(
        interaction_plan_id=plan.interaction_plan_id,
        organization_id=plan.organization_id,
        conversation_turn_id=plan.conversation_turn_id,
        planned_action=plan.planned_action,
        target_runtime=plan.target_runtime,
        enterprise_search_required=plan.enterprise_search_required,
        generation_required=plan.generation_required,
        deterministic_response_allowed=plan.deterministic_response_allowed,
    )


def require_enterprise_search_execution(
    session: Session,
    *,
    organization_id: uuid.UUID,
    conversation_turn_id: uuid.UUID,
) -> InteractionExecutionDirective:
    """Authorize Enterprise Search only when persisted planning evidence requires it."""
    directive = resolve_interaction_execution_directive(
        session,
        organization_id=organization_id,
        conversation_turn_id=conversation_turn_id,
    )
    if not directive.enterprise_search_required:
        raise InteractionExecutionNotPlannedError(
            f"enterprise search is not planned for action {directive.planned_action}"
        )
    return directive


def _validate_existing_plan(
    plan: ConversationInteractionPlan,
    *,
    context_package: ConversationContextPackage,
    interaction_decision: ConversationInteractionDecision,
) -> None:
    expected: tuple[tuple[str, uuid.UUID], ...] = (
        ("organization_id", interaction_decision.organization_id),
        ("conversation_id", interaction_decision.conversation_id),
        ("conversation_turn_id", interaction_decision.conversation_turn_id),
        ("conversation_context_package_id", context_package.conversation_context_package_id),
        ("interaction_decision_id", interaction_decision.interaction_decision_id),
    )
    for field_name, expected_value in expected:
        if getattr(plan, field_name) != expected_value:
            raise ValueError(f"persisted interaction plan {field_name} lineage is inconsistent")
