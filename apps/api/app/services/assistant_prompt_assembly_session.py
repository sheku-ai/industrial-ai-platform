"""Assistant Prompt Assembly session foundation."""

from __future__ import annotations

import hashlib
from typing import Any

from app.services.assistant_prompt_assembly_contracts import (
    AssistantPromptAssemblyRequest,
    AssistantPromptAssemblySessionDescriptor,
)
from app.services.enterprise_search_session import issue, sort_issues

ASSISTANT_PROMPT_ASSEMBLY_STATE_BLOCKED = "blocked"
ASSISTANT_PROMPT_ASSEMBLY_STATE_READY = "ready"


def _stable_prompt_assembly_session_id(*, context_package_id: str) -> str | None:
    if not context_package_id:
        return None
    digest = hashlib.sha256(f"{context_package_id}|assistant-prompt-assembly".encode()).hexdigest()[:24]
    return f"assistant-prompt-assembly-session:{digest}"


def build_assistant_prompt_assembly_request(
    *,
    context_package_id: str,
    assistant_id: str,
    assistant_session_id: str | None,
    chunk_count: int,
    citation_count: int,
    prompt_metadata: dict[str, Any] | None = None,
) -> AssistantPromptAssemblyRequest:
    return AssistantPromptAssemblyRequest(
        context_package_id=str(context_package_id),
        assistant_id=str(assistant_id),
        assistant_session_id=str(assistant_session_id) if assistant_session_id else None,
        chunk_count=max(0, int(chunk_count or 0)),
        citation_count=max(0, int(citation_count or 0)),
        prompt_metadata=dict(prompt_metadata or {}),
    )


def build_assistant_prompt_assembly_session(
    request: AssistantPromptAssemblyRequest,
) -> AssistantPromptAssemblySessionDescriptor:
    blocking_issues: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    if not request.context_package_id.strip():
        blocking_issues.append(
            issue(
                "context_package_id_missing",
                "Assistant prompt assembly requires a context_package_id.",
                component="assistant_prompt_assembly_session",
            )
        )
    if not request.assistant_id.strip():
        blocking_issues.append(
            issue(
                "assistant_id_missing",
                "Assistant prompt assembly requires an assistant_id.",
                component="assistant_prompt_assembly_session",
            )
        )
    if request.chunk_count <= 0:
        blocking_issues.append(
            issue(
                "context_chunks_missing",
                "Assistant prompt assembly requires at least one context chunk.",
                component="assistant_prompt_assembly_session",
            )
        )
    if request.citation_count <= 0:
        blocking_issues.append(
            issue(
                "context_citations_missing",
                "Assistant prompt assembly requires at least one citation.",
                component="assistant_prompt_assembly_session",
            )
        )
    ready = not blocking_issues
    return AssistantPromptAssemblySessionDescriptor(
        prompt_assembly_session_id=_stable_prompt_assembly_session_id(context_package_id=request.context_package_id),
        request=request,
        prompt_assembly_state=ASSISTANT_PROMPT_ASSEMBLY_STATE_READY
        if ready
        else ASSISTANT_PROMPT_ASSEMBLY_STATE_BLOCKED,
        blocking_issues=sort_issues(blocking_issues),
        warnings=sort_issues(warnings),
        next_available_actions=[
            {
                "action": "create_assistant_prompt_package",
                "available": ready,
                "status": "ready" if ready else "blocked",
                "reason": None if ready else "assistant_prompt_assembly_session_blocked",
            }
        ],
    )


def serialize_assistant_prompt_assembly_session(session: AssistantPromptAssemblySessionDescriptor) -> dict[str, Any]:
    return session.as_dict()
