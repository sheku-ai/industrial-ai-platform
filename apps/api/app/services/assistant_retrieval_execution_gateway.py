"""Assistant Retrieval Execution Readiness gateway."""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.models.assistant_runtime import AssistantRetrievalPlan
from app.repositories.assistant import AssistantRepository
from app.services.assistant_retrieval_execution_contracts import AssistantRetrievalExecutionHealthResult
from app.services.assistant_retrieval_execution_session import (
    build_assistant_retrieval_execution_request,
    build_assistant_retrieval_execution_session,
    serialize_assistant_retrieval_execution_session,
)
from app.services.enterprise_search_session import issue, sort_issues


def build_assistant_retrieval_execution_gateway(
    db: Session,
    *,
    retrieval_plan_id: str,
    organization_id: uuid.UUID | None = None,
    readiness_metadata: dict | None = None,
) -> dict:
    blocking_issues: list[dict] = []
    warnings: list[dict] = []
    repository = AssistantRepository(db)
    retrieval_plan = None
    try:
        retrieval_plan_uuid = uuid.UUID(str(retrieval_plan_id))
    except (TypeError, ValueError):
        blocking_issues.append(
            issue(
                "retrieval_plan_id_invalid",
                "Assistant retrieval execution readiness requires a valid retrieval_plan_id.",
                component="assistant_retrieval_execution_gateway",
                item_id=str(retrieval_plan_id),
            )
        )
    else:
        retrieval_plan = repository.get_scoped_artifact(
            AssistantRetrievalPlan,
            AssistantRetrievalPlan.retrieval_plan_id,
            retrieval_plan_uuid,
            organization_id=organization_id,
        )
        if retrieval_plan is None:
            blocking_issues.append(
                issue(
                    "retrieval_plan_not_found",
                    "Assistant retrieval execution readiness requires an existing retrieval plan.",
                    component="assistant_retrieval_execution_gateway",
                    item_id=str(retrieval_plan_uuid),
                )
            )
    request = build_assistant_retrieval_execution_request(
        retrieval_plan_id=str(retrieval_plan_id),
        assistant_id=str(retrieval_plan.assistant_id) if retrieval_plan is not None else "",
        assistant_session_id=str(retrieval_plan.assistant_session_id)
        if retrieval_plan is not None and retrieval_plan.assistant_session_id
        else None,
        selected_search_mode=retrieval_plan.selected_search_mode if retrieval_plan is not None else "enterprise_search",
        selected_runtime_domain=retrieval_plan.selected_runtime_domain
        if retrieval_plan is not None
        else "enterprise_search",
        readiness_metadata=readiness_metadata,
    )
    session = serialize_assistant_retrieval_execution_session(build_assistant_retrieval_execution_session(request))
    blocking_issues.extend(session.get("blocking_issues") or [])
    warnings.extend(session.get("warnings") or [])
    if retrieval_plan is not None:
        if retrieval_plan.plan_status not in {"planned", "prepared"}:
            blocking_issues.append(
                issue(
                    "retrieval_plan_status_not_ready",
                    "Assistant retrieval execution readiness requires a planned or prepared retrieval plan.",
                    component="assistant_retrieval_execution_gateway",
                    item_id=retrieval_plan.plan_status,
                )
            )
        if retrieval_plan.retrieval_executed:
            blocking_issues.append(
                issue(
                    "retrieval_already_executed",
                    "Assistant retrieval execution readiness requires a retrieval plan that has not "
                    "executed retrieval.",
                    component="assistant_retrieval_execution_gateway",
                    item_id=str(retrieval_plan.retrieval_plan_id),
                )
            )
    ready = bool(session.get("assistant_retrieval_execution_session_ready")) and not blocking_issues
    return {
        "assistant_retrieval_execution_gateway_schema_version": "1",
        "assistant_retrieval_execution_gateway_ready": ready,
        "gateway_status": "ready" if ready else "blocked",
        "assistant_retrieval_execution_session": session,
        "source_of_truth": "postgresql",
        "assistant_retrieval_execution_readiness_prepared": ready,
        "execution_readiness_created": ready,
        "retrieval_plan_id": str(retrieval_plan.retrieval_plan_id)
        if retrieval_plan is not None
        else str(retrieval_plan_id),
        "assistant_id": str(retrieval_plan.assistant_id) if retrieval_plan is not None else None,
        "assistant_session_id": str(retrieval_plan.assistant_session_id)
        if retrieval_plan is not None and retrieval_plan.assistant_session_id
        else None,
        "selected_search_mode": request.selected_search_mode,
        "selected_runtime_domain": request.selected_runtime_domain,
        "enterprise_search_execution_prepared": ready and request.selected_search_mode == "enterprise_search",
        "semantic_search_execution_prepared": False,
        "hybrid_search_execution_prepared": False,
        "retrieval_executed": False,
        "answer_generated": False,
        "llm_used": False,
        "tool_called": False,
        "workflow_executed": False,
        "external_action_called": False,
        "autonomous_execution": False,
        "postgresql_source_of_truth": True,
        "blocking_issues": sort_issues(blocking_issues),
        "warnings": sort_issues(warnings),
        "next_available_actions": [
            {
                "action": "create_assistant_retrieval_execution_readiness",
                "available": ready,
                "status": "ready" if ready else "blocked",
                "reason": None if ready else "assistant_retrieval_execution_gateway_blocked",
            }
        ],
    }


def build_assistant_retrieval_execution_health(db: Session) -> dict:
    return AssistantRetrievalExecutionHealthResult().as_dict()
