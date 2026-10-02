"""Descriptor-only Hybrid Search Runtime foundation."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.services.enterprise_search_runtime import build_enterprise_search
from app.services.hybrid_search_contracts import HybridSearchExecutionPlan, HybridSearchResult
from app.services.hybrid_search_gateway import build_hybrid_search_gateway, build_hybrid_search_health
from app.services.hybrid_search_session import build_hybrid_search_session
from app.services.semantic_search_runtime import build_semantic_search_runtime


def _execution_plan(db: Session, gateway: dict[str, Any]) -> HybridSearchExecutionPlan:
    session = gateway.get("hybrid_search_session") if isinstance(gateway.get("hybrid_search_session"), dict) else {}
    request = session.get("request") if isinstance(session.get("request"), dict) else {}
    session_descriptor = build_hybrid_search_session(
        db,
        query=request.get("query"),
        top_k=request.get("top_k"),
        hybrid_search_enabled=False,
        runtime_metadata=session.get("runtime_metadata") if isinstance(session.get("runtime_metadata"), dict) else {},
    )
    return HybridSearchExecutionPlan(session=session_descriptor)


def _organization_id_from_metadata(runtime_metadata: dict[str, Any] | None) -> str | None:
    metadata = runtime_metadata if isinstance(runtime_metadata, dict) else {}
    filters = metadata.get("filters") if isinstance(metadata.get("filters"), dict) else {}
    organization_id = metadata.get("organization_id") or filters.get("organization_id")
    return str(organization_id) if organization_id else None


def build_hybrid_search_runtime(
    db: Session,
    *,
    query: str,
    top_k: int | None = None,
    hybrid_search_enabled: bool = False,
    runtime_metadata: dict[str, Any] | None = None,
    persist_snapshot: bool = True,
) -> dict[str, Any]:
    gateway = build_hybrid_search_gateway(
        db,
        query=query,
        top_k=top_k,
        hybrid_search_enabled=hybrid_search_enabled,
        runtime_metadata=runtime_metadata,
    )
    plan = _execution_plan(db, gateway)
    organization_id = _organization_id_from_metadata(runtime_metadata)
    enterprise_search = (
        build_enterprise_search(
            db=db,
            query=query,
            top_k=top_k,
            search_config={"filters": {"organization_id": organization_id}},
            persist_snapshot=False,
        )
        if gateway.get("hybrid_search_gateway_ready")
        else {}
    )
    semantic_search = (
        build_semantic_search_runtime(
            db,
            query=query,
            top_k=top_k,
            persist_snapshot=False,
        )
        if gateway.get("hybrid_search_gateway_ready")
        else {}
    )
    result = HybridSearchResult(
        execution_plan=plan,
        hybrid_search_status="prepared" if gateway.get("hybrid_search_gateway_ready") else "blocked",
    )
    lexical_available = bool(gateway.get("lexical_search_available"))
    semantic_available = bool(gateway.get("semantic_search_available"))
    payload = {
        "hybrid_search_runtime_schema_version": "1",
        "hybrid_search_runtime_prepared": bool(gateway.get("hybrid_search_gateway_ready")),
        "hybrid_search_status": result.hybrid_search_status,
        "hybrid_search_gateway": gateway,
        "hybrid_search_execution_plan": plan.as_dict(),
        "hybrid_search_result": result.as_dict(),
        "enterprise_search_evidence": enterprise_search,
        "semantic_search_evidence": semantic_search,
        "query": plan.session.request.query,
        "normalized_query": plan.session.request.normalized_query,
        "top_k": plan.session.request.top_k,
        "hybrid_search_enabled": False,
        "hybrid_search_executed": False,
        "lexical_search_available": lexical_available,
        "lexical_search_source": "postgresql_fts",
        "enterprise_search_uses_postgresql_fts": True,
        "enterprise_search_still_uses_postgresql_fts": bool(enterprise_search.get("search_uses_postgresql_fts", True)),
        "semantic_search_available": semantic_available,
        "semantic_search_executed": False,
        "vector_search_executed": False,
        "qdrant_called": False,
        "reranking_executed": False,
        "llm_used": False,
        "assistant_used": False,
        "postgresql_source_of_truth": True,
        "blocking_issues": gateway.get("blocking_issues") or [],
        "warnings": gateway.get("warnings") or [],
        "next_available_actions": gateway.get("next_available_actions") or [],
    }
    if persist_snapshot and payload["hybrid_search_runtime_prepared"]:
        from app.services.runtime_persistence_runtime import persist_runtime_outputs

        hybrid_session_id = payload["hybrid_search_execution_plan"]["session"]["hybrid_search_session_id"]
        payload["runtime_persistence"] = persist_runtime_outputs(
            db,
            execution_id=f"hybrid-search-runtime:{hybrid_session_id}",
            artifact_id=None,
            runtime_outputs={"hybrid_search_runtime": payload},
        )
        payload["runtime_persistence"] = {
            **payload["runtime_persistence"],
            "runtime_persistence": bool(payload["runtime_persistence"].get("persistence_completed")),
        }
    else:
        payload["runtime_persistence"] = {"runtime_persistence": False, "persistence_completed": False}
    return payload


__all__ = [
    "build_hybrid_search_health",
    "build_hybrid_search_runtime",
]
