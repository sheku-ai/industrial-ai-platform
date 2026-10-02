"""Assistant Prompt Assembly gateway."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.repositories.assistant import AssistantRepository
from app.services.assistant_prompt_assembly_contracts import AssistantPromptAssemblyHealthResult
from app.services.assistant_prompt_assembly_session import (
    build_assistant_prompt_assembly_request,
    build_assistant_prompt_assembly_session,
    serialize_assistant_prompt_assembly_session,
)
from app.services.enterprise_search_session import issue, sort_issues


def build_assistant_prompt_assembly_gateway(
    db: Session,
    *,
    context_package_id: str,
    prompt_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    blocking_issues: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    repository = AssistantRepository(db)
    context_package = None
    try:
        context_package_uuid = uuid.UUID(str(context_package_id))
    except (TypeError, ValueError):
        blocking_issues.append(
            issue(
                "context_package_id_invalid",
                "Assistant prompt assembly requires a valid context_package_id.",
                component="assistant_prompt_assembly_gateway",
                item_id=str(context_package_id),
            )
        )
    else:
        context_package = repository.get_context_package(context_package_uuid)
        if context_package is None:
            blocking_issues.append(
                issue(
                    "context_package_not_found",
                    "Assistant prompt assembly requires an existing context package.",
                    component="assistant_prompt_assembly_gateway",
                    item_id=str(context_package_uuid),
                )
            )
    request = build_assistant_prompt_assembly_request(
        context_package_id=str(context_package_id),
        assistant_id=str(context_package.assistant_id) if context_package is not None else "",
        assistant_session_id=str(context_package.assistant_session_id)
        if context_package is not None and context_package.assistant_session_id
        else None,
        chunk_count=int(context_package.chunk_count or 0) if context_package is not None else 0,
        citation_count=int(context_package.citation_count or 0) if context_package is not None else 0,
        prompt_metadata=prompt_metadata,
    )
    session = serialize_assistant_prompt_assembly_session(build_assistant_prompt_assembly_session(request))
    blocking_issues.extend(session.get("blocking_issues") or [])
    warnings.extend(session.get("warnings") or [])
    if context_package is not None and context_package.package_status not in {"created", "prepared"}:
        blocking_issues.append(
            issue(
                "context_package_status_not_ready",
                "Assistant prompt assembly requires a created context package.",
                component="assistant_prompt_assembly_gateway",
                item_id=context_package.package_status,
            )
        )
    ready = bool(session.get("assistant_prompt_assembly_session_ready")) and not blocking_issues
    return {
        "assistant_prompt_assembly_gateway_schema_version": "1",
        "assistant_prompt_assembly_gateway_ready": ready,
        "gateway_status": "ready" if ready else "blocked",
        "assistant_prompt_assembly_session": session,
        "context_package_id": str(context_package.context_package_id)
        if context_package is not None
        else str(context_package_id),
        "assistant_id": str(context_package.assistant_id) if context_package is not None else None,
        "assistant_session_id": str(context_package.assistant_session_id)
        if context_package is not None and context_package.assistant_session_id
        else None,
        "assistant_prompt_assembly_prepared": ready,
        "context_package_created": ready,
        "llm_ready": ready,
        "llm_invoked": False,
        "answer_generated": False,
        "tool_called": False,
        "workflow_executed": False,
        "external_action_called": False,
        "autonomous_execution": False,
        "postgresql_source_of_truth": True,
        "blocking_issues": sort_issues(blocking_issues),
        "warnings": sort_issues(warnings),
        "next_available_actions": [
            {
                "action": "create_assistant_prompt_package",
                "available": ready,
                "status": "ready" if ready else "blocked",
                "reason": None if ready else "assistant_prompt_assembly_gateway_blocked",
            }
        ],
    }


def build_assistant_prompt_assembly_health(db: Session) -> dict[str, Any]:
    return AssistantPromptAssemblyHealthResult().as_dict()
