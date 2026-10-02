"""Descriptor-only Hybrid Search Runtime contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class HybridSearchRequest:
    query: str
    normalized_query: str
    top_k: int = 5
    hybrid_search_enabled: bool = False
    runtime_metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "hybrid_search_request_schema_version": "1",
            "query": self.query,
            "normalized_query": self.normalized_query,
            "top_k": self.top_k,
            "hybrid_search_enabled": self.hybrid_search_enabled,
            "runtime_metadata": dict(self.runtime_metadata),
            "hybrid_search_executed": False,
            "lexical_search_available": True,
            "lexical_search_source": "postgresql_fts",
            "semantic_search_available": True,
            "semantic_search_executed": False,
            "vector_search_executed": False,
            "qdrant_called": False,
            "reranking_executed": False,
            "llm_used": False,
            "assistant_used": False,
            "enterprise_search_uses_postgresql_fts": True,
            "postgresql_source_of_truth": True,
        }


@dataclass(frozen=True)
class HybridSearchSessionDescriptor:
    hybrid_search_session_id: str | None
    request: HybridSearchRequest
    hybrid_search_state: str
    lexical_search_available: bool
    semantic_search_available: bool
    semantic_search_health: dict[str, Any]
    runtime_metadata: dict[str, Any] = field(default_factory=dict)
    blocking_issues: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    next_available_actions: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        ready = self.hybrid_search_state == "ready"
        return {
            "hybrid_search_session_schema_version": "1",
            "hybrid_search_session_id": self.hybrid_search_session_id,
            "hybrid_search_session_ready": ready,
            "hybrid_search_state": self.hybrid_search_state,
            "request": self.request.as_dict(),
            "query": self.request.query,
            "normalized_query": self.request.normalized_query,
            "top_k": self.request.top_k,
            "lexical_search_available": self.lexical_search_available,
            "lexical_search_source": "postgresql_fts",
            "semantic_search_available": self.semantic_search_available,
            "semantic_search_health": dict(self.semantic_search_health),
            "runtime_metadata": dict(self.runtime_metadata),
            "hybrid_search_enabled": False,
            "hybrid_search_executed": False,
            "semantic_search_executed": False,
            "vector_search_executed": False,
            "qdrant_called": False,
            "reranking_executed": False,
            "llm_used": False,
            "assistant_used": False,
            "enterprise_search_uses_postgresql_fts": True,
            "postgresql_source_of_truth": True,
            "blocking_issues": list(self.blocking_issues),
            "warnings": list(self.warnings),
            "next_available_actions": list(self.next_available_actions),
        }


@dataclass(frozen=True)
class HybridSearchExecutionPlan:
    session: HybridSearchSessionDescriptor
    execution_allowed: bool = False
    descriptor_only: bool = True
    hybrid_search_enabled: bool = False
    hybrid_search_executed: bool = False
    lexical_search_available: bool = True
    lexical_search_source: str = "postgresql_fts"
    semantic_search_available: bool = True
    semantic_search_executed: bool = False
    vector_search_executed: bool = False
    qdrant_called: bool = False
    reranking_executed: bool = False
    llm_used: bool = False
    assistant_used: bool = False
    enterprise_search_uses_postgresql_fts: bool = True
    postgresql_source_of_truth: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "hybrid_search_execution_plan_schema_version": "1",
            "session": self.session.as_dict(),
            "execution_allowed": self.execution_allowed,
            "descriptor_only": self.descriptor_only,
            "hybrid_search_enabled": self.hybrid_search_enabled,
            "hybrid_search_executed": self.hybrid_search_executed,
            "lexical_search_available": self.lexical_search_available,
            "lexical_search_source": self.lexical_search_source,
            "semantic_search_available": self.semantic_search_available,
            "semantic_search_executed": self.semantic_search_executed,
            "vector_search_executed": self.vector_search_executed,
            "qdrant_called": self.qdrant_called,
            "reranking_executed": self.reranking_executed,
            "llm_used": self.llm_used,
            "assistant_used": self.assistant_used,
            "enterprise_search_uses_postgresql_fts": self.enterprise_search_uses_postgresql_fts,
            "postgresql_source_of_truth": self.postgresql_source_of_truth,
        }


@dataclass(frozen=True)
class HybridSearchResult:
    execution_plan: HybridSearchExecutionPlan
    hybrid_search_status: str = "prepared"
    result_count: int = 0
    results: list[dict[str, Any]] = field(default_factory=list)
    hybrid_search_enabled: bool = False
    hybrid_search_executed: bool = False
    lexical_search_available: bool = True
    lexical_search_source: str = "postgresql_fts"
    semantic_search_available: bool = True
    semantic_search_executed: bool = False
    vector_search_executed: bool = False
    qdrant_called: bool = False
    reranking_executed: bool = False
    llm_used: bool = False
    assistant_used: bool = False
    enterprise_search_still_uses_postgresql_fts: bool = True
    postgresql_source_of_truth: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "hybrid_search_result_schema_version": "1",
            "hybrid_search_status": self.hybrid_search_status,
            "result_count": self.result_count,
            "results": list(self.results),
            "execution_plan": self.execution_plan.as_dict(),
            "hybrid_search_enabled": self.hybrid_search_enabled,
            "hybrid_search_executed": self.hybrid_search_executed,
            "lexical_search_available": self.lexical_search_available,
            "lexical_search_source": self.lexical_search_source,
            "semantic_search_available": self.semantic_search_available,
            "semantic_search_executed": self.semantic_search_executed,
            "vector_search_executed": self.vector_search_executed,
            "qdrant_called": self.qdrant_called,
            "reranking_executed": self.reranking_executed,
            "llm_used": self.llm_used,
            "assistant_used": self.assistant_used,
            "enterprise_search_still_uses_postgresql_fts": self.enterprise_search_still_uses_postgresql_fts,
            "enterprise_search_uses_postgresql_fts": self.enterprise_search_still_uses_postgresql_fts,
            "postgresql_source_of_truth": self.postgresql_source_of_truth,
        }


@dataclass(frozen=True)
class HybridSearchHealth:
    hybrid_search_runtime_available: bool = True
    hybrid_search_status: str = "disabled"
    hybrid_search_enabled: bool = False
    hybrid_search_executed: bool = False
    lexical_search_available: bool = True
    lexical_search_source: str = "postgresql_fts"
    semantic_search_available: bool = True
    semantic_search_executed: bool = False
    vector_search_executed: bool = False
    qdrant_called: bool = False
    reranking_executed: bool = False
    llm_used: bool = False
    assistant_used: bool = False
    enterprise_search_uses_postgresql_fts: bool = True
    postgresql_source_of_truth: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "hybrid_search_health_schema_version": "1",
            "hybrid_search_runtime_available": self.hybrid_search_runtime_available,
            "hybrid_search_status": self.hybrid_search_status,
            "hybrid_search_enabled": self.hybrid_search_enabled,
            "hybrid_search_executed": self.hybrid_search_executed,
            "lexical_search_available": self.lexical_search_available,
            "lexical_search_source": self.lexical_search_source,
            "semantic_search_available": self.semantic_search_available,
            "semantic_search_executed": self.semantic_search_executed,
            "vector_search_executed": self.vector_search_executed,
            "qdrant_called": self.qdrant_called,
            "reranking_executed": self.reranking_executed,
            "llm_used": self.llm_used,
            "assistant_used": self.assistant_used,
            "enterprise_search_uses_postgresql_fts": self.enterprise_search_uses_postgresql_fts,
            "enterprise_search_still_uses_postgresql_fts": self.enterprise_search_uses_postgresql_fts,
            "postgresql_source_of_truth": self.postgresql_source_of_truth,
        }
