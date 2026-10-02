"""Assistant LLM Gateway validation gateway."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.repositories.assistant import AssistantRepository
from app.services.assistant_llm_gateway_contracts import AssistantLlmGatewayHealthResult
from app.services.assistant_llm_gateway_session import (
    build_assistant_llm_gateway_request,
    build_assistant_llm_gateway_session,
    serialize_assistant_llm_gateway_session,
)
from app.services.enterprise_search_session import issue, sort_issues


def build_assistant_llm_gateway(
    db: Session,
    *,
    prompt_package_id: str,
    provider_type: str = "reference",
    provider_name: str = "metadata-only",
    model_name: str = "metadata-only",
    planned_temperature: float = 0.0,
    planned_max_tokens: int = 1024,
    planned_top_p: float = 1.0,
    planned_stop_sequences: list[str] | None = None,
    planned_seed: int | None = None,
    planned_timeout: int = 30,
    gateway_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    blocking_issues: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    repository = AssistantRepository(db)
    prompt_package = None
    try:
        prompt_package_uuid = uuid.UUID(str(prompt_package_id))
    except (TypeError, ValueError):
        blocking_issues.append(
            issue(
                "prompt_package_id_invalid",
                "Assistant LLM gateway requires a valid prompt_package_id.",
                component="assistant_llm_gateway",
                item_id=str(prompt_package_id),
            )
        )
    else:
        prompt_package = repository.get_prompt_package(prompt_package_uuid)
        if prompt_package is None:
            blocking_issues.append(
                issue(
                    "prompt_package_not_found",
                    "Assistant LLM gateway requires an existing prompt package.",
                    component="assistant_llm_gateway",
                    item_id=str(prompt_package_uuid),
                )
            )
    request = build_assistant_llm_gateway_request(
        prompt_package_id=str(prompt_package_id),
        assistant_id=str(prompt_package.assistant_id) if prompt_package is not None else "",
        assistant_session_id=str(prompt_package.assistant_session_id)
        if prompt_package is not None and prompt_package.assistant_session_id
        else None,
        llm_ready=bool(prompt_package.llm_ready) if prompt_package is not None else False,
        llm_invoked=bool(prompt_package.llm_invoked) if prompt_package is not None else False,
        answer_generated=bool(prompt_package.answer_generated) if prompt_package is not None else False,
        provider_type=provider_type,
        provider_name=provider_name,
        model_name=model_name,
        planned_temperature=planned_temperature,
        planned_max_tokens=planned_max_tokens,
        planned_top_p=planned_top_p,
        planned_stop_sequences=planned_stop_sequences,
        planned_seed=planned_seed,
        planned_timeout=planned_timeout,
        gateway_metadata=gateway_metadata,
    )
    session = serialize_assistant_llm_gateway_session(build_assistant_llm_gateway_session(request))
    blocking_issues.extend(session.get("blocking_issues") or [])
    warnings.extend(session.get("warnings") or [])
    if prompt_package is not None and prompt_package.package_status not in {"created", "prepared"}:
        blocking_issues.append(
            issue(
                "prompt_package_status_not_ready",
                "Assistant LLM gateway requires a created prompt package.",
                component="assistant_llm_gateway",
                item_id=prompt_package.package_status,
            )
        )
    ready = bool(session.get("assistant_llm_gateway_session_ready")) and not blocking_issues
    return {
        "assistant_llm_gateway_schema_version": "1",
        "assistant_llm_gateway_ready": ready,
        "gateway_status": "ready" if ready else "blocked",
        "assistant_llm_gateway_session": session,
        "prompt_package_id": str(prompt_package.prompt_package_id)
        if prompt_package is not None
        else str(prompt_package_id),
        "assistant_id": str(prompt_package.assistant_id) if prompt_package is not None else None,
        "assistant_session_id": str(prompt_package.assistant_session_id)
        if prompt_package is not None and prompt_package.assistant_session_id
        else None,
        "provider_type": request.provider_type,
        "provider_name": request.provider_name,
        "model_name": request.model_name,
        "provider_ready": True,
        "execution_allowed": False,
        "blocked_reason": "execution_disabled",
        "assistant_llm_gateway_prepared": ready,
        "prompt_package_created": prompt_package is not None,
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
                "action": "create_llm_invocation_plan",
                "available": ready,
                "status": "ready" if ready else "blocked",
                "reason": None if ready else "assistant_llm_gateway_blocked",
            }
        ],
    }


def build_assistant_llm_gateway_health(db: Session) -> dict[str, Any]:
    return AssistantLlmGatewayHealthResult().as_dict()
