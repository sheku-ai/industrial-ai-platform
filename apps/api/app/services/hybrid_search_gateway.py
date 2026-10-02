"""Hybrid Search Runtime gateway."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.services.hybrid_search_contracts import HybridSearchHealth
from app.services.hybrid_search_session import build_hybrid_search_session, serialize_hybrid_search_session


def build_hybrid_search_gateway(
    db: Session,
    *,
    query: str | None,
    top_k: int | None = None,
    hybrid_search_enabled: bool = False,
    runtime_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    session_descriptor = build_hybrid_search_session(
        db,
        query=query,
        top_k=top_k,
        hybrid_search_enabled=hybrid_search_enabled,
        runtime_metadata=runtime_metadata,
    )
    session = serialize_hybrid_search_session(session_descriptor)
    ready = bool(session.get("hybrid_search_session_ready")) and not session.get("blocking_issues")
    return {
        "hybrid_search_gateway_schema_version": "1",
        "hybrid_search_gateway_ready": ready,
        "gateway_status": "ready" if ready else "blocked",
        "hybrid_search_session": session,
        "source_of_truth": "postgresql",
        "hybrid_search_enabled": False,
        "hybrid_search_executed": False,
        "lexical_search_available": bool(session.get("lexical_search_available")),
        "lexical_search_source": "postgresql_fts",
        "semantic_search_available": bool(session.get("semantic_search_available")),
        "semantic_search_executed": False,
        "vector_search_executed": False,
        "qdrant_called": False,
        "reranking_executed": False,
        "llm_used": False,
        "assistant_used": False,
        "enterprise_search_uses_postgresql_fts": True,
        "enterprise_search_still_uses_postgresql_fts": True,
        "postgresql_source_of_truth": True,
        "blocking_issues": session.get("blocking_issues") or [],
        "warnings": session.get("warnings") or [],
        "next_available_actions": [
            {
                "action": "prepare_hybrid_search_runtime",
                "available": ready,
                "status": "ready" if ready else "blocked",
                "reason": None if ready else "hybrid_search_gateway_blocked",
            }
        ],
    }


def build_hybrid_search_health() -> dict[str, Any]:
    return HybridSearchHealth().as_dict()
