"""Assistant Runtime session foundation."""

from __future__ import annotations

import hashlib
import re
from typing import Any

from app.services.assistant_contracts import AssistantDefinitionRequest, AssistantSessionDescriptor
from app.services.enterprise_search_session import issue, sort_issues

ASSISTANT_STATE_BLOCKED = "blocked"
ASSISTANT_STATE_READY = "ready"
SUPPORTED_SEARCH_MODES = {"none", "enterprise_search", "semantic_search", "hybrid_search"}
SEARCH_MODE_RUNTIME_DOMAIN = {
    "none": "assistant_runtime",
    "enterprise_search": "enterprise_search",
    "semantic_search": "semantic_search_runtime",
    "hybrid_search": "hybrid_search_runtime",
}
SUPPORTED_RUNTIME_DOMAINS = {
    "enterprise_search",
    "hybrid_search_runtime",
    "semantic_search_runtime",
    "workflow_runtime",
}
BLOCKED_TOKENS = {
    "llm",
    "answer",
    "generate",
    "tool",
    "workflow_execute",
    "execute_workflow",
    "external",
    "autonomous",
    "agent",
    "assistant_loop",
}


def _stable_session_id(*, assistant_key: str, assistant_version: str, selected_search_mode: str) -> str | None:
    if not assistant_key:
        return None
    digest = hashlib.sha256(
        f"{assistant_key}|{assistant_version}|{selected_search_mode}|assistant-runtime".encode()
    ).hexdigest()[:24]
    return f"assistant-session:{digest}"


def _normalize_key(value: str | None, fallback: str) -> str:
    raw = (value or fallback).strip().lower()
    normalized = re.sub(r"[^a-z0-9_-]+", "-", raw).strip("-")
    return normalized or fallback


def build_assistant_definition_request(
    *,
    assistant_name: str | None,
    assistant_key: str | None = None,
    assistant_version: str | None = None,
    assistant_type: str | None = None,
    description: str | None = None,
    default_search_mode: str | None = None,
    allowed_runtime_domains: list[str] | None = None,
    guardrail_profile: dict[str, Any] | None = None,
    requested_by: str | None = None,
    conversation_reference: str | None = None,
    requested_query: str | None = None,
    runtime_context: dict[str, Any] | None = None,
    runtime_metadata: dict[str, Any] | None = None,
) -> AssistantDefinitionRequest:
    resolved_name = (assistant_name or "").strip()
    resolved_key = _normalize_key(assistant_key, resolved_name or "assistant")
    return AssistantDefinitionRequest(
        assistant_key=resolved_key,
        assistant_name=resolved_name,
        assistant_version=(assistant_version or "1.0").strip() or "1.0",
        assistant_type=(assistant_type or "platform_assistant").strip() or "platform_assistant",
        description=description,
        default_search_mode=(default_search_mode or "enterprise_search").strip() or "enterprise_search",
        allowed_runtime_domains=list(allowed_runtime_domains or ["enterprise_search"]),
        guardrail_profile=dict(guardrail_profile or {}),
        requested_by=requested_by,
        conversation_reference=conversation_reference,
        requested_query=requested_query,
        runtime_context=dict(runtime_context or {}),
        runtime_metadata=dict(runtime_metadata or {}),
    )


def build_assistant_session(request: AssistantDefinitionRequest) -> AssistantSessionDescriptor:
    blocking_issues: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    if not request.assistant_name.strip():
        blocking_issues.append(
            issue(
                "assistant_name_missing",
                "Assistant definition requires a generic assistant name.",
                component="assistant_session",
            )
        )
    if not request.assistant_key.strip():
        blocking_issues.append(
            issue(
                "assistant_key_missing",
                "Assistant definition requires an assistant key.",
                component="assistant_session",
            )
        )
    if request.default_search_mode not in SUPPORTED_SEARCH_MODES:
        blocking_issues.append(
            issue(
                "assistant_search_mode_unsupported",
                "Assistant default search mode is not supported.",
                component="assistant_session",
                item_id=request.default_search_mode,
            )
        )
    if not request.allowed_runtime_domains:
        blocking_issues.append(
            issue(
                "assistant_runtime_domains_missing",
                "Assistant definition requires at least one allowed metadata runtime domain.",
                component="assistant_session",
            )
        )
    for domain in request.allowed_runtime_domains:
        if domain not in SUPPORTED_RUNTIME_DOMAINS:
            blocking_issues.append(
                issue(
                    "assistant_runtime_domain_unsupported",
                    "Assistant runtime domain is not supported by metadata-only assistant runtime.",
                    component="assistant_session",
                    item_id=domain,
                )
            )
    selected_runtime_domain = SEARCH_MODE_RUNTIME_DOMAIN.get(request.default_search_mode, "enterprise_search")
    if request.default_search_mode != "none" and selected_runtime_domain not in request.allowed_runtime_domains:
        blocking_issues.append(
            issue(
                "assistant_runtime_domain_not_allowed",
                "Assistant default search mode must map to an allowed runtime domain.",
                component="assistant_session",
                item_id=selected_runtime_domain,
            )
        )
    metadata_text = " ".join(
        [
            request.assistant_type,
            request.default_search_mode,
            " ".join(request.allowed_runtime_domains),
            str(request.runtime_metadata),
        ]
    )
    lowered_tokens = {token for token in re.split(r"[^a-z0-9_]+", metadata_text.lower()) if token}
    if lowered_tokens.intersection(BLOCKED_TOKENS):
        warnings.append(
            issue(
                "assistant_execution_capability_disabled",
                "Assistant Runtime foundation records metadata only and disables LLM, answer, tool, "
                "workflow and autonomous execution.",
                component="assistant_session",
                severity="warning",
            )
        )
    ready = not blocking_issues
    return AssistantSessionDescriptor(
        assistant_session_id=_stable_session_id(
            assistant_key=request.assistant_key,
            assistant_version=request.assistant_version,
            selected_search_mode=request.default_search_mode,
        ),
        request=request,
        assistant_state=ASSISTANT_STATE_READY if ready else ASSISTANT_STATE_BLOCKED,
        selected_search_mode=request.default_search_mode,
        selected_runtime_domain=selected_runtime_domain,
        runtime_metadata={
            **dict(request.runtime_metadata),
            "assistant_runtime_version": "assistant_runtime/1.0",
            "assistant_execution_planned": ready,
            "assistant_executed": False,
            "llm_used": False,
            "answer_generated": False,
            "tool_called": False,
            "workflow_executed": False,
            "external_action_called": False,
            "autonomous_execution": False,
            "enterprise_search_used": False,
            "hybrid_search_used": False,
            "postgresql_source_of_truth": True,
        },
        blocking_issues=sort_issues(blocking_issues),
        warnings=sort_issues(warnings),
        next_available_actions=[
            {
                "action": "persist_assistant_runtime_metadata",
                "available": ready,
                "status": "ready" if ready else "blocked",
                "reason": None if ready else "assistant_session_blocked",
            }
        ],
    )


def serialize_assistant_session(session: AssistantSessionDescriptor) -> dict[str, Any]:
    return session.as_dict()
