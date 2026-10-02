"""Assistant Enterprise Search Execution gateway."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.models.assistant_runtime import AssistantRetrievalExecutionPlan, AssistantRetrievalPlan
from app.repositories.assistant import AssistantRepository
from app.services.assistant_search_execution_contracts import AssistantSearchExecutionHealthResult
from app.services.assistant_search_execution_session import (
    build_assistant_search_execution_request,
    build_assistant_search_execution_session,
    serialize_assistant_search_execution_session,
)
from app.services.enterprise_search_session import issue, sort_issues


def build_assistant_search_execution_gateway(
    db: Session,
    *,
    execution_plan_id: str,
    organization_id: uuid.UUID | None = None,
    top_k: int | None = None,
    search_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    blocking_issues: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    repository = AssistantRepository(db)
    execution_plan = None
    retrieval_plan = None
    try:
        execution_plan_uuid = uuid.UUID(str(execution_plan_id))
    except (TypeError, ValueError):
        blocking_issues.append(
            issue(
                "execution_plan_id_invalid",
                "Assistant search execution requires a valid execution_plan_id.",
                component="assistant_search_execution_gateway",
                item_id=str(execution_plan_id),
            )
        )
    else:
        execution_plan = repository.get_scoped_artifact(
            AssistantRetrievalExecutionPlan,
            AssistantRetrievalExecutionPlan.execution_plan_id,
            execution_plan_uuid,
            organization_id=organization_id,
        )
        if execution_plan is None:
            blocking_issues.append(
                issue(
                    "execution_plan_not_found",
                    "Assistant search execution requires an existing retrieval execution readiness plan.",
                    component="assistant_search_execution_gateway",
                    item_id=str(execution_plan_uuid),
                )
            )
        else:
            retrieval_plan = repository.get_scoped_artifact(
                AssistantRetrievalPlan,
                AssistantRetrievalPlan.retrieval_plan_id,
                execution_plan.retrieval_plan_id,
                organization_id=execution_plan.organization_id,
            )
            if retrieval_plan is None:
                blocking_issues.append(
                    issue(
                        "retrieval_plan_not_found",
                        "Assistant search execution requires the source retrieval plan.",
                        component="assistant_search_execution_gateway",
                        item_id=str(execution_plan.retrieval_plan_id),
                    )
                )
            elif (
                retrieval_plan.assistant_id != execution_plan.assistant_id
                or retrieval_plan.assistant_session_id != execution_plan.assistant_session_id
                or retrieval_plan.organization_id != execution_plan.organization_id
                or retrieval_plan.ownership_scope != execution_plan.ownership_scope
            ):
                blocking_issues.append(
                    issue(
                        "retrieval_execution_lineage_mismatch",
                        "Retrieval execution does not match its persisted retrieval plan.",
                        component="assistant_search_execution_gateway",
                    )
                )
    if execution_plan is not None and execution_plan.organization_id is not None:
        config = search_config if isinstance(search_config, dict) else {}
        filters = config.get("filters") if isinstance(config.get("filters"), dict) else {}
        for supplied in (config.get("organization_id"), filters.get("organization_id")):
            if supplied is None:
                continue
            try:
                matches = uuid.UUID(str(supplied)) == execution_plan.organization_id
            except (TypeError, ValueError):
                matches = False
            if not matches:
                blocking_issues.append(
                    issue(
                        "search_organization_scope_mismatch",
                        "Search organization conflicts with persisted execution ownership.",
                        component="assistant_search_execution_gateway",
                    )
                )
                break
    request = build_assistant_search_execution_request(
        execution_plan_id=str(execution_plan_id),
        retrieval_plan_id=str(execution_plan.retrieval_plan_id) if execution_plan is not None else "",
        assistant_id=str(execution_plan.assistant_id) if execution_plan is not None else "",
        assistant_session_id=str(execution_plan.assistant_session_id)
        if execution_plan is not None and execution_plan.assistant_session_id
        else None,
        search_query=retrieval_plan.requested_query if retrieval_plan is not None else None,
        top_k=top_k,
        search_config=search_config,
    )
    session = serialize_assistant_search_execution_session(build_assistant_search_execution_session(request))
    blocking_issues.extend(session.get("blocking_issues") or [])
    warnings.extend(session.get("warnings") or [])
    if execution_plan is not None:
        if execution_plan.execution_status != "prepared":
            blocking_issues.append(
                issue(
                    "execution_readiness_not_prepared",
                    "Assistant search execution requires prepared execution readiness.",
                    component="assistant_search_execution_gateway",
                    item_id=execution_plan.execution_status,
                )
            )
        if execution_plan.execution_state != "readiness_only":
            blocking_issues.append(
                issue(
                    "execution_state_not_readiness_only",
                    "Assistant search execution requires readiness_only state.",
                    component="assistant_search_execution_gateway",
                    item_id=execution_plan.execution_state,
                )
            )
        if (
            execution_plan.selected_search_mode != "enterprise_search"
            or execution_plan.selected_runtime_domain != "enterprise_search"
        ):
            blocking_issues.append(
                issue(
                    "execution_mode_not_enterprise_search",
                    "Assistant search execution supports only enterprise_search readiness.",
                    component="assistant_search_execution_gateway",
                    item_id=execution_plan.selected_search_mode,
                )
            )
        if execution_plan.retrieval_executed:
            blocking_issues.append(
                issue(
                    "retrieval_already_executed",
                    "Assistant search execution requires readiness with retrieval_executed=false.",
                    component="assistant_search_execution_gateway",
                    item_id=str(execution_plan.execution_plan_id),
                )
            )
    ready = bool(session.get("assistant_search_execution_session_ready")) and not blocking_issues
    return {
        "assistant_search_execution_gateway_schema_version": "1",
        "assistant_search_execution_gateway_ready": ready,
        "gateway_status": "ready" if ready else "blocked",
        "assistant_search_execution_session": session,
        "execution_plan_id": str(execution_plan.execution_plan_id)
        if execution_plan is not None
        else str(execution_plan_id),
        "retrieval_plan_id": str(execution_plan.retrieval_plan_id) if execution_plan is not None else None,
        "assistant_id": str(execution_plan.assistant_id) if execution_plan is not None else None,
        "assistant_session_id": str(execution_plan.assistant_session_id)
        if execution_plan is not None and execution_plan.assistant_session_id
        else None,
        "search_query": request.search_query,
        "selected_search_mode": "enterprise_search",
        "selected_runtime_domain": "enterprise_search",
        "assistant_search_execution_prepared": ready,
        "lexical_search_used": ready,
        "postgresql_fts_used": ready,
        "semantic_search_used": False,
        "hybrid_search_used": False,
        "qdrant_used": False,
        "reranking_used": False,
        "llm_used": False,
        "answer_generated": False,
        "tool_called": False,
        "workflow_executed": False,
        "external_action_called": False,
        "autonomous_execution": False,
        "postgresql_source_of_truth": True,
        "blocking_issues": sort_issues(blocking_issues),
        "warnings": sort_issues(warnings),
        "next_available_actions": [
            {
                "action": "execute_assistant_enterprise_search",
                "available": ready,
                "status": "ready" if ready else "blocked",
                "reason": None if ready else "assistant_search_execution_gateway_blocked",
            }
        ],
    }


def build_assistant_search_execution_health(db: Session) -> dict[str, Any]:
    return AssistantSearchExecutionHealthResult().as_dict()
