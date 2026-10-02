"""Assistant Prompt Assembly contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class AssistantPromptAssemblyRequest:
    context_package_id: str
    assistant_id: str
    assistant_session_id: str | None
    chunk_count: int
    citation_count: int
    prompt_metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "assistant_prompt_assembly_request_schema_version": "1",
            "context_package_id": self.context_package_id,
            "assistant_id": self.assistant_id,
            "assistant_session_id": self.assistant_session_id,
            "chunk_count": self.chunk_count,
            "citation_count": self.citation_count,
            "prompt_metadata": dict(self.prompt_metadata),
        }


@dataclass(frozen=True)
class AssistantPromptAssemblySessionDescriptor:
    prompt_assembly_session_id: str | None
    request: AssistantPromptAssemblyRequest
    prompt_assembly_state: str
    blocking_issues: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    next_available_actions: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        ready = self.prompt_assembly_state == "ready"
        return {
            "assistant_prompt_assembly_session_schema_version": "1",
            "prompt_assembly_session_id": self.prompt_assembly_session_id,
            "assistant_prompt_assembly_session_ready": ready,
            "prompt_assembly_state": self.prompt_assembly_state,
            "request": self.request.as_dict(),
            "context_package_id": self.request.context_package_id,
            "assistant_id": self.request.assistant_id,
            "assistant_session_id": self.request.assistant_session_id,
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
            "blocking_issues": list(self.blocking_issues),
            "warnings": list(self.warnings),
            "next_available_actions": list(self.next_available_actions),
        }


@dataclass(frozen=True)
class AssistantPromptAssemblyHealthResult:
    assistant_prompt_assembly_available: bool = True
    assistant_prompt_assembly_status: str = "prompt_ready_no_inference"
    llm_ready: bool = True
    llm_invoked: bool = False
    answer_generated: bool = False
    tool_called: bool = False
    workflow_executed: bool = False
    external_action_called: bool = False
    autonomous_execution: bool = False
    postgresql_source_of_truth: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "assistant_prompt_assembly_health_schema_version": "1",
            "assistant_prompt_assembly_available": self.assistant_prompt_assembly_available,
            "assistant_prompt_assembly_status": self.assistant_prompt_assembly_status,
            "llm_ready": self.llm_ready,
            "llm_invoked": self.llm_invoked,
            "answer_generated": self.answer_generated,
            "tool_called": self.tool_called,
            "workflow_executed": self.workflow_executed,
            "external_action_called": self.external_action_called,
            "autonomous_execution": self.autonomous_execution,
            "postgresql_source_of_truth": self.postgresql_source_of_truth,
        }
