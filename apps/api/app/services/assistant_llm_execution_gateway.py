"""Assistant LLM Execution validation gateway."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.repositories.assistant import AssistantRepository
from app.services.assistant_llm_execution_contracts import (
    LOCAL_MOCK_MODEL_NAME,
    LOCAL_MOCK_PROVIDER_NAME,
    LOCAL_MOCK_PROVIDER_TYPE,
    AssistantLlmExecutionHealthResult,
)
from app.services.assistant_llm_execution_session import (
    build_assistant_llm_execution_request,
    build_assistant_llm_execution_session,
    serialize_assistant_llm_execution_session,
)
from app.services.enterprise_search_session import issue, sort_issues


def build_assistant_llm_execution_gateway(
    db: Session,
    *,
    gateway_id: str,
    request_payload_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    blocking_issues: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    repository = AssistantRepository(db)
    llm_plan = None
    prompt_package = None
    try:
        gateway_uuid = uuid.UUID(str(gateway_id))
    except (TypeError, ValueError):
        blocking_issues.append(
            issue(
                "gateway_id_invalid",
                "Assistant LLM execution requires a valid gateway_id.",
                component="assistant_llm_execution_gateway",
                item_id=str(gateway_id),
            )
        )
    else:
        llm_plan = repository.get_llm_invocation_plan(gateway_uuid)
        if llm_plan is None:
            blocking_issues.append(
                issue(
                    "llm_gateway_not_found",
                    "Assistant LLM execution requires an existing LLM gateway plan.",
                    component="assistant_llm_execution_gateway",
                    item_id=str(gateway_uuid),
                )
            )
        else:
            prompt_package = repository.get_prompt_package(llm_plan.prompt_package_id)
            if prompt_package is None:
                blocking_issues.append(
                    issue(
                        "prompt_package_not_found",
                        "Assistant LLM execution requires an existing prompt package.",
                        component="assistant_llm_execution_gateway",
                        item_id=str(llm_plan.prompt_package_id),
                    )
                )
    provider_type = LOCAL_MOCK_PROVIDER_TYPE
    provider_name = LOCAL_MOCK_PROVIDER_NAME
    model_name = LOCAL_MOCK_MODEL_NAME
    execution_allowed = True
    request = build_assistant_llm_execution_request(
        gateway_id=str(gateway_id),
        prompt_package_id=str(llm_plan.prompt_package_id) if llm_plan is not None else "",
        assistant_id=str(llm_plan.assistant_id) if llm_plan is not None else "",
        assistant_session_id=str(llm_plan.assistant_session_id)
        if llm_plan is not None and llm_plan.assistant_session_id
        else None,
        provider_type=provider_type,
        provider_name=provider_name,
        model_name=model_name,
        execution_allowed=execution_allowed,
        llm_ready=bool(prompt_package.llm_ready) if prompt_package is not None else False,
        request_payload_metadata=request_payload_metadata,
    )
    session = serialize_assistant_llm_execution_session(build_assistant_llm_execution_session(request))
    blocking_issues.extend(session.get("blocking_issues") or [])
    warnings.extend(session.get("warnings") or [])
    if prompt_package is not None and prompt_package.package_status not in {"created", "prepared"}:
        blocking_issues.append(
            issue(
                "prompt_package_status_not_ready",
                "Assistant LLM execution requires a created prompt package.",
                component="assistant_llm_execution_gateway",
                item_id=prompt_package.package_status,
            )
        )
    if prompt_package is not None and bool(prompt_package.answer_generated):
        blocking_issues.append(
            issue(
                "prompt_package_answer_generated",
                "Assistant LLM execution cannot use a prompt package that already generated an answer.",
                component="assistant_llm_execution_gateway",
                item_id=str(prompt_package.prompt_package_id),
            )
        )
    ready = bool(session.get("assistant_llm_execution_session_ready")) and not blocking_issues
    return {
        "assistant_llm_execution_gateway_schema_version": "1",
        "assistant_llm_execution_gateway_ready": ready,
        "gateway_status": "ready" if ready else "blocked",
        "assistant_llm_execution_session": session,
        "gateway_id": str(llm_plan.gateway_id) if llm_plan is not None else str(gateway_id),
        "prompt_package_id": str(llm_plan.prompt_package_id) if llm_plan is not None else None,
        "assistant_id": str(llm_plan.assistant_id) if llm_plan is not None else None,
        "assistant_session_id": str(llm_plan.assistant_session_id)
        if llm_plan is not None and llm_plan.assistant_session_id
        else None,
        "provider_type": provider_type,
        "provider_name": provider_name,
        "model_name": model_name,
        "execution_allowed": execution_allowed,
        "provider_call_mode": session.get("provider_call_mode"),
        "assistant_llm_execution_prepared": ready,
        "llm_gateway_created": llm_plan is not None,
        "llm_execution_created": False,
        "provider_called": False,
        "raw_output_created": False,
        "raw_output_persisted": False,
        "citation_verification_completed": False,
        "final_response_created": False,
        "tool_called": False,
        "workflow_executed": False,
        "external_action_called": False,
        "autonomous_execution": False,
        "postgresql_source_of_truth": True,
        "blocking_issues": sort_issues(blocking_issues),
        "warnings": sort_issues(warnings),
        "next_available_actions": [
            {
                "action": "execute_assistant_llm_local_mock",
                "available": ready,
                "status": "ready" if ready else "blocked",
                "reason": None if ready else "assistant_llm_execution_gateway_blocked",
            }
        ],
    }


def build_assistant_llm_execution_health(db: Session) -> dict[str, Any]:
    return AssistantLlmExecutionHealthResult().as_dict()
