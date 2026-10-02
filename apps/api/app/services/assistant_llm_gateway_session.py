"""Assistant LLM Gateway session foundation."""

from __future__ import annotations

import hashlib
from typing import Any

from app.services.assistant_llm_gateway_contracts import (
    AssistantLlmGatewayRequest,
    AssistantLlmGatewaySessionDescriptor,
)
from app.services.enterprise_search_session import issue, sort_issues

ASSISTANT_LLM_GATEWAY_STATE_BLOCKED = "blocked"
ASSISTANT_LLM_GATEWAY_STATE_READY = "ready"
ASSISTANT_LLM_GATEWAY_BLOCKED_REASON = "execution_disabled"


def _stable_llm_gateway_session_id(*, prompt_package_id: str, provider_name: str, model_name: str) -> str | None:
    if not prompt_package_id:
        return None
    digest = hashlib.sha256(
        f"{prompt_package_id}|{provider_name}|{model_name}|assistant-llm-gateway".encode()
    ).hexdigest()[:24]
    return f"assistant-llm-gateway-session:{digest}"


def build_assistant_llm_gateway_request(
    *,
    prompt_package_id: str,
    assistant_id: str,
    assistant_session_id: str | None,
    llm_ready: bool,
    llm_invoked: bool,
    answer_generated: bool,
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
) -> AssistantLlmGatewayRequest:
    return AssistantLlmGatewayRequest(
        prompt_package_id=str(prompt_package_id),
        assistant_id=str(assistant_id),
        assistant_session_id=str(assistant_session_id) if assistant_session_id else None,
        llm_ready=bool(llm_ready),
        llm_invoked=bool(llm_invoked),
        answer_generated=bool(answer_generated),
        provider_type=str(provider_type or "reference"),
        provider_name=str(provider_name or "metadata-only"),
        model_name=str(model_name or "metadata-only"),
        planned_temperature=max(0.0, float(planned_temperature or 0.0)),
        planned_max_tokens=max(1, int(planned_max_tokens or 1)),
        planned_top_p=max(0.0, min(1.0, float(planned_top_p if planned_top_p is not None else 1.0))),
        planned_stop_sequences=list(planned_stop_sequences or []),
        planned_seed=planned_seed,
        planned_timeout=max(1, int(planned_timeout or 1)),
        gateway_metadata=dict(gateway_metadata or {}),
    )


def build_assistant_llm_gateway_session(request: AssistantLlmGatewayRequest) -> AssistantLlmGatewaySessionDescriptor:
    blocking_issues: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    if not request.prompt_package_id.strip():
        blocking_issues.append(
            issue(
                "prompt_package_id_missing",
                "Assistant LLM gateway requires a prompt_package_id.",
                component="assistant_llm_gateway_session",
            )
        )
    if not request.assistant_id.strip():
        blocking_issues.append(
            issue(
                "assistant_id_missing",
                "Assistant LLM gateway requires an assistant_id.",
                component="assistant_llm_gateway_session",
            )
        )
    if not request.llm_ready:
        blocking_issues.append(
            issue(
                "prompt_package_not_llm_ready",
                "Assistant LLM gateway requires a prompt package marked llm_ready.",
                component="assistant_llm_gateway_session",
            )
        )
    if request.llm_invoked:
        blocking_issues.append(
            issue(
                "prompt_package_already_invoked",
                "Assistant LLM gateway cannot plan from a prompt package that already invoked an LLM.",
                component="assistant_llm_gateway_session",
            )
        )
    if request.answer_generated:
        blocking_issues.append(
            issue(
                "prompt_package_answer_generated",
                "Assistant LLM gateway cannot plan from a prompt package that already generated an answer.",
                component="assistant_llm_gateway_session",
            )
        )
    if not request.provider_type.strip():
        blocking_issues.append(
            issue(
                "provider_type_missing",
                "Assistant LLM gateway requires a provider_type.",
                component="assistant_llm_gateway_session",
            )
        )
    if not request.provider_name.strip():
        blocking_issues.append(
            issue(
                "provider_name_missing",
                "Assistant LLM gateway requires a provider_name.",
                component="assistant_llm_gateway_session",
            )
        )
    if not request.model_name.strip():
        blocking_issues.append(
            issue(
                "model_name_missing",
                "Assistant LLM gateway requires a model_name.",
                component="assistant_llm_gateway_session",
            )
        )
    if request.planned_max_tokens <= 0:
        blocking_issues.append(
            issue(
                "planned_max_tokens_invalid",
                "Assistant LLM gateway requires planned_max_tokens greater than zero.",
                component="assistant_llm_gateway_session",
            )
        )
    if request.planned_top_p < 0 or request.planned_top_p > 1:
        blocking_issues.append(
            issue(
                "planned_top_p_invalid",
                "Assistant LLM gateway requires planned_top_p between 0 and 1.",
                component="assistant_llm_gateway_session",
            )
        )
    if request.planned_timeout <= 0:
        blocking_issues.append(
            issue(
                "planned_timeout_invalid",
                "Assistant LLM gateway requires planned_timeout greater than zero.",
                component="assistant_llm_gateway_session",
            )
        )
    ready = not blocking_issues
    return AssistantLlmGatewaySessionDescriptor(
        llm_gateway_session_id=_stable_llm_gateway_session_id(
            prompt_package_id=request.prompt_package_id,
            provider_name=request.provider_name,
            model_name=request.model_name,
        ),
        request=request,
        gateway_state=ASSISTANT_LLM_GATEWAY_STATE_READY if ready else ASSISTANT_LLM_GATEWAY_STATE_BLOCKED,
        provider_ready=True,
        execution_allowed=False,
        blocked_reason=ASSISTANT_LLM_GATEWAY_BLOCKED_REASON,
        blocking_issues=sort_issues(blocking_issues),
        warnings=sort_issues(warnings),
        next_available_actions=[
            {
                "action": "create_llm_invocation_plan",
                "available": ready,
                "status": "ready" if ready else "blocked",
                "reason": None if ready else "assistant_llm_gateway_session_blocked",
            }
        ],
    )


def serialize_assistant_llm_gateway_session(session: AssistantLlmGatewaySessionDescriptor) -> dict[str, Any]:
    return session.as_dict()
