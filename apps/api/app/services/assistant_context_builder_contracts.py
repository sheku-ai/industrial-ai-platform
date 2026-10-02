"""Assistant Context Builder contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class AssistantContextBuilderRequest:
    search_execution_id: str
    assistant_id: str
    assistant_session_id: str | None
    result_count: int
    package_metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "assistant_context_builder_request_schema_version": "1",
            "search_execution_id": self.search_execution_id,
            "assistant_id": self.assistant_id,
            "assistant_session_id": self.assistant_session_id,
            "result_count": self.result_count,
            "package_metadata": dict(self.package_metadata),
        }


@dataclass(frozen=True)
class AssistantContextBuilderSessionDescriptor:
    context_builder_session_id: str | None
    request: AssistantContextBuilderRequest
    context_builder_state: str
    blocking_issues: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    next_available_actions: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        ready = self.context_builder_state == "ready"
        return {
            "assistant_context_builder_session_schema_version": "1",
            "context_builder_session_id": self.context_builder_session_id,
            "assistant_context_builder_session_ready": ready,
            "context_builder_state": self.context_builder_state,
            "request": self.request.as_dict(),
            "search_execution_id": self.request.search_execution_id,
            "assistant_id": self.request.assistant_id,
            "assistant_session_id": self.request.assistant_session_id,
            "assistant_context_builder_prepared": ready,
            "search_execution_completed": ready,
            "ordered_context_created": ready,
            "ordered_citations_created": ready,
            "token_estimation_completed": ready,
            "llm_used": False,
            "answer_generated": False,
            "workflow_executed": False,
            "tool_called": False,
            "external_action_called": False,
            "autonomous_execution": False,
            "postgresql_source_of_truth": True,
            "blocking_issues": list(self.blocking_issues),
            "warnings": list(self.warnings),
            "next_available_actions": list(self.next_available_actions),
        }


@dataclass(frozen=True)
class AssistantContextBuilderHealthResult:
    assistant_context_builder_available: bool = True
    assistant_context_builder_status: str = "metadata_only"
    prompt_generated: bool = False
    llm_used: bool = False
    answer_generated: bool = False
    workflow_executed: bool = False
    tool_called: bool = False
    external_action_called: bool = False
    autonomous_execution: bool = False
    postgresql_source_of_truth: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "assistant_context_builder_health_schema_version": "1",
            "assistant_context_builder_available": self.assistant_context_builder_available,
            "assistant_context_builder_status": self.assistant_context_builder_status,
            "prompt_generated": self.prompt_generated,
            "llm_used": self.llm_used,
            "answer_generated": self.answer_generated,
            "workflow_executed": self.workflow_executed,
            "tool_called": self.tool_called,
            "external_action_called": self.external_action_called,
            "autonomous_execution": self.autonomous_execution,
            "postgresql_source_of_truth": self.postgresql_source_of_truth,
        }
