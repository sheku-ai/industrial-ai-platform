"""Assistant Retrieval Planning session foundation."""

from __future__ import annotations

import hashlib
from typing import Any

from app.services.assistant_retrieval_contracts import (
    AssistantRetrievalPlanRequest,
    AssistantRetrievalSessionDescriptor,
)
from app.services.enterprise_search_session import issue, sort_issues

ASSISTANT_RETRIEVAL_STATE_BLOCKED = "blocked"
ASSISTANT_RETRIEVAL_STATE_READY = "ready"
SUPPORTED_RETRIEVAL_SEARCH_MODES = {"enterprise_search"}
SEARCH_MODE_RUNTIME_DOMAIN = {"enterprise_search": "enterprise_search"}


def _stable_retrieval_session_id(
    *, assistant_id: str, assistant_session_id: str | None, selected_search_mode: str
) -> str | None:
    if not assistant_id:
        return None
    digest = hashlib.sha256(
        f"{assistant_id}|{assistant_session_id or ''}|{selected_search_mode}|assistant-retrieval-runtime".encode()
    ).hexdigest()[:24]
    return f"assistant-retrieval-session:{digest}"


def build_assistant_retrieval_plan_request(
    *,
    assistant_id: str,
    assistant_session_id: str | None = None,
    requested_query: str | None = None,
    selected_search_mode: str | None = None,
    runtime_metadata: dict[str, Any] | None = None,
) -> AssistantRetrievalPlanRequest:
    search_mode = (selected_search_mode or "enterprise_search").strip() or "enterprise_search"
    return AssistantRetrievalPlanRequest(
        assistant_id=str(assistant_id),
        assistant_session_id=str(assistant_session_id) if assistant_session_id else None,
        requested_query=requested_query,
        selected_search_mode=search_mode,
        selected_runtime_domain=SEARCH_MODE_RUNTIME_DOMAIN.get(search_mode, "enterprise_search"),
        runtime_metadata=dict(runtime_metadata or {}),
    )


def build_assistant_retrieval_session(request: AssistantRetrievalPlanRequest) -> AssistantRetrievalSessionDescriptor:
    blocking_issues: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    if not request.assistant_id.strip():
        blocking_issues.append(
            issue(
                "assistant_id_missing",
                "Assistant retrieval planning requires an assistant_id.",
                component="assistant_retrieval_session",
            )
        )
    if request.selected_search_mode not in SUPPORTED_RETRIEVAL_SEARCH_MODES:
        blocking_issues.append(
            issue(
                "retrieval_search_mode_not_enabled",
                "Assistant retrieval planning foundation only prepares Enterprise Search metadata plans.",
                component="assistant_retrieval_session",
                item_id=request.selected_search_mode,
            )
        )
    ready = not blocking_issues
    return AssistantRetrievalSessionDescriptor(
        retrieval_session_id=_stable_retrieval_session_id(
            assistant_id=request.assistant_id,
            assistant_session_id=request.assistant_session_id,
            selected_search_mode=request.selected_search_mode,
        ),
        request=request,
        retrieval_state=ASSISTANT_RETRIEVAL_STATE_READY if ready else ASSISTANT_RETRIEVAL_STATE_BLOCKED,
        enterprise_search_planned=ready and request.selected_search_mode == "enterprise_search",
        semantic_search_planned=False,
        hybrid_search_planned=False,
        runtime_metadata={
            **dict(request.runtime_metadata),
            "assistant_retrieval_runtime_version": "assistant_retrieval_runtime/1.0",
            "retrieval_plan_created": ready,
            "retrieval_executed": False,
            "answer_generated": False,
            "llm_used": False,
            "tool_called": False,
            "workflow_executed": False,
            "autonomous_execution": False,
            "postgresql_source_of_truth": True,
        },
        blocking_issues=sort_issues(blocking_issues),
        warnings=sort_issues(warnings),
        next_available_actions=[
            {
                "action": "persist_assistant_retrieval_plan_metadata",
                "available": ready,
                "status": "ready" if ready else "blocked",
                "reason": None if ready else "assistant_retrieval_session_blocked",
            }
        ],
    )


def serialize_assistant_retrieval_session(session: AssistantRetrievalSessionDescriptor) -> dict[str, Any]:
    return session.as_dict()
