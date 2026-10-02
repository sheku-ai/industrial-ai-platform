"""Assistant LLM Gateway contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class AssistantLlmGatewayRequest:
    prompt_package_id: str
    assistant_id: str
    assistant_session_id: str | None
    llm_ready: bool
    llm_invoked: bool
    answer_generated: bool
    provider_type: str
    provider_name: str
    model_name: str
    planned_temperature: float
    planned_max_tokens: int
    planned_top_p: float
    planned_stop_sequences: list[str] = field(default_factory=list)
    planned_seed: int | None = None
    planned_timeout: int = 30
    gateway_metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "assistant_llm_gateway_request_schema_version": "1",
            "prompt_package_id": self.prompt_package_id,
            "assistant_id": self.assistant_id,
            "assistant_session_id": self.assistant_session_id,
            "llm_ready": self.llm_ready,
            "llm_invoked": self.llm_invoked,
            "answer_generated": self.answer_generated,
            "provider_type": self.provider_type,
            "provider_name": self.provider_name,
            "model_name": self.model_name,
            "planned_temperature": self.planned_temperature,
            "planned_max_tokens": self.planned_max_tokens,
            "planned_top_p": self.planned_top_p,
            "planned_stop_sequences": list(self.planned_stop_sequences),
            "planned_seed": self.planned_seed,
            "planned_timeout": self.planned_timeout,
            "gateway_metadata": dict(self.gateway_metadata),
        }


@dataclass(frozen=True)
class AssistantLlmGatewaySessionDescriptor:
    llm_gateway_session_id: str | None
    request: AssistantLlmGatewayRequest
    gateway_state: str
    provider_ready: bool
    execution_allowed: bool
    blocked_reason: str
    blocking_issues: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    next_available_actions: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        ready = self.gateway_state == "ready"
        return {
            "assistant_llm_gateway_session_schema_version": "1",
            "llm_gateway_session_id": self.llm_gateway_session_id,
            "assistant_llm_gateway_session_ready": ready,
            "gateway_state": self.gateway_state,
            "request": self.request.as_dict(),
            "prompt_package_id": self.request.prompt_package_id,
            "assistant_id": self.request.assistant_id,
            "assistant_session_id": self.request.assistant_session_id,
            "provider_type": self.request.provider_type,
            "provider_name": self.request.provider_name,
            "model_name": self.request.model_name,
            "provider_ready": self.provider_ready,
            "execution_allowed": self.execution_allowed,
            "blocked_reason": self.blocked_reason,
            "assistant_llm_gateway_prepared": ready,
            "prompt_package_created": ready,
            "llm_invoked": False,
            "answer_generated": False,
            "tool_called": False,
            "workflow_executed": False,
            "external_action_called": False,
            "autonomous_execution": False,
            "postgresql_source_of_truth": True,
            "blocking_issues": list(self.blocking_issues),
            "warnings": list(self.warnings),
            "next_available_actions": list(self.next_available_actions),
        }


@dataclass(frozen=True)
class AssistantLlmGatewayHealthResult:
    assistant_llm_gateway_available: bool = True
    assistant_llm_gateway_status: str = "planning_only_no_inference"
    provider_ready: bool = True
    execution_allowed: bool = False
    blocked_reason: str = "execution_disabled"
    llm_invoked: bool = False
    answer_generated: bool = False
    tool_called: bool = False
    workflow_executed: bool = False
    external_action_called: bool = False
    autonomous_execution: bool = False
    postgresql_source_of_truth: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "assistant_llm_gateway_health_schema_version": "1",
            "assistant_llm_gateway_available": self.assistant_llm_gateway_available,
            "assistant_llm_gateway_status": self.assistant_llm_gateway_status,
            "provider_ready": self.provider_ready,
            "execution_allowed": self.execution_allowed,
            "blocked_reason": self.blocked_reason,
            "llm_invoked": self.llm_invoked,
            "answer_generated": self.answer_generated,
            "tool_called": self.tool_called,
            "workflow_executed": self.workflow_executed,
            "external_action_called": self.external_action_called,
            "autonomous_execution": self.autonomous_execution,
            "postgresql_source_of_truth": self.postgresql_source_of_truth,
        }
