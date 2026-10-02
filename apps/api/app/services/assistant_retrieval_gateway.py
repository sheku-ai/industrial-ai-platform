"""Assistant Retrieval Planning gateway."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.models.assistant_runtime import AssistantSession
from app.repositories.assistant import AssistantRepository
from app.services.assistant_retrieval_contracts import AssistantRetrievalHealthResult
from app.services.assistant_retrieval_session import (
    build_assistant_retrieval_plan_request,
    build_assistant_retrieval_session,
    serialize_assistant_retrieval_session,
)
from app.services.enterprise_search_session import issue, sort_issues


def build_assistant_retrieval_gateway(
    db: Session,
    *,
    assistant_id: str,
    assistant_session_id: str | None = None,
    organization_id: uuid.UUID | None = None,
    requested_query: str | None = None,
    selected_search_mode: str | None = None,
    runtime_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    request = build_assistant_retrieval_plan_request(
        assistant_id=assistant_id,
        assistant_session_id=assistant_session_id,
        requested_query=requested_query,
        selected_search_mode=selected_search_mode,
        runtime_metadata=runtime_metadata,
    )
    session = serialize_assistant_retrieval_session(build_assistant_retrieval_session(request))
    blocking_issues = list(session.get("blocking_issues") or [])
    warnings = list(session.get("warnings") or [])
    repository = AssistantRepository(db)
    assistant = None
    assistant_session = None
    try:
        assistant_uuid = uuid.UUID(str(assistant_id))
    except (TypeError, ValueError):
        blocking_issues.append(
            issue(
                "assistant_id_invalid",
                "Assistant retrieval planning requires a valid assistant_id.",
                component="assistant_retrieval_gateway",
                item_id=str(assistant_id),
            )
        )
    else:
        assistant = repository.get_scoped_assistant_definition(assistant_uuid, organization_id=organization_id)
        if assistant is None:
            blocking_issues.append(
                issue(
                    "assistant_not_found",
                    "Assistant retrieval planning requires an existing assistant.",
                    component="assistant_retrieval_gateway",
                    item_id=str(assistant_uuid),
                )
            )
    if assistant_session_id:
        try:
            assistant_session_uuid = uuid.UUID(str(assistant_session_id))
        except (TypeError, ValueError):
            blocking_issues.append(
                issue(
                    "assistant_session_id_invalid",
                    "Assistant retrieval planning requires a valid assistant_session_id when provided.",
                    component="assistant_retrieval_gateway",
                    item_id=str(assistant_session_id),
                )
            )
        else:
            assistant_session = (
                repository.get_scoped_assistant_session(
                    assistant_session_uuid, organization_id=organization_id
                )
                if organization_id is not None
                else repository.get_scoped_artifact(
                    AssistantSession,
                    AssistantSession.assistant_session_id,
                    assistant_session_uuid,
                    organization_id=None,
                )
            )
            if assistant_session is None:
                blocking_issues.append(
                    issue(
                        "assistant_session_not_found",
                        "Assistant retrieval planning requires a session in the authorized scope.",
                        component="assistant_retrieval_gateway",
                        item_id=str(assistant_session_uuid),
                    )
                )
            elif assistant is not None and assistant_session.assistant_id != assistant.assistant_id:
                blocking_issues.append(
                    issue(
                        "assistant_session_mismatch",
                        "Assistant session must belong to the selected assistant.",
                        component="assistant_retrieval_gateway",
                        item_id=str(assistant_session_uuid),
                    )
                )
    if assistant is not None and assistant.assistant_status not in {"prepared", "active"}:
        blocking_issues.append(
            issue(
                "assistant_status_not_plannable",
                "Assistant retrieval planning requires a prepared or active assistant.",
                component="assistant_retrieval_gateway",
                item_id=assistant.assistant_status,
            )
        )
    if assistant is not None and "enterprise_search" not in list(assistant.allowed_runtime_domains or []):
        blocking_issues.append(
            issue(
                "enterprise_search_not_allowed",
                "Assistant retrieval planning requires enterprise_search as an allowed runtime domain.",
                component="assistant_retrieval_gateway",
            )
        )
    ready = bool(session.get("assistant_retrieval_session_ready")) and not blocking_issues
    return {
        "assistant_retrieval_gateway_schema_version": "1",
        "assistant_retrieval_gateway_ready": ready,
        "gateway_status": "ready" if ready else "blocked",
        "assistant_retrieval_session": session,
        "source_of_truth": "postgresql",
        "assistant_retrieval_runtime_prepared": ready,
        "retrieval_plan_created": ready,
        "selected_search_mode": request.selected_search_mode,
        "selected_runtime_domain": request.selected_runtime_domain,
        "enterprise_search_planned": ready and request.selected_search_mode == "enterprise_search",
        "hybrid_search_planned": False,
        "semantic_search_planned": False,
        "retrieval_executed": False,
        "answer_generated": False,
        "llm_used": False,
        "tool_called": False,
        "workflow_executed": False,
        "autonomous_execution": False,
        "postgresql_source_of_truth": True,
        "blocking_issues": sort_issues(blocking_issues),
        "warnings": sort_issues(warnings),
        "next_available_actions": [
            {
                "action": "create_assistant_retrieval_plan",
                "available": ready,
                "status": "ready" if ready else "blocked",
                "reason": None if ready else "assistant_retrieval_gateway_blocked",
            }
        ],
    }


def build_assistant_retrieval_health(db: Session) -> dict[str, Any]:
    assistants = AssistantRepository(db).list_assistant_definitions(limit=500)
    return {
        **AssistantRetrievalHealthResult().as_dict(),
        "assistant_count": len(assistants),
    }
