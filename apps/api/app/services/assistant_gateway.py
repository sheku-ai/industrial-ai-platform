"""Assistant Runtime gateway."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.repositories.assistant import AssistantRepository
from app.services.assistant_contracts import AssistantHealthResult
from app.services.assistant_session import (
    build_assistant_definition_request,
    build_assistant_session,
    serialize_assistant_session,
)


def build_assistant_gateway(
    db: Session,
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
) -> dict[str, Any]:
    request = build_assistant_definition_request(
        assistant_name=assistant_name,
        assistant_key=assistant_key,
        assistant_version=assistant_version,
        assistant_type=assistant_type,
        description=description,
        default_search_mode=default_search_mode,
        allowed_runtime_domains=allowed_runtime_domains,
        guardrail_profile=guardrail_profile,
        requested_by=requested_by,
        conversation_reference=conversation_reference,
        requested_query=requested_query,
        runtime_context=runtime_context,
        runtime_metadata=runtime_metadata,
    )
    session = serialize_assistant_session(build_assistant_session(request))
    ready = bool(session.get("assistant_session_ready")) and not session.get("blocking_issues")
    return {
        "assistant_gateway_schema_version": "1",
        "assistant_gateway_ready": ready,
        "gateway_status": "ready" if ready else "blocked",
        "assistant_session": session,
        "source_of_truth": "postgresql",
        "assistant_runtime_prepared": ready,
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
        "blocking_issues": session.get("blocking_issues") or [],
        "warnings": session.get("warnings") or [],
        "next_available_actions": [
            {
                "action": "create_assistant_runtime_run",
                "available": ready,
                "status": "ready" if ready else "blocked",
                "reason": None if ready else "assistant_gateway_blocked",
            }
        ],
    }


def build_assistant_health(db: Session) -> dict[str, Any]:
    assistants = AssistantRepository(db).list_assistant_definitions(limit=500)
    return {
        **AssistantHealthResult().as_dict(),
        "assistant_count": len(assistants),
    }
