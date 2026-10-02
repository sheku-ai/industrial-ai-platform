"""Hybrid Search Runtime session foundation."""

from __future__ import annotations

import hashlib
from typing import Any

from sqlalchemy.orm import Session

from app.repositories.knowledge_index import KnowledgeIndexRepository
from app.services.enterprise_search_session import issue, normalize_query_text, sort_issues
from app.services.hybrid_search_contracts import HybridSearchRequest, HybridSearchSessionDescriptor
from app.services.semantic_search_runtime import build_semantic_search_health

HYBRID_SEARCH_STATE_BLOCKED = "blocked"
HYBRID_SEARCH_STATE_READY = "ready"
DEFAULT_TOP_K = 5
MAX_TOP_K = 50


def _stable_session_id(*, normalized_query: str, top_k: int) -> str | None:
    if not normalized_query:
        return None
    digest = hashlib.sha256(f"{normalized_query}|{top_k}|hybrid-search".encode()).hexdigest()[:24]
    return f"hybrid-search-session:{digest}"


def _resolve_top_k(top_k: int | None) -> int:
    try:
        value = int(top_k if top_k is not None else DEFAULT_TOP_K)
    except (TypeError, ValueError):
        return DEFAULT_TOP_K
    return max(1, min(value, MAX_TOP_K))


def build_hybrid_search_session(
    db: Session,
    *,
    query: str | None,
    top_k: int | None = None,
    hybrid_search_enabled: bool = False,
    runtime_metadata: dict[str, Any] | None = None,
) -> HybridSearchSessionDescriptor:
    normalized_query = normalize_query_text(query)
    resolved_top_k = _resolve_top_k(top_k)
    blocking_issues: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    if not normalized_query:
        blocking_issues.append(
            issue("query_missing", "Hybrid search preparation requires a query.", component="hybrid_search_session")
        )
    indexed_chunk_count = KnowledgeIndexRepository(db).indexed_chunk_count()
    lexical_available = indexed_chunk_count > 0
    if not lexical_available:
        blocking_issues.append(
            issue(
                "postgresql_fts_unavailable",
                "Hybrid search preparation requires indexed PostgreSQL FTS evidence.",
                component="knowledge_fts",
            )
        )
    semantic_health = build_semantic_search_health()
    semantic_available = bool(semantic_health.get("semantic_search_runtime_available"))
    if not semantic_available:
        blocking_issues.append(
            issue(
                "semantic_search_runtime_unavailable",
                "Hybrid search preparation requires Semantic Search Runtime metadata availability.",
                component="semantic_search_runtime",
            )
        )
    if (
        semantic_health.get("semantic_search_enabled") is not False
        or semantic_health.get("semantic_search_executed") is not False
    ):
        blocking_issues.append(
            issue(
                "semantic_search_must_remain_disabled",
                "Sprint 49 requires Semantic Search Runtime to remain disabled.",
                component="semantic_search_runtime",
            )
        )
    if hybrid_search_enabled:
        warnings.append(
            issue(
                "hybrid_search_execution_disabled",
                "Hybrid search execution remains descriptor-only in this foundation.",
                component="hybrid_search_session",
                severity="warning",
            )
        )
    request = HybridSearchRequest(
        query=str(query or ""),
        normalized_query=normalized_query,
        top_k=resolved_top_k,
        hybrid_search_enabled=False,
        runtime_metadata=dict(runtime_metadata or {}),
    )
    ready = not blocking_issues
    return HybridSearchSessionDescriptor(
        hybrid_search_session_id=_stable_session_id(normalized_query=normalized_query, top_k=resolved_top_k),
        request=request,
        hybrid_search_state=HYBRID_SEARCH_STATE_READY if ready else HYBRID_SEARCH_STATE_BLOCKED,
        lexical_search_available=lexical_available,
        semantic_search_available=semantic_available,
        semantic_search_health=semantic_health,
        runtime_metadata={
            **dict(runtime_metadata or {}),
            "hybrid_search_runtime_version": "hybrid_search_runtime/1.0",
            "indexed_chunk_count": indexed_chunk_count,
            "hybrid_search_enabled": False,
            "hybrid_search_executed": False,
            "lexical_search_available": lexical_available,
            "lexical_search_source": "postgresql_fts",
            "semantic_search_available": semantic_available,
            "semantic_search_executed": False,
            "vector_search_executed": False,
            "qdrant_called": False,
            "reranking_executed": False,
            "llm_used": False,
            "assistant_used": False,
            "enterprise_search_uses_postgresql_fts": True,
            "postgresql_source_of_truth": True,
        },
        blocking_issues=sort_issues(blocking_issues),
        warnings=sort_issues(warnings),
        next_available_actions=[
            {
                "action": "build_hybrid_search_execution_plan",
                "available": ready,
                "status": "ready" if ready else "blocked",
                "reason": None if ready else "hybrid_search_session_blocked",
            }
        ],
    )


def serialize_hybrid_search_session(session: HybridSearchSessionDescriptor) -> dict[str, Any]:
    return session.as_dict()
