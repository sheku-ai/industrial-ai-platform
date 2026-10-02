"""Assistant Context Builder gateway."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.repositories.assistant import AssistantRepository
from app.services.assistant_context_builder_contracts import AssistantContextBuilderHealthResult
from app.services.assistant_context_builder_session import (
    build_assistant_context_builder_request,
    build_assistant_context_builder_session,
    serialize_assistant_context_builder_session,
)
from app.services.enterprise_search_session import issue, sort_issues


def build_assistant_context_builder_gateway(
    db: Session,
    *,
    search_execution_id: str,
    package_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    blocking_issues: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    repository = AssistantRepository(db)
    search_execution = None
    try:
        search_execution_uuid = uuid.UUID(str(search_execution_id))
    except (TypeError, ValueError):
        blocking_issues.append(
            issue(
                "search_execution_id_invalid",
                "Assistant context builder requires a valid search_execution_id.",
                component="assistant_context_builder_gateway",
                item_id=str(search_execution_id),
            )
        )
    else:
        search_execution = repository.get_assistant_search_execution(search_execution_uuid)
        if search_execution is None:
            blocking_issues.append(
                issue(
                    "search_execution_not_found",
                    "Assistant context builder requires an existing assistant search execution.",
                    component="assistant_context_builder_gateway",
                    item_id=str(search_execution_uuid),
                )
            )
    request = build_assistant_context_builder_request(
        search_execution_id=str(search_execution_id),
        assistant_id=str(search_execution.assistant_id) if search_execution is not None else "",
        assistant_session_id=str(search_execution.assistant_session_id)
        if search_execution is not None and search_execution.assistant_session_id
        else None,
        result_count=int(search_execution.result_count or 0) if search_execution is not None else 0,
        package_metadata=package_metadata,
    )
    session = serialize_assistant_context_builder_session(build_assistant_context_builder_session(request))
    blocking_issues.extend(session.get("blocking_issues") or [])
    warnings.extend(session.get("warnings") or [])
    if search_execution is not None:
        if not search_execution.search_completed:
            blocking_issues.append(
                issue(
                    "search_execution_not_completed",
                    "Assistant context builder requires a completed search execution.",
                    component="assistant_context_builder_gateway",
                    item_id=str(search_execution.search_execution_id),
                )
            )
        if (
            not search_execution.postgresql_fts_used
            or search_execution.semantic_search_used
            or search_execution.hybrid_search_used
        ):
            blocking_issues.append(
                issue(
                    "search_execution_not_enterprise_fts",
                    "Assistant context builder requires PostgreSQL FTS Enterprise Search results only.",
                    component="assistant_context_builder_gateway",
                    item_id=str(search_execution.search_execution_id),
                )
            )
    ready = bool(session.get("assistant_context_builder_session_ready")) and not blocking_issues
    return {
        "assistant_context_builder_gateway_schema_version": "1",
        "assistant_context_builder_gateway_ready": ready,
        "gateway_status": "ready" if ready else "blocked",
        "assistant_context_builder_session": session,
        "search_execution_id": str(search_execution.search_execution_id)
        if search_execution is not None
        else str(search_execution_id),
        "assistant_id": str(search_execution.assistant_id) if search_execution is not None else None,
        "assistant_session_id": str(search_execution.assistant_session_id)
        if search_execution is not None and search_execution.assistant_session_id
        else None,
        "assistant_context_builder_prepared": ready,
        "search_execution_completed": ready,
        "ordered_context_created": ready,
        "ordered_citations_created": ready,
        "token_estimation_completed": ready,
        "llm_used": False,
        "answer_generated": False,
        "workflow_executed": False,
        "tool_called": False,
        "external_action_called": False,
        "autonomous_execution": False,
        "postgresql_source_of_truth": True,
        "blocking_issues": sort_issues(blocking_issues),
        "warnings": sort_issues(warnings),
        "next_available_actions": [
            {
                "action": "create_assistant_context_package",
                "available": ready,
                "status": "ready" if ready else "blocked",
                "reason": None if ready else "assistant_context_builder_gateway_blocked",
            }
        ],
    }


def build_assistant_context_builder_health(db: Session) -> dict[str, Any]:
    return AssistantContextBuilderHealthResult().as_dict()
