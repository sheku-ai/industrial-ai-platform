"""Assistant LLM Execution contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

LOCAL_MOCK_PROVIDER_TYPE = "local_mock"
LOCAL_MOCK_PROVIDER_NAME = "deterministic-local-mock"
LOCAL_MOCK_MODEL_NAME = "deterministic-assistant-runtime-mock"
LOCAL_MOCK_CALL_MODE = "deterministic_local_mock"


@dataclass(frozen=True)
class AssistantLlmExecutionRequest:
    gateway_id: str
    prompt_package_id: str
    assistant_id: str
    assistant_session_id: str | None
    provider_type: str
    provider_name: str
    model_name: str
    execution_allowed: bool
    llm_ready: bool
    request_payload_metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "assistant_llm_execution_request_schema_version": "1",
            "gateway_id": self.gateway_id,
            "prompt_package_id": self.prompt_package_id,
            "assistant_id": self.assistant_id,
            "assistant_session_id": self.assistant_session_id,
            "provider_type": self.provider_type,
            "provider_name": self.provider_name,
            "model_name": self.model_name,
            "execution_allowed": self.execution_allowed,
            "llm_ready": self.llm_ready,
            "request_payload_metadata": dict(self.request_payload_metadata),
        }


@dataclass(frozen=True)
class AssistantLlmExecutionSessionDescriptor:
    llm_execution_session_id: str | None
    request: AssistantLlmExecutionRequest
    execution_state: str
    provider_call_mode: str
    blocking_issues: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    next_available_actions: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        ready = self.execution_state == "ready"
        return {
            "assistant_llm_execution_session_schema_version": "1",
            "llm_execution_session_id": self.llm_execution_session_id,
            "assistant_llm_execution_session_ready": ready,
            "execution_state": self.execution_state,
            "provider_call_mode": self.provider_call_mode,
            "request": self.request.as_dict(),
            "gateway_id": self.request.gateway_id,
            "prompt_package_id": self.request.prompt_package_id,
            "assistant_id": self.request.assistant_id,
            "assistant_session_id": self.request.assistant_session_id,
            "provider_type": self.request.provider_type,
            "provider_name": self.request.provider_name,
            "model_name": self.request.model_name,
            "assistant_llm_execution_prepared": ready,
            "llm_gateway_created": ready,
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
            "blocking_issues": list(self.blocking_issues),
            "warnings": list(self.warnings),
            "next_available_actions": list(self.next_available_actions),
        }


@dataclass(frozen=True)
class AssistantLlmExecutionHealthResult:
    assistant_llm_execution_available: bool = True
    assistant_llm_execution_status: str = "local_mock_execution_only"
    provider_type: str = LOCAL_MOCK_PROVIDER_TYPE
    provider_name: str = LOCAL_MOCK_PROVIDER_NAME
    model_name: str = LOCAL_MOCK_MODEL_NAME
    provider_call_mode: str = LOCAL_MOCK_CALL_MODE
    external_providers_enabled: bool = False
    citation_verification_completed: bool = False
    final_response_created: bool = False
    tool_called: bool = False
    workflow_executed: bool = False
    external_action_called: bool = False
    autonomous_execution: bool = False
    postgresql_source_of_truth: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "assistant_llm_execution_health_schema_version": "1",
            "assistant_llm_execution_available": self.assistant_llm_execution_available,
            "assistant_llm_execution_status": self.assistant_llm_execution_status,
            "provider_type": self.provider_type,
            "provider_name": self.provider_name,
            "model_name": self.model_name,
            "provider_call_mode": self.provider_call_mode,
            "external_providers_enabled": self.external_providers_enabled,
            "citation_verification_completed": self.citation_verification_completed,
            "final_response_created": self.final_response_created,
            "tool_called": self.tool_called,
            "workflow_executed": self.workflow_executed,
            "external_action_called": self.external_action_called,
            "autonomous_execution": self.autonomous_execution,
            "postgresql_source_of_truth": self.postgresql_source_of_truth,
        }
