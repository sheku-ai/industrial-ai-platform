"""Assistant Citation Verification contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class AssistantCitationVerificationRequest:
    llm_execution_id: str
    prompt_package_id: str
    context_package_id: str
    assistant_runtime_id: str | None
    raw_output_available: bool
    context_citation_count: int
    request_metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "assistant_citation_verification_request_schema_version": "1",
            "llm_execution_id": self.llm_execution_id,
            "prompt_package_id": self.prompt_package_id,
            "context_package_id": self.context_package_id,
            "assistant_runtime_id": self.assistant_runtime_id,
            "raw_output_available": self.raw_output_available,
            "context_citation_count": self.context_citation_count,
            "request_metadata": dict(self.request_metadata),
        }


@dataclass(frozen=True)
class AssistantCitationVerificationSessionDescriptor:
    citation_verification_session_id: str | None
    request: AssistantCitationVerificationRequest
    verification_state: str
    blocking_issues: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    next_available_actions: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        ready = self.verification_state == "ready"
        return {
            "assistant_citation_verification_session_schema_version": "1",
            "citation_verification_session_id": self.citation_verification_session_id,
            "assistant_citation_verification_session_ready": ready,
            "verification_state": self.verification_state,
            "request": self.request.as_dict(),
            "llm_execution_id": self.request.llm_execution_id,
            "prompt_package_id": self.request.prompt_package_id,
            "context_package_id": self.request.context_package_id,
            "assistant_runtime_id": self.request.assistant_runtime_id,
            "citation_runtime_created": False,
            "verification_completed": False,
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
class AssistantCitationVerificationHealthResult:
    assistant_citation_verification_available: bool = True
    assistant_citation_verification_status: str = "deterministic_metadata_verification"
    llm_used: bool = False
    embeddings_used: bool = False
    provider_called: bool = False
    final_response_created: bool = False
    tool_called: bool = False
    workflow_executed: bool = False
    external_action_called: bool = False
    autonomous_execution: bool = False
    postgresql_source_of_truth: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "assistant_citation_verification_health_schema_version": "1",
            "assistant_citation_verification_available": self.assistant_citation_verification_available,
            "assistant_citation_verification_status": self.assistant_citation_verification_status,
            "llm_used": self.llm_used,
            "embeddings_used": self.embeddings_used,
            "provider_called": self.provider_called,
            "final_response_created": self.final_response_created,
            "tool_called": self.tool_called,
            "workflow_executed": self.workflow_executed,
            "external_action_called": self.external_action_called,
            "autonomous_execution": self.autonomous_execution,
            "postgresql_source_of_truth": self.postgresql_source_of_truth,
        }
