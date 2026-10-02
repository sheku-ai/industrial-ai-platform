"""Assistant Enterprise Search Execution session foundation."""

from __future__ import annotations

import hashlib
from typing import Any

from app.services.assistant_search_execution_contracts import (
    AssistantSearchExecutionRequest,
    AssistantSearchExecutionSessionDescriptor,
)
from app.services.enterprise_search_session import issue, sort_issues

ASSISTANT_SEARCH_EXECUTION_STATE_BLOCKED = "blocked"
ASSISTANT_SEARCH_EXECUTION_STATE_READY = "ready"


def _stable_search_execution_session_id(*, execution_plan_id: str, search_query: str) -> str | None:
    if not execution_plan_id:
        return None
    digest = hashlib.sha256(f"{execution_plan_id}|{search_query}|assistant-search-execution".encode()).hexdigest()[:24]
    return f"assistant-search-execution-session:{digest}"


def build_assistant_search_execution_request(
    *,
    execution_plan_id: str,
    retrieval_plan_id: str,
    assistant_id: str,
    assistant_session_id: str | None,
    search_query: str | None,
    top_k: int | None = None,
    search_config: dict[str, Any] | None = None,
) -> AssistantSearchExecutionRequest:
    return AssistantSearchExecutionRequest(
        execution_plan_id=str(execution_plan_id),
        retrieval_plan_id=str(retrieval_plan_id),
        assistant_id=str(assistant_id),
        assistant_session_id=str(assistant_session_id) if assistant_session_id else None,
        search_query=(search_query or "").strip(),
        search_mode="enterprise_search",
        runtime_domain="enterprise_search",
        top_k=max(1, min(int(top_k or 10), 50)),
        search_config=dict(search_config or {}),
    )


def build_assistant_search_execution_session(
    request: AssistantSearchExecutionRequest,
) -> AssistantSearchExecutionSessionDescriptor:
    blocking_issues: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    if not request.execution_plan_id.strip():
        blocking_issues.append(
            issue(
                "execution_plan_id_missing",
                "Assistant search execution requires an execution_plan_id.",
                component="assistant_search_execution_session",
            )
        )
    if not request.retrieval_plan_id.strip():
        blocking_issues.append(
            issue(
                "retrieval_plan_id_missing",
                "Assistant search execution requires a retrieval_plan_id.",
                component="assistant_search_execution_session",
            )
        )
    if not request.assistant_id.strip():
        blocking_issues.append(
            issue(
                "assistant_id_missing",
                "Assistant search execution requires an assistant_id.",
                component="assistant_search_execution_session",
            )
        )
    if not request.search_query.strip():
        blocking_issues.append(
            issue(
                "search_query_missing",
                "Assistant search execution requires a search query.",
                component="assistant_search_execution_session",
            )
        )
    if request.search_mode != "enterprise_search":
        blocking_issues.append(
            issue(
                "search_mode_not_supported",
                "Assistant search execution supports only Enterprise Search.",
                component="assistant_search_execution_session",
                item_id=request.search_mode,
            )
        )
    if request.runtime_domain != "enterprise_search":
        blocking_issues.append(
            issue(
                "runtime_domain_not_supported",
                "Assistant search execution supports only the enterprise_search runtime domain.",
                component="assistant_search_execution_session",
                item_id=request.runtime_domain,
            )
        )
    ready = not blocking_issues
    return AssistantSearchExecutionSessionDescriptor(
        search_execution_session_id=_stable_search_execution_session_id(
            execution_plan_id=request.execution_plan_id, search_query=request.search_query
        ),
        request=request,
        search_execution_state=ASSISTANT_SEARCH_EXECUTION_STATE_READY
        if ready
        else ASSISTANT_SEARCH_EXECUTION_STATE_BLOCKED,
        blocking_issues=sort_issues(blocking_issues),
        warnings=sort_issues(warnings),
        next_available_actions=[
            {
                "action": "execute_enterprise_search",
                "available": ready,
                "status": "ready" if ready else "blocked",
                "reason": None if ready else "assistant_search_execution_session_blocked",
            }
        ],
    )


def serialize_assistant_search_execution_session(session: AssistantSearchExecutionSessionDescriptor) -> dict[str, Any]:
    return session.as_dict()
