from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.services.assistant_workspace_runtime import build_assistant_workspace_runtime
from app.services.document_workspace_runtime import build_document_workspace_runtime
from app.services.knowledge_workspace_runtime import build_knowledge_workspace_runtime
from app.services.platform_dashboard_runtime import build_platform_dashboard_runtime
from app.services.reference_tenant import build_reference_tenant_readiness
from app.services.runtime_composition import compose_runtime_dependency

SEARCH_DISCOVERY_RUNTIME_SCHEMA_VERSION = "1"
SEARCH_DISCOVERY_RUNTIME_NAME = "search_discovery_runtime"


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _listing(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _ratio(numerator: int, denominator: int) -> float:
    return float(numerator / denominator) if denominator else 0.0


def _workspace_summary(
    knowledge: dict[str, Any],
    documents: dict[str, Any],
    assistant: dict[str, Any],
    reference_tenant: dict[str, Any],
) -> dict[str, Any]:
    knowledge_summary = _mapping(knowledge.get("workspace_summary"))
    document_summary = _mapping(documents.get("workspace_summary"))
    assistant_summary = _mapping(assistant.get("workspace_summary"))
    chunk_overview = _mapping(knowledge.get("chunk_overview"))
    enterprise_search = _mapping(knowledge.get("enterprise_search"))
    search_ready = bool(enterprise_search.get("search_ready")) or bool(knowledge_summary.get("search_ready"))
    knowledge_ready = bool(knowledge_summary.get("knowledge_ready"))
    documents_ready = bool(document_summary.get("documents_ready"))
    citations_ready = bool(assistant_summary.get("citations_ready"))
    runtime_ready = (
        search_ready and knowledge_ready and documents_ready and int(chunk_overview.get("indexed_chunks") or 0) > 0
    )
    return {
        "runtime_status": "ready" if runtime_ready else "degraded",
        "search_ready": search_ready,
        "knowledge_ready": knowledge_ready,
        "documents_ready": documents_ready,
        "citations_ready": citations_ready,
        "evidence_ready": bool(chunk_overview.get("indexed_chunks")) and bool(knowledge.get("knowledge_documents")),
        "reference_tenant_search_ready": bool(reference_tenant.get("search_ready")),
        "reference_tenant_chat_ready": bool(reference_tenant.get("chat_ready")),
        "postgresql_source_of_truth": True,
        "ai_required": False,
        "llm_used": False,
        "qdrant_used": False,
    }


def _enterprise_search_summary(
    dashboard: dict[str, Any],
    knowledge: dict[str, Any],
    assistant: dict[str, Any],
) -> dict[str, Any]:
    enterprise_search = _mapping(knowledge.get("enterprise_search"))
    operational = _mapping(dashboard.get("operational_summary"))
    retrieval = _mapping(assistant.get("retrieval_and_citations"))
    return {
        "fts_ready": bool(enterprise_search.get("fts_ready")),
        "search_ready": bool(enterprise_search.get("search_ready")),
        "indexed_document_count": enterprise_search.get("indexed_document_count")
        or operational.get("indexed_documents")
        or 0,
        "searchable_chunk_count": enterprise_search.get("searchable_chunk_count") or 0,
        "assistant_enterprise_search_ready": bool(retrieval.get("enterprise_search_ready")),
        "postgresql_fts_source": True,
        "llm_used": False,
        "qdrant_used": False,
    }


def _knowledge_coverage(knowledge: dict[str, Any], documents: dict[str, Any]) -> dict[str, Any]:
    collections = _listing(knowledge.get("collections"))
    knowledge_documents = _listing(knowledge.get("knowledge_documents"))
    chunk_overview = _mapping(knowledge.get("chunk_overview"))
    document_registry = _listing(documents.get("document_registry"))
    document_versions = _listing(documents.get("versions"))
    total_documents = len(document_registry)
    indexed_documents = len(
        [
            document
            for document in knowledge_documents
            if _mapping(document.get("readiness")).get("searchable")
            or str(document.get("status") or "").lower() in {"indexed", "ready"}
        ]
    )
    total_chunks = int(chunk_overview.get("total_chunks") or 0)
    indexed_chunks = int(chunk_overview.get("indexed_chunks") or 0)
    return {
        "collection_count": len(collections),
        "document_count": total_documents,
        "document_version_count": len(document_versions),
        "knowledge_document_count": len(knowledge_documents),
        "total_chunks": total_chunks,
        "indexed_chunks": indexed_chunks,
        "document_coverage": _ratio(indexed_documents, total_documents),
        "chunk_coverage": _ratio(indexed_chunks, total_chunks),
        "coverage_ready": indexed_documents > 0 and indexed_chunks > 0,
    }


def _chunk_explorer(knowledge: dict[str, Any]) -> dict[str, Any]:
    overview = _mapping(knowledge.get("chunk_overview"))
    diagnostics = _mapping(overview.get("chunk_diagnostics"))
    return {
        "total_chunks": overview.get("total_chunks") or 0,
        "indexed_chunks": overview.get("indexed_chunks") or 0,
        "chunks_by_status": overview.get("chunks_by_status") or {},
        "sample_chunks": overview.get("sample_chunks") or [],
        "safe_sample_limit": diagnostics.get("safe_sample_limit"),
        "chunk_diagnostics": diagnostics,
    }


def _document_explorer(documents: dict[str, Any]) -> dict[str, Any]:
    registry = _listing(documents.get("document_registry"))
    versions = _listing(documents.get("versions"))
    return {
        "document_count": len(registry),
        "version_count": len(versions),
        "documents": registry,
        "versions": versions,
        "searchable_documents": len(
            [item for item in registry if bool(_mapping(item.get("readiness")).get("search_ready"))]
        ),
    }


def _search_explorer(
    knowledge: dict[str, Any],
    assistant: dict[str, Any],
    dashboard: dict[str, Any],
) -> dict[str, Any]:
    enterprise_search = _mapping(knowledge.get("enterprise_search"))
    retrieval_explorer = _mapping(assistant.get("retrieval_explorer"))
    operational = _mapping(dashboard.get("operational_summary"))
    return {
        "enterprise_search": enterprise_search,
        "assistant_retrieval": retrieval_explorer,
        "search_requests": operational.get("search_requests") or 0,
        "postgresql_fts_used": True,
        "semantic_search_required": False,
        "qdrant_used": False,
        "llm_used": False,
    }


def _search_diagnostics(
    knowledge: dict[str, Any],
    documents: dict[str, Any],
    assistant: dict[str, Any],
) -> dict[str, Any]:
    enterprise_search = _mapping(knowledge.get("enterprise_search"))
    knowledge_diagnostics = _mapping(knowledge.get("diagnostics"))
    document_diagnostics = _mapping(documents.get("diagnostics"))
    assistant_diagnostics = _mapping(assistant.get("diagnostics"))
    return {
        "enterprise_search_diagnostics": enterprise_search.get("search_diagnostics") or {},
        "knowledge_diagnostics": knowledge_diagnostics,
        "document_diagnostics": document_diagnostics,
        "assistant_search_diagnostics": assistant_diagnostics,
        "blocking_issues": [
            *_listing(knowledge_diagnostics.get("blocking_issues")),
            *_listing(document_diagnostics.get("blocking_issues")),
            *_listing(assistant_diagnostics.get("blocking_issues")),
        ],
        "degraded_items": [
            *_listing(knowledge_diagnostics.get("degraded_items")),
            *_listing(document_diagnostics.get("degraded_items")),
            *_listing(assistant_diagnostics.get("degraded_items")),
        ],
    }


def _coverage_diagnostics(coverage: dict[str, Any]) -> dict[str, Any]:
    warnings: list[dict[str, Any]] = []
    recommendations: list[dict[str, Any]] = []
    if not coverage.get("coverage_ready"):
        warnings.append({"code": "search_coverage_not_ready"})
        recommendations.append({"code": "publish_and_index_searchable_knowledge"})
    if float(coverage.get("document_coverage") or 0) < 1.0:
        recommendations.append({"code": "review_unindexed_documents"})
    return {
        "coverage_ready": bool(coverage.get("coverage_ready")),
        "document_coverage": coverage.get("document_coverage"),
        "chunk_coverage": coverage.get("chunk_coverage"),
        "warnings": warnings,
        "recommendations": recommendations,
    }


def _evidence_readiness(
    knowledge: dict[str, Any],
    assistant: dict[str, Any],
    reference_tenant: dict[str, Any],
) -> dict[str, Any]:
    chunk_overview = _mapping(knowledge.get("chunk_overview"))
    citations = _mapping(assistant.get("retrieval_and_citations"))
    return {
        "indexed_chunks_available": int(chunk_overview.get("indexed_chunks") or 0) > 0,
        "knowledge_documents_available": bool(_listing(knowledge.get("knowledge_documents"))),
        "citation_verification_ready": bool(citations.get("citation_verification_ready")),
        "citation_count": citations.get("citation_count") or 0,
        "evidence_count": citations.get("evidence_count") or 0,
        "reference_tenant_coverage_ready": bool(reference_tenant.get("knowledge_indexed"))
        and bool(reference_tenant.get("search_ready")),
        "evidence_ready": (
            int(chunk_overview.get("indexed_chunks") or 0) > 0 and bool(_listing(knowledge.get("knowledge_documents")))
        ),
    }


def _traceability(
    documents: dict[str, Any],
    knowledge: dict[str, Any],
    assistant: dict[str, Any],
) -> dict[str, Any]:
    document_explorer = _document_explorer(documents)
    runtime_trace = _mapping(assistant.get("runtime_trace"))
    return {
        "document_to_knowledge_trace_available": bool(_listing(knowledge.get("knowledge_documents"))),
        "document_lineage_count": document_explorer["version_count"],
        "knowledge_document_count": len(_listing(knowledge.get("knowledge_documents"))),
        "runtime_trace_available": bool(runtime_trace.get("runtime_trace_available")),
        "runtime_trace_count": runtime_trace.get("record_count") or 0,
    }


def _search_performance(assistant: dict[str, Any], dashboard: dict[str, Any]) -> dict[str, Any]:
    runtime_executions = _mapping(assistant.get("runtime_executions"))
    operational = _mapping(dashboard.get("operational_summary"))
    return {
        "search_requests": operational.get("search_requests") or 0,
        "assistant_search_executions": runtime_executions.get("enterprise_search_executions") or 0,
        "retrieval_executions": runtime_executions.get("retrieval_executions") or 0,
        "runtime_persistence_available": bool(runtime_executions.get("runtime_persistence_by_domain")),
    }


def _search_quality(coverage: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any]:
    score = int(
        round(
            (
                float(coverage.get("chunk_coverage") or 0)
                + float(coverage.get("document_coverage") or 0)
                + (1.0 if evidence.get("evidence_ready") else 0.0)
            )
            / 3
            * 100
        )
    )
    return {
        "quality_score": score,
        "coverage_ready": bool(coverage.get("coverage_ready")),
        "evidence_ready": bool(evidence.get("evidence_ready")),
        "citation_ready": bool(evidence.get("citation_verification_ready")),
        "search_quality_ready": score > 0 and bool(coverage.get("coverage_ready")),
    }


def _reference_tenant_coverage(reference_tenant: dict[str, Any]) -> dict[str, Any]:
    return {
        "reference_tenant_ready": bool(reference_tenant.get("reference_tenant_ready")),
        "reference_documents_count": reference_tenant.get("reference_documents_count") or 0,
        "reference_documents_ready": bool(reference_tenant.get("documents_ready"))
        and bool(reference_tenant.get("reference_content_provisioned")),
        "reference_knowledge_ready": bool(reference_tenant.get("knowledge_ready"))
        and bool(reference_tenant.get("knowledge_indexed")),
        "reference_search_ready": bool(reference_tenant.get("search_ready")),
        "reference_chat_ready": bool(reference_tenant.get("chat_ready")),
        "knowledge_indexed": bool(reference_tenant.get("knowledge_indexed")),
    }


def build_search_discovery_runtime(
    db: Session,
    *,
    source_runtimes: dict[str, dict[str, Any]] | None = None,
    organization_id: uuid.UUID | None = None,
    platform_scope: bool = True,
) -> dict[str, Any]:
    sources = source_runtimes or {}
    dependency_status: list[dict[str, Any]] = []
    dashboard = sources.get("dashboard") or (
        build_platform_dashboard_runtime(
            db,
            organization_id=organization_id,
            platform_scope=True,
        )
        if platform_scope
        else {}
    )
    if "knowledge" in sources:
        knowledge = sources["knowledge"]
    else:
        knowledge, dependency = compose_runtime_dependency(
            db,
            runtime=SEARCH_DISCOVERY_RUNTIME_NAME,
            organization_id=organization_id,
            dependency="knowledge_workspace",
            required=True,
            builder=lambda: build_knowledge_workspace_runtime(
                db,
                organization_id=organization_id,
                platform_scope=platform_scope,
                source_runtimes={"dashboard": dashboard} if dashboard else None,
            ),
            optional_default={},
        )
        dependency_status.append(dependency)
    if "documents" in sources:
        documents = sources["documents"]
    else:
        documents, dependency = compose_runtime_dependency(
            db,
            runtime=SEARCH_DISCOVERY_RUNTIME_NAME,
            organization_id=organization_id,
            dependency="document_workspace",
            required=False,
            builder=lambda: build_document_workspace_runtime(
                db,
                organization_id=organization_id,
                platform_scope=platform_scope,
                source_runtimes={
                    "knowledge": knowledge,
                    **({"dashboard": dashboard} if dashboard else {}),
                },
            ),
            optional_default={"runtime_status": "unavailable"},
        )
        dependency_status.append(dependency)
    if "assistants" in sources:
        assistant = sources["assistants"]
    else:
        assistant, dependency = compose_runtime_dependency(
            db,
            runtime=SEARCH_DISCOVERY_RUNTIME_NAME,
            organization_id=organization_id,
            dependency="assistant_workspace",
            required=False,
            builder=lambda: build_assistant_workspace_runtime(
                db,
                organization_id=organization_id,
                platform_scope=platform_scope,
                source_runtimes={"dashboard": dashboard} if dashboard else None,
            ),
            optional_default={"runtime_status": "unavailable"},
        )
        dependency_status.append(dependency)
    if "reference_readiness" in sources:
        reference_tenant = sources["reference_readiness"]
    elif platform_scope:
        reference_tenant = build_reference_tenant_readiness(db)
    else:
        reference_tenant = {}

    workspace_summary = _workspace_summary(knowledge, documents, assistant, reference_tenant)
    enterprise_search = _enterprise_search_summary(dashboard if platform_scope else {}, knowledge, assistant)
    coverage = _knowledge_coverage(knowledge, documents)
    chunk_explorer = _chunk_explorer(knowledge)
    document_explorer = _document_explorer(documents)
    citation_explorer = _mapping(assistant.get("citation_explorer"))
    search_explorer = _search_explorer(knowledge, assistant, dashboard)
    search_diagnostics = _search_diagnostics(knowledge, documents, assistant)
    search_diagnostics["dependencies"] = dependency_status
    coverage_diagnostics = _coverage_diagnostics(coverage)
    evidence = _evidence_readiness(knowledge, assistant, reference_tenant)
    traceability = _traceability(documents, knowledge, assistant)
    performance = _search_performance(assistant, dashboard)
    quality = _search_quality(coverage, evidence)
    reference_coverage = _reference_tenant_coverage(reference_tenant)
    warnings = [
        *_listing(search_diagnostics.get("warnings")),
        *_listing(coverage_diagnostics.get("warnings")),
    ]
    pending_capabilities = [
        *_listing(_mapping(knowledge.get("diagnostics")).get("pending_capabilities")),
        *_listing(_mapping(documents.get("diagnostics")).get("pending_capabilities")),
        *_listing(_mapping(assistant.get("diagnostics")).get("pending_capabilities")),
    ]
    recommendations = [
        *_listing(coverage_diagnostics.get("recommendations")),
        {"code": "review_search_quality"} if not quality["search_quality_ready"] else {},
    ]
    recommendations = [item for item in recommendations if item]
    runtime_ready = bool(workspace_summary.get("search_ready")) and bool(coverage.get("coverage_ready"))
    return {
        "search_discovery_runtime_schema_version": SEARCH_DISCOVERY_RUNTIME_SCHEMA_VERSION,
        "runtime_name": SEARCH_DISCOVERY_RUNTIME_NAME,
        "runtime_status": "ready" if runtime_ready else "degraded",
        "workspace_summary": workspace_summary,
        "enterprise_search_summary": enterprise_search,
        "knowledge_coverage": coverage,
        "knowledge_collections": _listing(knowledge.get("collections")),
        "knowledge_sources": _listing(knowledge.get("knowledge_sources")),
        "knowledge_documents": _listing(knowledge.get("knowledge_documents")),
        "knowledge_chunks": _mapping(knowledge.get("chunk_overview")),
        "chunk_explorer": chunk_explorer,
        "document_explorer": document_explorer,
        "citation_explorer": citation_explorer,
        "search_explorer": search_explorer,
        "search_diagnostics": search_diagnostics,
        "coverage_diagnostics": coverage_diagnostics,
        "evidence_readiness": evidence,
        "traceability": traceability,
        "search_performance": performance,
        "search_quality": quality,
        "reference_tenant_coverage": reference_coverage,
        "pending_capabilities": pending_capabilities,
        "warnings": warnings,
        "recommendations": recommendations,
        "postgresql_source_of_truth": True,
        "llm_used": False,
        "qdrant_used": False,
        "external_calls_performed": False,
        "side_effects_performed": False,
    }
