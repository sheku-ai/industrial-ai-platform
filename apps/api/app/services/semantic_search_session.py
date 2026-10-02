"""Semantic Search Runtime session foundation."""

from __future__ import annotations

import hashlib
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.repositories.vector_index import VectorIndexRepository
from app.services.enterprise_search_session import issue, normalize_query_text, sort_issues
from app.services.qdrant_provider_registry import get_qdrant_provider_registry
from app.services.semantic_search_contracts import SemanticSearchRequest, SemanticSearchSessionDescriptor

SEMANTIC_SEARCH_STATE_BLOCKED = "blocked"
SEMANTIC_SEARCH_STATE_READY = "ready"
DEFAULT_TOP_K = 5
MAX_TOP_K = 50


def _stable_session_id(*, normalized_query: str, vector_index_id: str | None, top_k: int) -> str | None:
    if not normalized_query:
        return None
    digest = hashlib.sha256(f"{normalized_query}|{vector_index_id}|{top_k}|semantic-search".encode()).hexdigest()[:24]
    return f"semantic-search-session:{digest}"


def _resolve_top_k(top_k: int | None) -> int:
    try:
        value = int(top_k if top_k is not None else DEFAULT_TOP_K)
    except (TypeError, ValueError):
        return DEFAULT_TOP_K
    return max(1, min(value, MAX_TOP_K))


def build_semantic_search_session(
    db: Session,
    *,
    query: str | None,
    top_k: int | None = None,
    vector_index_id: str | None = None,
    qdrant_provider_name: str | None = None,
    semantic_search_enabled: bool = False,
    runtime_metadata: dict[str, Any] | None = None,
) -> SemanticSearchSessionDescriptor:
    normalized_query = normalize_query_text(query)
    resolved_top_k = _resolve_top_k(top_k)
    blocking_issues: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    if not normalized_query:
        blocking_issues.append(
            issue("query_missing", "Semantic search preparation requires a query.", component="semantic_search_session")
        )
    vector_index_record = None
    if vector_index_id:
        try:
            vector_index_record = VectorIndexRepository(db).get_vector_index_record(uuid.UUID(str(vector_index_id)))
        except (TypeError, ValueError):
            blocking_issues.append(
                issue(
                    "vector_index_id_invalid",
                    "Semantic search preparation requires a valid vector index id.",
                    component="vector_index_runtime",
                    item_id=str(vector_index_id),
                )
            )
        if vector_index_record is None and not any(
            item.get("code") == "vector_index_id_invalid" for item in blocking_issues
        ):
            blocking_issues.append(
                issue(
                    "vector_index_record_missing",
                    "Semantic search preparation requires existing vector index metadata.",
                    component="vector_index_runtime",
                    item_id=str(vector_index_id),
                )
            )
    else:
        warnings.append(
            issue(
                "vector_index_record_not_selected",
                "Semantic search is descriptor-only without an explicit vector index record.",
                component="semantic_search_session",
                severity="warning",
            )
        )
    provider_name = qdrant_provider_name
    if vector_index_record is not None:
        runtime_values = vector_index_record.runtime_metadata or {}
        provider_name = (
            provider_name or runtime_values.get("qdrant_provider_name") or vector_index_record.index_provider
        )
    qdrant_provider, qdrant_resolution = get_qdrant_provider_registry().resolve(provider_name)
    if semantic_search_enabled:
        warnings.append(
            issue(
                "semantic_search_execution_disabled",
                "Semantic search execution remains descriptor-only in this foundation.",
                component="semantic_search_session",
                severity="warning",
            )
        )
    ready = not blocking_issues
    request = SemanticSearchRequest(
        query=str(query or ""),
        normalized_query=normalized_query,
        top_k=resolved_top_k,
        vector_index_id=str(vector_index_id) if vector_index_id else None,
        qdrant_provider_name=qdrant_provider.provider_name,
        semantic_search_enabled=False,
        runtime_metadata=dict(runtime_metadata or {}),
    )
    return SemanticSearchSessionDescriptor(
        semantic_search_session_id=_stable_session_id(
            normalized_query=normalized_query, vector_index_id=vector_index_id, top_k=resolved_top_k
        ),
        request=request,
        semantic_search_state=SEMANTIC_SEARCH_STATE_READY if ready else SEMANTIC_SEARCH_STATE_BLOCKED,
        vector_index_available=vector_index_record is not None,
        qdrant_provider_descriptor=qdrant_provider.as_dict(),
        runtime_metadata={
            **dict(runtime_metadata or {}),
            "semantic_search_runtime_version": "semantic_search_runtime/1.0",
            "vector_index_id": str(vector_index_record.vector_index_id) if vector_index_record is not None else None,
            "vector_index_status": vector_index_record.index_status if vector_index_record is not None else None,
            "qdrant_provider_resolution": qdrant_resolution,
            "semantic_search_enabled": False,
            "semantic_search_executed": False,
            "vector_search_executed": False,
            "qdrant_called": False,
            "network_call_attempted": False,
            "hybrid_search_enabled": False,
            "enterprise_search_uses_postgresql_fts": True,
            "postgresql_source_of_truth": True,
        },
        blocking_issues=sort_issues(blocking_issues),
        warnings=sort_issues(warnings),
        next_available_actions=[
            {
                "action": "build_semantic_search_execution_plan",
                "available": ready,
                "status": "ready" if ready else "blocked",
                "reason": None if ready else "semantic_search_session_blocked",
            }
        ],
    )


def serialize_semantic_search_session(session: SemanticSearchSessionDescriptor) -> dict[str, Any]:
    return session.as_dict()
