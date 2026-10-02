"""Conversation-scoped Enterprise Search execution authorized by persisted planning evidence."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.services.assistant_search_execution_runtime import build_assistant_search_execution_runtime
from app.services.conversation_interaction_plan_runtime import require_enterprise_search_execution


def build_planned_conversation_search_runtime(
    db: Session,
    *,
    organization_id: uuid.UUID,
    conversation_turn_id: uuid.UUID,
    execution_plan_id: str,
    top_k: int | None = None,
    search_config: dict[str, Any] | None = None,
    persist_snapshot: bool = True,
) -> dict[str, Any] | None:
    """Execute Enterprise Search only when the persisted interaction plan authorizes it."""
    directive = require_enterprise_search_execution(
        db,
        organization_id=organization_id,
        conversation_turn_id=conversation_turn_id,
    )
    scoped_config = dict(search_config or {})
    scoped_config["organization_id"] = str(organization_id)
    filters = dict(scoped_config.get("filters") or {})
    filters["organization_id"] = str(organization_id)
    scoped_config["filters"] = filters
    scoped_config["interaction_plan_id"] = str(directive.interaction_plan_id)
    scoped_config["conversation_turn_id"] = str(conversation_turn_id)
    scoped_config["planned_action"] = directive.planned_action

    result = build_assistant_search_execution_runtime(
        db,
        execution_plan_id=execution_plan_id,
        organization_id=organization_id,
        top_k=top_k,
        search_config=scoped_config,
        persist_snapshot=persist_snapshot,
    )
    if result is not None:
        result["interaction_plan_id"] = str(directive.interaction_plan_id)
        result["conversation_turn_id"] = str(conversation_turn_id)
        result["planned_action"] = directive.planned_action
        result["enterprise_search_authorized_by_plan"] = True
    return result


__all__ = ["build_planned_conversation_search_runtime"]
