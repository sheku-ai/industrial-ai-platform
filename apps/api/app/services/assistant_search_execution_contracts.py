"""Assistant Enterprise Search Execution contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class AssistantSearchExecutionRequest:
    execution_plan_id: str
    retrieval_plan_id: str
    assistant_id: str
    assistant_session_id: str | None
    search_query: str
    search_mode: str = "enterprise_search"
    runtime_domain: str = "enterprise_search"
    top_k: int = 10
    search_config: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "assistant_search_execution_request_schema_version": "1",
            "execution_plan_id": self.execution_plan_id,
            "retrieval_plan_id": self.retrieval_plan_id,
            "assistant_id": self.assistant_id,
            "assistant_session_id": self.assistant_session_id,
            "search_query": self.search_query,
            "search_mode": self.search_mode,
            "runtime_domain": self.runtime_domain,
            "top_k": self.top_k,
            "search_config": dict(self.search_config),
        }


@dataclass(frozen=True)
class AssistantSearchExecutionSessionDescriptor:
    search_execution_session_id: str | None
    request: AssistantSearchExecutionRequest
    search_execution_state: str
    blocking_issues: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    next_available_actions: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        ready = self.search_execution_state == "ready"
        return {
            "assistant_search_execution_session_schema_version": "1",
            "search_execution_session_id": self.search_execution_session_id,
            "assistant_search_execution_session_ready": ready,
            "search_execution_state": self.search_execution_state,
            "request": self.request.as_dict(),
            "execution_plan_id": self.request.execution_plan_id,
            "retrieval_plan_id": self.request.retrieval_plan_id,
            "assistant_id": self.request.assistant_id,
            "assistant_session_id": self.request.assistant_session_id,
            "search_query": self.request.search_query,
            "selected_search_mode": self.request.search_mode,
            "selected_runtime_domain": self.request.runtime_domain,
            "assistant_search_execution_prepared": ready,
            "lexical_search_used": ready,
            "postgresql_fts_used": ready,
            "semantic_search_used": False,
            "hybrid_search_used": False,
            "qdrant_used": False,
            "reranking_used": False,
            "llm_used": False,
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
class AssistantSearchExecutionHealthResult:
    assistant_search_execution_available: bool = True
    assistant_search_execution_status: str = "enterprise_search_fts"
    selected_search_mode: str = "enterprise_search"
    selected_runtime_domain: str = "enterprise_search"
    lexical_search_used: bool = True
    postgresql_fts_used: bool = True
    semantic_search_used: bool = False
    hybrid_search_used: bool = False
    qdrant_used: bool = False
    reranking_used: bool = False
    llm_used: bool = False
    answer_generated: bool = False
    tool_called: bool = False
    workflow_executed: bool = False
    external_action_called: bool = False
    autonomous_execution: bool = False
    postgresql_source_of_truth: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "assistant_search_execution_health_schema_version": "1",
            "assistant_search_execution_available": self.assistant_search_execution_available,
            "assistant_search_execution_status": self.assistant_search_execution_status,
            "selected_search_mode": self.selected_search_mode,
            "selected_runtime_domain": self.selected_runtime_domain,
            "lexical_search_used": self.lexical_search_used,
            "postgresql_fts_used": self.postgresql_fts_used,
            "semantic_search_used": self.semantic_search_used,
            "hybrid_search_used": self.hybrid_search_used,
            "qdrant_used": self.qdrant_used,
            "reranking_used": self.reranking_used,
            "llm_used": self.llm_used,
            "answer_generated": self.answer_generated,
            "tool_called": self.tool_called,
            "workflow_executed": self.workflow_executed,
            "external_action_called": self.external_action_called,
            "autonomous_execution": self.autonomous_execution,
            "postgresql_source_of_truth": self.postgresql_source_of_truth,
        }
