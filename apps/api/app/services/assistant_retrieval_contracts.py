"""Metadata-only Assistant Retrieval Planning contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class AssistantRetrievalPlanRequest:
    assistant_id: str
    assistant_session_id: str | None = None
    requested_query: str | None = None
    selected_search_mode: str = "enterprise_search"
    selected_runtime_domain: str = "enterprise_search"
    runtime_metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "assistant_retrieval_plan_request_schema_version": "1",
            "assistant_id": self.assistant_id,
            "assistant_session_id": self.assistant_session_id,
            "requested_query": self.requested_query,
            "selected_search_mode": self.selected_search_mode,
            "selected_runtime_domain": self.selected_runtime_domain,
            "runtime_metadata": dict(self.runtime_metadata),
        }


@dataclass(frozen=True)
class AssistantRetrievalSessionDescriptor:
    retrieval_session_id: str | None
    request: AssistantRetrievalPlanRequest
    retrieval_state: str
    enterprise_search_planned: bool
    semantic_search_planned: bool = False
    hybrid_search_planned: bool = False
    runtime_metadata: dict[str, Any] = field(default_factory=dict)
    blocking_issues: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    next_available_actions: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        ready = self.retrieval_state == "ready"
        return {
            "assistant_retrieval_session_descriptor_schema_version": "1",
            "retrieval_session_id": self.retrieval_session_id,
            "assistant_retrieval_session_ready": ready,
            "retrieval_state": self.retrieval_state,
            "request": self.request.as_dict(),
            "assistant_id": self.request.assistant_id,
            "assistant_session_id": self.request.assistant_session_id,
            "requested_query": self.request.requested_query,
            "selected_search_mode": self.request.selected_search_mode,
            "selected_runtime_domain": self.request.selected_runtime_domain,
            "enterprise_search_planned": self.enterprise_search_planned,
            "hybrid_search_planned": self.hybrid_search_planned,
            "semantic_search_planned": self.semantic_search_planned,
            "retrieval_executed": False,
            "answer_generated": False,
            "llm_used": False,
            "tool_called": False,
            "workflow_executed": False,
            "autonomous_execution": False,
            "postgresql_source_of_truth": True,
            "runtime_metadata": dict(self.runtime_metadata),
            "blocking_issues": list(self.blocking_issues),
            "warnings": list(self.warnings),
            "next_available_actions": list(self.next_available_actions),
        }


@dataclass(frozen=True)
class AssistantRetrievalRuntimePlan:
    session: AssistantRetrievalSessionDescriptor
    retrieval_plan_id: str | None
    assistant_id: str
    assistant_session_id: str | None
    execution_allowed: bool = False
    descriptor_only: bool = True
    retrieval_plan_created: bool = True
    retrieval_executed: bool = False
    answer_generated: bool = False
    llm_used: bool = False
    tool_called: bool = False
    workflow_executed: bool = False
    autonomous_execution: bool = False
    postgresql_source_of_truth: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "assistant_retrieval_runtime_plan_schema_version": "1",
            "session": self.session.as_dict(),
            "retrieval_plan_id": self.retrieval_plan_id,
            "assistant_id": self.assistant_id,
            "assistant_session_id": self.assistant_session_id,
            "execution_allowed": self.execution_allowed,
            "descriptor_only": self.descriptor_only,
            "retrieval_plan_created": self.retrieval_plan_created,
            "selected_search_mode": self.session.request.selected_search_mode,
            "enterprise_search_planned": self.session.enterprise_search_planned,
            "hybrid_search_planned": self.session.hybrid_search_planned,
            "semantic_search_planned": self.session.semantic_search_planned,
            "retrieval_executed": self.retrieval_executed,
            "answer_generated": self.answer_generated,
            "llm_used": self.llm_used,
            "tool_called": self.tool_called,
            "workflow_executed": self.workflow_executed,
            "autonomous_execution": self.autonomous_execution,
            "postgresql_source_of_truth": self.postgresql_source_of_truth,
        }


@dataclass(frozen=True)
class AssistantRetrievalRuntimeResult:
    runtime_plan: AssistantRetrievalRuntimePlan
    plan_status: str
    execution_state: str
    retrieval_plan_created: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "assistant_retrieval_runtime_result_schema_version": "1",
            "plan_status": self.plan_status,
            "execution_state": self.execution_state,
            "retrieval_plan_created": self.retrieval_plan_created,
            "assistant_retrieval_runtime_prepared": True,
            "selected_search_mode": self.runtime_plan.session.request.selected_search_mode,
            "enterprise_search_planned": self.runtime_plan.session.enterprise_search_planned,
            "hybrid_search_planned": self.runtime_plan.session.hybrid_search_planned,
            "semantic_search_planned": self.runtime_plan.session.semantic_search_planned,
            "retrieval_executed": False,
            "answer_generated": False,
            "llm_used": False,
            "tool_called": False,
            "workflow_executed": False,
            "autonomous_execution": False,
            "postgresql_source_of_truth": True,
            "runtime_plan": self.runtime_plan.as_dict(),
        }


@dataclass(frozen=True)
class AssistantRetrievalHealthResult:
    assistant_retrieval_runtime_available: bool = True
    assistant_retrieval_runtime_status: str = "metadata_only"
    selected_search_mode: str = "enterprise_search"
    enterprise_search_planned: bool = True
    hybrid_search_planned: bool = False
    semantic_search_planned: bool = False
    retrieval_executed: bool = False
    answer_generated: bool = False
    llm_used: bool = False
    tool_called: bool = False
    workflow_executed: bool = False
    autonomous_execution: bool = False
    postgresql_source_of_truth: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "assistant_retrieval_health_schema_version": "1",
            "assistant_retrieval_runtime_available": self.assistant_retrieval_runtime_available,
            "assistant_retrieval_runtime_status": self.assistant_retrieval_runtime_status,
            "selected_search_mode": self.selected_search_mode,
            "enterprise_search_planned": self.enterprise_search_planned,
            "hybrid_search_planned": self.hybrid_search_planned,
            "semantic_search_planned": self.semantic_search_planned,
            "retrieval_executed": self.retrieval_executed,
            "answer_generated": self.answer_generated,
            "llm_used": self.llm_used,
            "tool_called": self.tool_called,
            "workflow_executed": self.workflow_executed,
            "autonomous_execution": self.autonomous_execution,
            "postgresql_source_of_truth": self.postgresql_source_of_truth,
        }
