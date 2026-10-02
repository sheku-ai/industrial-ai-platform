from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.services.qdrant_provider_contracts import QdrantProviderDescriptor
from app.services.semantic_search_contracts import SemanticSearchExecutionPlan, SemanticSearchResult
from app.services.semantic_search_gateway import build_semantic_search_gateway, build_semantic_search_health
from app.services.semantic_search_session import build_semantic_search_session


def _execution_plan(db: Session, gateway: dict[str, Any]) -> SemanticSearchExecutionPlan:
    session = gateway.get("semantic_search_session") if isinstance(gateway.get("semantic_search_session"), dict) else {}
    request = session.get("request") if isinstance(session.get("request"), dict) else {}
    qdrant_provider = (
        session.get("qdrant_provider_descriptor") if isinstance(session.get("qdrant_provider_descriptor"), dict) else {}
    )
    descriptor = QdrantProviderDescriptor(
        provider_name=qdrant_provider.get("provider_name") or "qdrant-disabled",
        provider_type=qdrant_provider.get("provider_type") or "descriptor-only",
        provider_version=qdrant_provider.get("provider_version") or "descriptor-only/1.0",
        enabled=bool(qdrant_provider.get("enabled")),
        descriptor_only=bool(qdrant_provider.get("descriptor_only", True)),
        endpoint_configured=bool(qdrant_provider.get("endpoint_configured")),
        collection_name=qdrant_provider.get("collection_name") or "derived-vector-index",
        collection_status=qdrant_provider.get("collection_status") or "disabled",
        vector_dimensions=int(qdrant_provider.get("vector_dimensions") or 0),
        distance_metric=qdrant_provider.get("distance_metric") or "cosine",
    )
    session_descriptor = build_semantic_search_session(
        db,
        query=request.get("query"),
        top_k=request.get("top_k"),
        vector_index_id=request.get("vector_index_id"),
        qdrant_provider_name=descriptor.provider_name,
        semantic_search_enabled=False,
        runtime_metadata=session.get("runtime_metadata") if isinstance(session.get("runtime_metadata"), dict) else {},
    )
    return SemanticSearchExecutionPlan(session=session_descriptor)


def build_semantic_search_runtime(
    db: Session,
    *,
    query: str,
    top_k: int | None = None,
    vector_index_id: str | None = None,
    qdrant_provider_name: str | None = None,
    semantic_search_enabled: bool = False,
    runtime_metadata: dict[str, Any] | None = None,
    persist_snapshot: bool = True,
) -> dict[str, Any]:
    gateway = build_semantic_search_gateway(
        db,
        query=query,
        top_k=top_k,
        vector_index_id=vector_index_id,
        qdrant_provider_name=qdrant_provider_name,
        semantic_search_enabled=semantic_search_enabled,
        runtime_metadata=runtime_metadata,
    )
    plan = _execution_plan(db, gateway)
    result = SemanticSearchResult(
        execution_plan=plan,
        semantic_search_status="prepared" if gateway.get("semantic_search_gateway_ready") else "blocked",
    )
    payload = {
        "semantic_search_runtime_schema_version": "1",
        "semantic_search_runtime_prepared": bool(gateway.get("semantic_search_gateway_ready")),
        "semantic_search_status": result.semantic_search_status,
        "semantic_search_gateway": gateway,
        "semantic_search_execution_plan": plan.as_dict(),
        "semantic_search_result": result.as_dict(),
        "query": result.execution_plan.session.request.query,
        "normalized_query": result.execution_plan.session.request.normalized_query,
        "top_k": result.execution_plan.session.request.top_k,
        "vector_index_id": result.execution_plan.session.request.vector_index_id,
        "semantic_search_enabled": False,
        "semantic_search_executed": False,
        "vector_search_executed": False,
        "qdrant_called": False,
        "network_call_attempted": False,
        "hybrid_search_enabled": False,
        "enterprise_search_uses_postgresql_fts": True,
        "enterprise_search_still_uses_postgresql_fts": True,
        "postgresql_source_of_truth": True,
        "blocking_issues": gateway.get("blocking_issues") or [],
        "warnings": gateway.get("warnings") or [],
        "next_available_actions": gateway.get("next_available_actions") or [],
    }
    if persist_snapshot and payload["semantic_search_runtime_prepared"]:
        from app.services.runtime_persistence_runtime import persist_runtime_outputs

        payload["runtime_persistence"] = persist_runtime_outputs(
            db,
            execution_id=f"semantic-search-runtime:{payload['semantic_search_execution_plan']['session']['semantic_search_session_id']}",
            artifact_id=None,
            runtime_outputs={"semantic_search_runtime": payload},
        )
        payload["runtime_persistence"] = {
            **payload["runtime_persistence"],
            "runtime_persistence": bool(payload["runtime_persistence"].get("persistence_completed")),
        }
    else:
        payload["runtime_persistence"] = {"runtime_persistence": False, "persistence_completed": False}
    return payload


__all__ = [
    "build_semantic_search_health",
    "build_semantic_search_runtime",
]
