"""Semantic Search Runtime gateway."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.services.qdrant_provider_contracts import QdrantProviderDescriptor
from app.services.qdrant_provider_runtime import get_qdrant_provider_runtime_adapter
from app.services.semantic_search_contracts import SemanticSearchHealth
from app.services.semantic_search_session import build_semantic_search_session, serialize_semantic_search_session


def build_semantic_search_gateway(
    db: Session,
    *,
    query: str | None,
    top_k: int | None = None,
    vector_index_id: str | None = None,
    qdrant_provider_name: str | None = None,
    semantic_search_enabled: bool = False,
    runtime_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    session_descriptor = build_semantic_search_session(
        db,
        query=query,
        top_k=top_k,
        vector_index_id=vector_index_id,
        qdrant_provider_name=qdrant_provider_name,
        semantic_search_enabled=semantic_search_enabled,
        runtime_metadata=runtime_metadata,
    )
    session = serialize_semantic_search_session(session_descriptor)
    provider = session_descriptor.qdrant_provider_descriptor
    qdrant_health = (
        get_qdrant_provider_runtime_adapter()
        .evaluate_health(
            QdrantProviderDescriptor(
                provider_name=provider.get("provider_name") or "qdrant-disabled",
                provider_type=provider.get("provider_type") or "descriptor-only",
                provider_version=provider.get("provider_version") or "descriptor-only/1.0",
                enabled=bool(provider.get("enabled")),
                descriptor_only=bool(provider.get("descriptor_only", True)),
                endpoint_configured=bool(provider.get("endpoint_configured")),
                collection_name=provider.get("collection_name") or "derived-vector-index",
                collection_status=provider.get("collection_status") or "disabled",
                vector_dimensions=int(provider.get("vector_dimensions") or 0),
                distance_metric=provider.get("distance_metric") or "cosine",
            )
        )
        .as_dict()
    )
    ready = bool(session.get("semantic_search_session_ready")) and not session.get("blocking_issues")
    return {
        "semantic_search_gateway_schema_version": "1",
        "semantic_search_gateway_ready": ready,
        "gateway_status": "ready" if ready else "blocked",
        "semantic_search_session": session,
        "qdrant_connection_health": qdrant_health,
        "source_of_truth": "postgresql",
        "semantic_search_enabled": False,
        "semantic_search_executed": False,
        "vector_search_executed": False,
        "qdrant_called": False,
        "network_call_attempted": False,
        "hybrid_search_enabled": False,
        "enterprise_search_uses_postgresql_fts": True,
        "enterprise_search_still_uses_postgresql_fts": True,
        "postgresql_source_of_truth": True,
        "blocking_issues": session.get("blocking_issues") or [],
        "warnings": session.get("warnings") or [],
        "next_available_actions": [
            {
                "action": "prepare_semantic_search_runtime",
                "available": ready,
                "status": "ready" if ready else "blocked",
                "reason": None if ready else "semantic_search_gateway_blocked",
            }
        ],
    }


def build_semantic_search_health() -> dict[str, Any]:
    return SemanticSearchHealth().as_dict()
