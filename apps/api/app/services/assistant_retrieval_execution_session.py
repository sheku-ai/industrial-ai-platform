"""Assistant Retrieval Execution Readiness session foundation."""

from __future__ import annotations

import hashlib
from typing import Any

from app.services.assistant_retrieval_execution_contracts import (
    AssistantRetrievalExecutionReadinessRequest,
    AssistantRetrievalExecutionSessionDescriptor,
)
from app.services.enterprise_search_session import issue, sort_issues

ASSISTANT_RETRIEVAL_EXECUTION_STATE_BLOCKED = "blocked"
ASSISTANT_RETRIEVAL_EXECUTION_STATE_READY = "ready"
SUPPORTED_EXECUTION_READINESS_SEARCH_MODES = {"enterprise_search"}


def _stable_readiness_session_id(*, retrieval_plan_id: str, selected_search_mode: str) -> str | None:
    if not retrieval_plan_id:
        return None
    digest = hashlib.sha256(
        f"{retrieval_plan_id}|{selected_search_mode}|assistant-retrieval-execution-readiness".encode()
    ).hexdigest()[:24]
    return f"assistant-retrieval-execution-session:{digest}"


def build_assistant_retrieval_execution_request(
    *,
    retrieval_plan_id: str,
    assistant_id: str,
    assistant_session_id: str | None,
    selected_search_mode: str | None,
    selected_runtime_domain: str | None,
    readiness_metadata: dict[str, Any] | None = None,
) -> AssistantRetrievalExecutionReadinessRequest:
    search_mode = (selected_search_mode or "enterprise_search").strip() or "enterprise_search"
    runtime_domain = (selected_runtime_domain or "enterprise_search").strip() or "enterprise_search"
    return AssistantRetrievalExecutionReadinessRequest(
        retrieval_plan_id=str(retrieval_plan_id),
        assistant_id=str(assistant_id),
        assistant_session_id=str(assistant_session_id) if assistant_session_id else None,
        selected_search_mode=search_mode,
        selected_runtime_domain=runtime_domain,
        readiness_metadata=dict(readiness_metadata or {}),
    )


def build_assistant_retrieval_execution_session(
    request: AssistantRetrievalExecutionReadinessRequest,
) -> AssistantRetrievalExecutionSessionDescriptor:
    blocking_issues: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    if not request.retrieval_plan_id.strip():
        blocking_issues.append(
            issue(
                "retrieval_plan_id_missing",
                "Assistant retrieval execution readiness requires a retrieval_plan_id.",
                component="assistant_retrieval_execution_session",
            )
        )
    if not request.assistant_id.strip():
        blocking_issues.append(
            issue(
                "assistant_id_missing",
                "Assistant retrieval execution readiness requires an assistant_id.",
                component="assistant_retrieval_execution_session",
            )
        )
    if request.selected_search_mode not in SUPPORTED_EXECUTION_READINESS_SEARCH_MODES:
        blocking_issues.append(
            issue(
                "execution_readiness_search_mode_not_enabled",
                "Assistant retrieval execution readiness currently prepares Enterprise Search metadata only.",
                component="assistant_retrieval_execution_session",
                item_id=request.selected_search_mode,
            )
        )
    if request.selected_runtime_domain != "enterprise_search":
        blocking_issues.append(
            issue(
                "execution_readiness_runtime_domain_not_enabled",
                "Assistant retrieval execution readiness currently prepares the enterprise_search runtime domain only.",
                component="assistant_retrieval_execution_session",
                item_id=request.selected_runtime_domain,
            )
        )
    ready = not blocking_issues
    return AssistantRetrievalExecutionSessionDescriptor(
        readiness_session_id=_stable_readiness_session_id(
            retrieval_plan_id=request.retrieval_plan_id,
            selected_search_mode=request.selected_search_mode,
        ),
        request=request,
        readiness_state=ASSISTANT_RETRIEVAL_EXECUTION_STATE_READY
        if ready
        else ASSISTANT_RETRIEVAL_EXECUTION_STATE_BLOCKED,
        enterprise_search_execution_prepared=ready and request.selected_search_mode == "enterprise_search",
        semantic_search_execution_prepared=False,
        hybrid_search_execution_prepared=False,
        blocking_issues=sort_issues(blocking_issues),
        warnings=sort_issues(warnings),
        next_available_actions=[
            {
                "action": "persist_assistant_retrieval_execution_readiness",
                "available": ready,
                "status": "ready" if ready else "blocked",
                "reason": None if ready else "assistant_retrieval_execution_session_blocked",
            }
        ],
    )


def serialize_assistant_retrieval_execution_session(
    session: AssistantRetrievalExecutionSessionDescriptor,
) -> dict[str, Any]:
    return session.as_dict()
