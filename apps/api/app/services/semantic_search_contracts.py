"""Descriptor-only Semantic Search Runtime contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SemanticSearchRequest:
    query: str
    normalized_query: str
    top_k: int = 5
    vector_index_id: str | None = None
    qdrant_provider_name: str | None = None
    semantic_search_enabled: bool = False
    runtime_metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "semantic_search_request_schema_version": "1",
            "query": self.query,
            "normalized_query": self.normalized_query,
            "top_k": self.top_k,
            "vector_index_id": self.vector_index_id,
            "qdrant_provider_name": self.qdrant_provider_name,
            "semantic_search_enabled": self.semantic_search_enabled,
            "runtime_metadata": dict(self.runtime_metadata),
            "semantic_search_executed": False,
            "vector_search_executed": False,
            "qdrant_called": False,
            "network_call_attempted": False,
            "hybrid_search_enabled": False,
            "enterprise_search_uses_postgresql_fts": True,
            "postgresql_source_of_truth": True,
        }


@dataclass(frozen=True)
class SemanticSearchSessionDescriptor:
    semantic_search_session_id: str | None
    request: SemanticSearchRequest
    semantic_search_state: str
    vector_index_available: bool
    qdrant_provider_descriptor: dict[str, Any]
    runtime_metadata: dict[str, Any] = field(default_factory=dict)
    blocking_issues: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    next_available_actions: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        ready = self.semantic_search_state == "ready"
        return {
            "semantic_search_session_schema_version": "1",
            "semantic_search_session_id": self.semantic_search_session_id,
            "semantic_search_session_ready": ready,
            "semantic_search_state": self.semantic_search_state,
            "request": self.request.as_dict(),
            "query": self.request.query,
            "normalized_query": self.request.normalized_query,
            "top_k": self.request.top_k,
            "vector_index_id": self.request.vector_index_id,
            "vector_index_available": self.vector_index_available,
            "qdrant_provider_descriptor": dict(self.qdrant_provider_descriptor),
            "runtime_metadata": dict(self.runtime_metadata),
            "semantic_search_enabled": False,
            "semantic_search_executed": False,
            "vector_search_executed": False,
            "qdrant_called": False,
            "network_call_attempted": False,
            "hybrid_search_enabled": False,
            "enterprise_search_uses_postgresql_fts": True,
            "postgresql_source_of_truth": True,
            "blocking_issues": list(self.blocking_issues),
            "warnings": list(self.warnings),
            "next_available_actions": list(self.next_available_actions),
        }


@dataclass(frozen=True)
class SemanticSearchExecutionPlan:
    session: SemanticSearchSessionDescriptor
    execution_allowed: bool = False
    descriptor_only: bool = True
    semantic_search_enabled: bool = False
    semantic_search_executed: bool = False
    vector_search_executed: bool = False
    qdrant_called: bool = False
    network_call_attempted: bool = False
    hybrid_search_enabled: bool = False
    enterprise_search_uses_postgresql_fts: bool = True
    postgresql_source_of_truth: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "semantic_search_execution_plan_schema_version": "1",
            "session": self.session.as_dict(),
            "execution_allowed": self.execution_allowed,
            "descriptor_only": self.descriptor_only,
            "semantic_search_enabled": self.semantic_search_enabled,
            "semantic_search_executed": self.semantic_search_executed,
            "vector_search_executed": self.vector_search_executed,
            "qdrant_called": self.qdrant_called,
            "network_call_attempted": self.network_call_attempted,
            "hybrid_search_enabled": self.hybrid_search_enabled,
            "enterprise_search_uses_postgresql_fts": self.enterprise_search_uses_postgresql_fts,
            "postgresql_source_of_truth": self.postgresql_source_of_truth,
        }


@dataclass(frozen=True)
class SemanticSearchResult:
    execution_plan: SemanticSearchExecutionPlan
    semantic_search_status: str = "prepared"
    result_count: int = 0
    results: list[dict[str, Any]] = field(default_factory=list)
    semantic_search_enabled: bool = False
    semantic_search_executed: bool = False
    vector_search_executed: bool = False
    qdrant_called: bool = False
    network_call_attempted: bool = False
    hybrid_search_enabled: bool = False
    enterprise_search_still_uses_postgresql_fts: bool = True
    postgresql_source_of_truth: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "semantic_search_result_schema_version": "1",
            "semantic_search_status": self.semantic_search_status,
            "result_count": self.result_count,
            "results": list(self.results),
            "execution_plan": self.execution_plan.as_dict(),
            "semantic_search_enabled": self.semantic_search_enabled,
            "semantic_search_executed": self.semantic_search_executed,
            "vector_search_executed": self.vector_search_executed,
            "qdrant_called": self.qdrant_called,
            "network_call_attempted": self.network_call_attempted,
            "hybrid_search_enabled": self.hybrid_search_enabled,
            "enterprise_search_still_uses_postgresql_fts": self.enterprise_search_still_uses_postgresql_fts,
            "enterprise_search_uses_postgresql_fts": self.enterprise_search_still_uses_postgresql_fts,
            "postgresql_source_of_truth": self.postgresql_source_of_truth,
        }


@dataclass(frozen=True)
class SemanticSearchHealth:
    semantic_search_runtime_available: bool = True
    semantic_search_status: str = "disabled"
    semantic_search_enabled: bool = False
    semantic_search_executed: bool = False
    vector_search_executed: bool = False
    qdrant_called: bool = False
    network_call_attempted: bool = False
    hybrid_search_enabled: bool = False
    enterprise_search_uses_postgresql_fts: bool = True
    postgresql_source_of_truth: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "semantic_search_health_schema_version": "1",
            "semantic_search_runtime_available": self.semantic_search_runtime_available,
            "semantic_search_status": self.semantic_search_status,
            "semantic_search_enabled": self.semantic_search_enabled,
            "semantic_search_executed": self.semantic_search_executed,
            "vector_search_executed": self.vector_search_executed,
            "qdrant_called": self.qdrant_called,
            "network_call_attempted": self.network_call_attempted,
            "hybrid_search_enabled": self.hybrid_search_enabled,
            "enterprise_search_uses_postgresql_fts": self.enterprise_search_uses_postgresql_fts,
            "enterprise_search_still_uses_postgresql_fts": self.enterprise_search_uses_postgresql_fts,
            "postgresql_source_of_truth": self.postgresql_source_of_truth,
        }
