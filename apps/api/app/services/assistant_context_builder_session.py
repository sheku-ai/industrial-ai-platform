"""Assistant Context Builder session foundation."""

from __future__ import annotations

import hashlib
from typing import Any

from app.services.assistant_context_builder_contracts import (
    AssistantContextBuilderRequest,
    AssistantContextBuilderSessionDescriptor,
)
from app.services.enterprise_search_session import issue, sort_issues

ASSISTANT_CONTEXT_BUILDER_STATE_BLOCKED = "blocked"
ASSISTANT_CONTEXT_BUILDER_STATE_READY = "ready"


def _stable_context_builder_session_id(*, search_execution_id: str) -> str | None:
    if not search_execution_id:
        return None
    digest = hashlib.sha256(f"{search_execution_id}|assistant-context-builder".encode()).hexdigest()[:24]
    return f"assistant-context-builder-session:{digest}"


def build_assistant_context_builder_request(
    *,
    search_execution_id: str,
    assistant_id: str,
    assistant_session_id: str | None,
    result_count: int,
    package_metadata: dict[str, Any] | None = None,
) -> AssistantContextBuilderRequest:
    return AssistantContextBuilderRequest(
        search_execution_id=str(search_execution_id),
        assistant_id=str(assistant_id),
        assistant_session_id=str(assistant_session_id) if assistant_session_id else None,
        result_count=max(0, int(result_count or 0)),
        package_metadata=dict(package_metadata or {}),
    )


def build_assistant_context_builder_session(
    request: AssistantContextBuilderRequest,
) -> AssistantContextBuilderSessionDescriptor:
    blocking_issues: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    if not request.search_execution_id.strip():
        blocking_issues.append(
            issue(
                "search_execution_id_missing",
                "Assistant context builder requires a search_execution_id.",
                component="assistant_context_builder_session",
            )
        )
    if not request.assistant_id.strip():
        blocking_issues.append(
            issue(
                "assistant_id_missing",
                "Assistant context builder requires an assistant_id.",
                component="assistant_context_builder_session",
            )
        )
    if request.result_count <= 0:
        blocking_issues.append(
            issue(
                "search_results_missing",
                "Assistant context builder requires at least one search result.",
                component="assistant_context_builder_session",
            )
        )
    ready = not blocking_issues
    return AssistantContextBuilderSessionDescriptor(
        context_builder_session_id=_stable_context_builder_session_id(search_execution_id=request.search_execution_id),
        request=request,
        context_builder_state=ASSISTANT_CONTEXT_BUILDER_STATE_READY
        if ready
        else ASSISTANT_CONTEXT_BUILDER_STATE_BLOCKED,
        blocking_issues=sort_issues(blocking_issues),
        warnings=sort_issues(warnings),
        next_available_actions=[
            {
                "action": "create_assistant_context_package",
                "available": ready,
                "status": "ready" if ready else "blocked",
                "reason": None if ready else "assistant_context_builder_session_blocked",
            }
        ],
    )


def serialize_assistant_context_builder_session(session: AssistantContextBuilderSessionDescriptor) -> dict[str, Any]:
    return session.as_dict()
