"""Assistant LLM Execution session foundation."""

from __future__ import annotations

import hashlib
from typing import Any

from app.services.assistant_llm_execution_contracts import (
    LOCAL_MOCK_CALL_MODE,
    LOCAL_MOCK_MODEL_NAME,
    LOCAL_MOCK_PROVIDER_NAME,
    LOCAL_MOCK_PROVIDER_TYPE,
    AssistantLlmExecutionRequest,
    AssistantLlmExecutionSessionDescriptor,
)
from app.services.enterprise_search_session import issue, sort_issues

ASSISTANT_LLM_EXECUTION_STATE_BLOCKED = "blocked"
ASSISTANT_LLM_EXECUTION_STATE_READY = "ready"


def _stable_llm_execution_session_id(*, gateway_id: str, provider_name: str, model_name: str) -> str | None:
    if not gateway_id:
        return None
    digest = hashlib.sha256(f"{gateway_id}|{provider_name}|{model_name}|assistant-llm-execution".encode()).hexdigest()[
        :24
    ]
    return f"assistant-llm-execution-session:{digest}"


def build_assistant_llm_execution_request(
    *,
    gateway_id: str,
    prompt_package_id: str,
    assistant_id: str,
    assistant_session_id: str | None,
    provider_type: str = LOCAL_MOCK_PROVIDER_TYPE,
    provider_name: str = LOCAL_MOCK_PROVIDER_NAME,
    model_name: str = LOCAL_MOCK_MODEL_NAME,
    execution_allowed: bool = False,
    llm_ready: bool = False,
    request_payload_metadata: dict[str, Any] | None = None,
) -> AssistantLlmExecutionRequest:
    return AssistantLlmExecutionRequest(
        gateway_id=str(gateway_id),
        prompt_package_id=str(prompt_package_id),
        assistant_id=str(assistant_id),
        assistant_session_id=str(assistant_session_id) if assistant_session_id else None,
        provider_type=str(provider_type or LOCAL_MOCK_PROVIDER_TYPE),
        provider_name=str(provider_name or LOCAL_MOCK_PROVIDER_NAME),
        model_name=str(model_name or LOCAL_MOCK_MODEL_NAME),
        execution_allowed=bool(execution_allowed),
        llm_ready=bool(llm_ready),
        request_payload_metadata=dict(request_payload_metadata or {}),
    )


def build_assistant_llm_execution_session(
    request: AssistantLlmExecutionRequest,
) -> AssistantLlmExecutionSessionDescriptor:
    blocking_issues: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    if not request.gateway_id.strip():
        blocking_issues.append(
            issue(
                "gateway_id_missing",
                "Assistant LLM execution requires a gateway_id.",
                component="assistant_llm_execution_session",
            )
        )
    if not request.prompt_package_id.strip():
        blocking_issues.append(
            issue(
                "prompt_package_id_missing",
                "Assistant LLM execution requires a prompt_package_id.",
                component="assistant_llm_execution_session",
            )
        )
    if not request.assistant_id.strip():
        blocking_issues.append(
            issue(
                "assistant_id_missing",
                "Assistant LLM execution requires an assistant_id.",
                component="assistant_llm_execution_session",
            )
        )
    if not request.llm_ready:
        blocking_issues.append(
            issue(
                "prompt_package_not_llm_ready",
                "Assistant LLM execution requires an LLM-ready prompt package.",
                component="assistant_llm_execution_session",
            )
        )
    local_mock = request.provider_type == LOCAL_MOCK_PROVIDER_TYPE
    if not local_mock:
        blocking_issues.append(
            issue(
                "provider_not_enabled",
                "Assistant LLM execution only supports the local mock provider in this sprint.",
                component="assistant_llm_execution_session",
                item_id=request.provider_type,
            )
        )
    if not request.execution_allowed and not local_mock:
        blocking_issues.append(
            issue(
                "execution_not_allowed",
                "Assistant LLM execution requires execution_allowed or local_mock provider mode.",
                component="assistant_llm_execution_session",
            )
        )
    ready = not blocking_issues
    return AssistantLlmExecutionSessionDescriptor(
        llm_execution_session_id=_stable_llm_execution_session_id(
            gateway_id=request.gateway_id, provider_name=request.provider_name, model_name=request.model_name
        ),
        request=request,
        execution_state=ASSISTANT_LLM_EXECUTION_STATE_READY if ready else ASSISTANT_LLM_EXECUTION_STATE_BLOCKED,
        provider_call_mode=LOCAL_MOCK_CALL_MODE,
        blocking_issues=sort_issues(blocking_issues),
        warnings=sort_issues(warnings),
        next_available_actions=[
            {
                "action": "execute_assistant_llm_local_mock",
                "available": ready,
                "status": "ready" if ready else "blocked",
                "reason": None if ready else "assistant_llm_execution_session_blocked",
            }
        ],
    )


def serialize_assistant_llm_execution_session(session: AssistantLlmExecutionSessionDescriptor) -> dict[str, Any]:
    return session.as_dict()
