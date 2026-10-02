"""Assistant Citation Verification session foundation."""

from __future__ import annotations

import hashlib
from typing import Any

from app.services.assistant_citation_verification_contracts import (
    AssistantCitationVerificationRequest,
    AssistantCitationVerificationSessionDescriptor,
)
from app.services.enterprise_search_session import issue, sort_issues

ASSISTANT_CITATION_VERIFICATION_STATE_BLOCKED = "blocked"
ASSISTANT_CITATION_VERIFICATION_STATE_READY = "ready"


def _stable_citation_verification_session_id(*, llm_execution_id: str, context_package_id: str) -> str | None:
    if not llm_execution_id:
        return None
    digest = hashlib.sha256(
        f"{llm_execution_id}|{context_package_id}|assistant-citation-verification".encode()
    ).hexdigest()[:24]
    return f"assistant-citation-verification-session:{digest}"


def build_assistant_citation_verification_request(
    *,
    llm_execution_id: str,
    prompt_package_id: str,
    context_package_id: str,
    assistant_runtime_id: str | None = None,
    raw_output_available: bool = False,
    context_citation_count: int = 0,
    request_metadata: dict[str, Any] | None = None,
) -> AssistantCitationVerificationRequest:
    return AssistantCitationVerificationRequest(
        llm_execution_id=str(llm_execution_id),
        prompt_package_id=str(prompt_package_id),
        context_package_id=str(context_package_id),
        assistant_runtime_id=str(assistant_runtime_id) if assistant_runtime_id else None,
        raw_output_available=bool(raw_output_available),
        context_citation_count=max(0, int(context_citation_count or 0)),
        request_metadata=dict(request_metadata or {}),
    )


def build_assistant_citation_verification_session(
    request: AssistantCitationVerificationRequest,
) -> AssistantCitationVerificationSessionDescriptor:
    blocking_issues: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    if not request.llm_execution_id.strip():
        blocking_issues.append(
            issue(
                "llm_execution_id_missing",
                "Assistant citation verification requires an llm_execution_id.",
                component="assistant_citation_verification_session",
            )
        )
    if not request.prompt_package_id.strip():
        blocking_issues.append(
            issue(
                "prompt_package_id_missing",
                "Assistant citation verification requires a prompt_package_id.",
                component="assistant_citation_verification_session",
            )
        )
    if not request.context_package_id.strip():
        blocking_issues.append(
            issue(
                "context_package_id_missing",
                "Assistant citation verification requires a context_package_id.",
                component="assistant_citation_verification_session",
            )
        )
    if not request.raw_output_available:
        blocking_issues.append(
            issue(
                "raw_output_missing",
                "Assistant citation verification requires persisted raw model output.",
                component="assistant_citation_verification_session",
            )
        )
    if request.context_citation_count <= 0:
        blocking_issues.append(
            issue(
                "context_citations_missing",
                "Assistant citation verification requires at least one context citation.",
                component="assistant_citation_verification_session",
            )
        )
    ready = not blocking_issues
    return AssistantCitationVerificationSessionDescriptor(
        citation_verification_session_id=_stable_citation_verification_session_id(
            llm_execution_id=request.llm_execution_id, context_package_id=request.context_package_id
        ),
        request=request,
        verification_state=ASSISTANT_CITATION_VERIFICATION_STATE_READY
        if ready
        else ASSISTANT_CITATION_VERIFICATION_STATE_BLOCKED,
        blocking_issues=sort_issues(blocking_issues),
        warnings=sort_issues(warnings),
        next_available_actions=[
            {
                "action": "verify_assistant_citations",
                "available": ready,
                "status": "ready" if ready else "blocked",
                "reason": None if ready else "assistant_citation_verification_session_blocked",
            }
        ],
    )


def serialize_assistant_citation_verification_session(
    session: AssistantCitationVerificationSessionDescriptor,
) -> dict[str, Any]:
    return session.as_dict()
