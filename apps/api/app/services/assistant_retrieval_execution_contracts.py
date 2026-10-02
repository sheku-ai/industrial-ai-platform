"""Assistant Retrieval Execution Readiness contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class AssistantRetrievalExecutionReadinessRequest:
    retrieval_plan_id: str
    assistant_id: str
    assistant_session_id: str | None
    selected_search_mode: str
    selected_runtime_domain: str
    readiness_metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "assistant_retrieval_execution_readiness_request_schema_version": "1",
            "retrieval_plan_id": self.retrieval_plan_id,
            "assistant_id": self.assistant_id,
            "assistant_session_id": self.assistant_session_id,
            "selected_search_mode": self.selected_search_mode,
            "selected_runtime_domain": self.selected_runtime_domain,
            "readiness_metadata": dict(self.readiness_metadata),
        }


@dataclass(frozen=True)
class AssistantRetrievalExecutionSessionDescriptor:
    readiness_session_id: str | None
    request: AssistantRetrievalExecutionReadinessRequest
    readiness_state: str
    enterprise_search_execution_prepared: bool
    semantic_search_execution_prepared: bool = False
    hybrid_search_execution_prepared: bool = False
    blocking_issues: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    next_available_actions: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        ready = self.readiness_state == "ready"
        return {
            "assistant_retrieval_execution_session_descriptor_schema_version": "1",
            "readiness_session_id": self.readiness_session_id,
            "assistant_retrieval_execution_session_ready": ready,
            "readiness_state": self.readiness_state,
            "request": self.request.as_dict(),
            "retrieval_plan_id": self.request.retrieval_plan_id,
            "assistant_id": self.request.assistant_id,
            "assistant_session_id": self.request.assistant_session_id,
            "selected_search_mode": self.request.selected_search_mode,
            "selected_runtime_domain": self.request.selected_runtime_domain,
            "enterprise_search_execution_prepared": self.enterprise_search_execution_prepared,
            "semantic_search_execution_prepared": self.semantic_search_execution_prepared,
            "hybrid_search_execution_prepared": self.hybrid_search_execution_prepared,
            "retrieval_executed": False,
            "answer_generated": False,
            "llm_used": False,
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
class AssistantRetrievalExecutionRuntimePlan:
    session: AssistantRetrievalExecutionSessionDescriptor
    execution_plan_id: str | None
    execution_allowed: bool = False
    descriptor_only: bool = True
    execution_readiness_created: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "assistant_retrieval_execution_runtime_plan_schema_version": "1",
            "session": self.session.as_dict(),
            "execution_plan_id": self.execution_plan_id,
            "execution_allowed": self.execution_allowed,
            "descriptor_only": self.descriptor_only,
            "execution_readiness_created": self.execution_readiness_created,
            "selected_search_mode": self.session.request.selected_search_mode,
            "selected_runtime_domain": self.session.request.selected_runtime_domain,
            "enterprise_search_execution_prepared": self.session.enterprise_search_execution_prepared,
            "semantic_search_execution_prepared": self.session.semantic_search_execution_prepared,
            "hybrid_search_execution_prepared": self.session.hybrid_search_execution_prepared,
            "retrieval_executed": False,
            "answer_generated": False,
            "llm_used": False,
            "tool_called": False,
            "workflow_executed": False,
            "external_action_called": False,
            "autonomous_execution": False,
            "postgresql_source_of_truth": True,
        }


@dataclass(frozen=True)
class AssistantRetrievalExecutionHealthResult:
    assistant_retrieval_execution_readiness_available: bool = True
    assistant_retrieval_execution_readiness_status: str = "readiness_only"
    selected_search_mode: str = "enterprise_search"
    selected_runtime_domain: str = "enterprise_search"
    enterprise_search_execution_prepared: bool = True
    semantic_search_execution_prepared: bool = False
    hybrid_search_execution_prepared: bool = False
    retrieval_executed: bool = False
    answer_generated: bool = False
    llm_used: bool = False
    tool_called: bool = False
    workflow_executed: bool = False
    external_action_called: bool = False
    autonomous_execution: bool = False
    postgresql_source_of_truth: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "assistant_retrieval_execution_health_schema_version": "1",
            "assistant_retrieval_execution_readiness_available": self.assistant_retrieval_execution_readiness_available,
            "assistant_retrieval_execution_readiness_status": self.assistant_retrieval_execution_readiness_status,
            "selected_search_mode": self.selected_search_mode,
            "selected_runtime_domain": self.selected_runtime_domain,
            "enterprise_search_execution_prepared": self.enterprise_search_execution_prepared,
            "semantic_search_execution_prepared": self.semantic_search_execution_prepared,
            "hybrid_search_execution_prepared": self.hybrid_search_execution_prepared,
            "retrieval_executed": self.retrieval_executed,
            "answer_generated": self.answer_generated,
            "llm_used": self.llm_used,
            "tool_called": self.tool_called,
            "workflow_executed": self.workflow_executed,
            "external_action_called": self.external_action_called,
            "autonomous_execution": self.autonomous_execution,
            "postgresql_source_of_truth": self.postgresql_source_of_truth,
        }
