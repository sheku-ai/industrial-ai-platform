"""Metadata-only Assistant Runtime contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class AssistantDefinitionRequest:
    assistant_key: str
    assistant_name: str
    assistant_version: str = "1.0"
    assistant_type: str = "platform_assistant"
    description: str | None = None
    default_search_mode: str = "enterprise_search"
    allowed_runtime_domains: list[str] = field(default_factory=list)
    guardrail_profile: dict[str, Any] = field(default_factory=dict)
    requested_by: str | None = None
    conversation_reference: str | None = None
    requested_query: str | None = None
    runtime_context: dict[str, Any] = field(default_factory=dict)
    runtime_metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "assistant_definition_request_schema_version": "1",
            "assistant_key": self.assistant_key,
            "assistant_name": self.assistant_name,
            "assistant_version": self.assistant_version,
            "assistant_type": self.assistant_type,
            "description": self.description,
            "default_search_mode": self.default_search_mode,
            "allowed_runtime_domains": list(self.allowed_runtime_domains),
            "guardrail_profile": dict(self.guardrail_profile),
            "requested_by": self.requested_by,
            "conversation_reference": self.conversation_reference,
            "requested_query": self.requested_query,
            "runtime_context": dict(self.runtime_context),
            "runtime_metadata": dict(self.runtime_metadata),
        }


@dataclass(frozen=True)
class AssistantSessionDescriptor:
    assistant_session_id: str | None
    request: AssistantDefinitionRequest
    assistant_state: str
    selected_search_mode: str
    selected_runtime_domain: str
    runtime_metadata: dict[str, Any] = field(default_factory=dict)
    blocking_issues: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    next_available_actions: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        ready = self.assistant_state == "ready"
        return {
            "assistant_session_descriptor_schema_version": "1",
            "assistant_session_id": self.assistant_session_id,
            "assistant_session_ready": ready,
            "assistant_state": self.assistant_state,
            "request": self.request.as_dict(),
            "assistant_key": self.request.assistant_key,
            "assistant_name": self.request.assistant_name,
            "assistant_version": self.request.assistant_version,
            "assistant_type": self.request.assistant_type,
            "selected_search_mode": self.selected_search_mode,
            "selected_runtime_domain": self.selected_runtime_domain,
            "runtime_metadata": dict(self.runtime_metadata),
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
            "blocking_issues": list(self.blocking_issues),
            "warnings": list(self.warnings),
            "next_available_actions": list(self.next_available_actions),
        }


@dataclass(frozen=True)
class AssistantRuntimePlan:
    session: AssistantSessionDescriptor
    assistant_id: str | None
    assistant_session_id: str | None
    assistant_run_id: str | None
    execution_allowed: bool = False
    descriptor_only: bool = True
    assistant_execution_planned: bool = True
    assistant_executed: bool = False
    llm_used: bool = False
    answer_generated: bool = False
    tool_called: bool = False
    workflow_executed: bool = False
    external_action_called: bool = False
    autonomous_execution: bool = False
    enterprise_search_used: bool = False
    hybrid_search_used: bool = False
    postgresql_source_of_truth: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "assistant_runtime_plan_schema_version": "1",
            "session": self.session.as_dict(),
            "assistant_id": self.assistant_id,
            "assistant_session_id": self.assistant_session_id,
            "assistant_run_id": self.assistant_run_id,
            "execution_allowed": self.execution_allowed,
            "descriptor_only": self.descriptor_only,
            "assistant_execution_planned": self.assistant_execution_planned,
            "assistant_executed": self.assistant_executed,
            "llm_used": self.llm_used,
            "answer_generated": self.answer_generated,
            "tool_called": self.tool_called,
            "workflow_executed": self.workflow_executed,
            "external_action_called": self.external_action_called,
            "autonomous_execution": self.autonomous_execution,
            "enterprise_search_used": self.enterprise_search_used,
            "hybrid_search_used": self.hybrid_search_used,
            "postgresql_source_of_truth": self.postgresql_source_of_truth,
        }


@dataclass(frozen=True)
class AssistantRuntimeResult:
    runtime_plan: AssistantRuntimePlan
    assistant_status: str
    session_status: str
    run_status: str
    assistant_definition_created: bool
    assistant_session_created: bool
    assistant_run_created: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "assistant_runtime_result_schema_version": "1",
            "assistant_status": self.assistant_status,
            "session_status": self.session_status,
            "run_status": self.run_status,
            "assistant_definition_created": self.assistant_definition_created,
            "assistant_session_created": self.assistant_session_created,
            "assistant_run_created": self.assistant_run_created,
            "assistant_execution_planned": True,
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
            "runtime_plan": self.runtime_plan.as_dict(),
        }


@dataclass(frozen=True)
class AssistantHealthResult:
    assistant_runtime_available: bool = True
    assistant_runtime_status: str = "metadata_only"
    assistant_executed: bool = False
    llm_used: bool = False
    answer_generated: bool = False
    tool_called: bool = False
    workflow_executed: bool = False
    external_action_called: bool = False
    autonomous_execution: bool = False
    postgresql_source_of_truth: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "assistant_health_schema_version": "1",
            "assistant_runtime_available": self.assistant_runtime_available,
            "assistant_runtime_status": self.assistant_runtime_status,
            "assistant_executed": self.assistant_executed,
            "llm_used": self.llm_used,
            "answer_generated": self.answer_generated,
            "tool_called": self.tool_called,
            "workflow_executed": self.workflow_executed,
            "external_action_called": self.external_action_called,
            "autonomous_execution": self.autonomous_execution,
            "postgresql_source_of_truth": self.postgresql_source_of_truth,
        }
