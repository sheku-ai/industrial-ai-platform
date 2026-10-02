from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.services.ai_studio_runtime import build_ai_studio_runtime
from app.services.assistant_workspace_runtime import build_assistant_workspace_runtime
from app.services.connector_workspace_runtime import build_connector_workspace_runtime
from app.services.document_workspace_runtime import build_document_workspace_runtime
from app.services.governance_center_runtime import build_governance_center_runtime
from app.services.knowledge_workspace_runtime import build_knowledge_workspace_runtime
from app.services.operations_center_runtime import build_operations_center_runtime
from app.services.platform_dashboard_runtime import build_platform_dashboard_runtime
from app.services.product_integration_runtime import build_product_integration_runtime
from app.services.reference_tenant import (
    build_reference_tenant_readiness,
    build_reference_tenant_status,
    validate_reference_tenant,
)
from app.services.runtime_composition import compose_runtime_dependency
from app.services.scheduler_background_services_runtime import build_scheduler_background_services_runtime
from app.services.search_discovery_runtime import build_search_discovery_runtime
from app.services.security_center_runtime import build_security_center_runtime
from app.services.workflow_studio_runtime import build_workflow_studio_runtime

REPORTING_ANALYTICS_RUNTIME_SCHEMA_VERSION = "1"
REPORTING_ANALYTICS_RUNTIME_NAME = "reporting_analytics_runtime"


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _listing(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _as_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _trend_snapshot(
    *,
    key: str,
    label: str,
    current: int | float | str | bool | None,
    previous: int | float | str | bool | None = None,
    warnings: list[dict[str, Any]] | None = None,
    recommendations: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    numeric = isinstance(current, int | float) and isinstance(previous, int | float)
    growth = (current - previous) if numeric else None
    if numeric and growth is not None:
        direction = "up" if growth > 0 else "down" if growth < 0 else "flat"
    else:
        direction = "snapshot_only"
    return {
        "key": key,
        "label": label,
        "current_snapshot": current,
        "historical_snapshot": previous,
        "trend_direction": direction,
        "growth": growth,
        "warnings": warnings or [],
        "recommendations": recommendations or [],
    }


def _platform_summary(dashboard: dict[str, Any], product: dict[str, Any]) -> dict[str, Any]:
    platform = _mapping(dashboard.get("platform_summary"))
    overall = _mapping(product.get("overall"))
    return {
        "platform_version": platform.get("platform_version"),
        "edition": platform.get("edition"),
        "runtime_status": dashboard.get("runtime_status"),
        "product_baseline_status": platform.get("product_baseline_status"),
        "integration_ready": overall.get("integration_ready"),
        "production_candidate": overall.get("production_candidate"),
        "postgresql_source_of_truth": True,
        "ai_required": False,
        "llm_used": False,
        "qdrant_used": False,
    }


def _executive_kpis(
    operations: dict[str, Any],
    scheduler: dict[str, Any],
    workflow: dict[str, Any],
    connector: dict[str, Any],
    governance: dict[str, Any],
    reference: dict[str, Any],
) -> dict[str, Any]:
    documents = _mapping(operations.get("document_lifecycle_operations"))
    knowledge = _mapping(operations.get("knowledge_operations"))
    search = _mapping(operations.get("enterprise_search_operations"))
    assistant = _mapping(operations.get("assistant_operations"))
    runtime = _mapping(operations.get("runtime_persistence"))
    feedback_audit = _mapping(operations.get("feedback_audit_operations"))
    scheduler_summary = _mapping(scheduler.get("scheduler_summary"))
    return {
        "registered_documents": _as_int(documents.get("registered_documents")),
        "knowledge_documents": _as_int(knowledge.get("knowledge_documents")),
        "knowledge_chunks": _as_int(knowledge.get("knowledge_chunks")),
        "indexed_documents": _as_int(knowledge.get("indexed_documents")),
        "indexed_chunks": _as_int(knowledge.get("indexed_chunks")),
        "search_requests": _as_int(search.get("search_requests")),
        "assistant_requests": _as_int(assistant.get("assistant_runtime_executions")),
        "conversation_count": _as_int(assistant.get("conversation_count")),
        "connector_count": _as_int(_mapping(connector.get("workspace_summary")).get("connector_count"))
        or _as_int(_mapping(operations.get("connector_operations")).get("connector_count")),
        "scheduler_jobs": _as_int(scheduler_summary.get("job_count")),
        "background_services": len(_listing(scheduler.get("background_services"))),
        "workflow_count": _as_int(_mapping(workflow.get("workflow_readiness")).get("workflow_count")),
        "runtime_executions": _as_int(runtime.get("total_runtime_records")),
        "feedback_count": _as_int(feedback_audit.get("feedback_count"))
        or _as_int(_mapping(governance.get("feedback_governance")).get("feedback_count")),
        "audit_events": _as_int(feedback_audit.get("audit_event_count"))
        or _as_int(_mapping(governance.get("audit_governance")).get("audit_event_count")),
        "reference_tenant_status": "ready" if reference.get("reference_tenant_ready") else "degraded",
    }


def _document_analytics(document: dict[str, Any], operations: dict[str, Any]) -> dict[str, Any]:
    summary = _mapping(document.get("workspace_summary"))
    lifecycle = _mapping(operations.get("document_lifecycle_operations"))
    return {
        "summary": summary,
        "registered_documents": lifecycle.get("registered_documents"),
        "document_versions": lifecycle.get("total_document_versions"),
        "storage_verified": lifecycle.get("storage_verified"),
        "processed_documents": lifecycle.get("processing_completed"),
        "processing_measurement": lifecycle.get("processing_measurement") or {},
        "chunks_created": lifecycle.get("chunks_created"),
        "failed_lifecycles": lifecycle.get("failed_lifecycles"),
        "pending_lifecycles": lifecycle.get("pending_lifecycles"),
        "recent_activity": lifecycle.get("recent_lifecycles") or [],
    }


def _knowledge_analytics(knowledge: dict[str, Any], operations: dict[str, Any]) -> dict[str, Any]:
    ops = _mapping(operations.get("knowledge_operations"))
    return {
        "summary": _mapping(knowledge.get("workspace_summary")),
        "collections": knowledge.get("collections") or [],
        "knowledge_documents": ops.get("knowledge_documents"),
        "knowledge_chunks": ops.get("knowledge_chunks"),
        "indexed_documents": ops.get("indexed_documents"),
        "indexed_chunks": ops.get("indexed_chunks"),
        "publication_completed": ops.get("publication_completed"),
        "publication_failed": ops.get("publication_failed"),
        "indexing_pending": ops.get("indexing_pending"),
        "indexing_failed": ops.get("indexing_failed"),
        "chunk_overview": knowledge.get("chunk_overview") or {},
    }


def _search_analytics(search_discovery: dict[str, Any], operations: dict[str, Any]) -> dict[str, Any]:
    search = _mapping(operations.get("enterprise_search_operations"))
    return {
        "summary": search_discovery.get("workspace_summary") or {},
        "enterprise_search_summary": search_discovery.get("enterprise_search_summary") or {},
        "search_requests": search.get("search_requests"),
        "successful_searches": search.get("successful_searches"),
        "failed_searches": search.get("failed_searches"),
        "search_ready": search.get("search_ready"),
        "search_result_coverage": search.get("search_result_coverage"),
        "search_coverage_measurement": search.get("search_coverage_measurement") or {},
        "search_quality": search_discovery.get("search_quality") or {},
        "search_diagnostics": search_discovery.get("search_diagnostics") or {},
    }


def _assistant_analytics(
    assistant: dict[str, Any],
    operations: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    ops = _mapping(operations.get("assistant_operations"))
    assistant_analytics = {
        "summary": assistant.get("workspace_summary") or {},
        "assistant_definitions": assistant.get("assistant_definitions") or [],
        "assistant_sessions": ops.get("assistant_sessions"),
        "assistant_runtime_executions": ops.get("assistant_runtime_executions"),
        "context_builder_executions": ops.get("context_builder_executions"),
        "prompt_assembly_executions": ops.get("prompt_assembly_executions"),
        "llm_gateway_executions": ops.get("llm_gateway_executions"),
        "citation_verification_executions": ops.get("citation_verification_executions"),
        "assistant_response_executions": ops.get("assistant_response_executions"),
        "recent_activity": ops.get("recent_assistant_activity") or [],
    }
    conversation_analytics = {
        "conversation_count": ops.get("conversation_count"),
        "turn_count": ops.get("turn_count"),
        "conversations": assistant.get("conversations") or [],
        "turns": assistant.get("conversation_turns") or [],
    }
    return assistant_analytics, conversation_analytics


def _workflow_analytics(workflow: dict[str, Any]) -> dict[str, Any]:
    return {
        "summary": workflow.get("workspace_summary") or {},
        "readiness": workflow.get("workflow_readiness") or {},
        "inventory": workflow.get("workflow_inventory") or [],
        "categories": workflow.get("workflow_categories") or {},
        "diagnostics": workflow.get("workflow_diagnostics") or {},
    }


def _scheduler_analytics(scheduler: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    scheduler_summary = _mapping(scheduler.get("scheduler_summary"))
    background = {
        "summary": scheduler.get("workspace_summary") or {},
        "services": scheduler.get("background_services") or [],
        "worker_health": scheduler.get("worker_health") or {},
        "lease_diagnostics": scheduler.get("lease_diagnostics") or {},
        "retry_engine": scheduler.get("retry_engine") or {},
        "pipeline_health": scheduler.get("pipeline_health") or {},
    }
    return scheduler_summary, background


def _connector_analytics(connector: dict[str, Any], operations: dict[str, Any]) -> dict[str, Any]:
    connector_ops = _mapping(operations.get("connector_operations"))
    return {
        "summary": connector.get("workspace_summary") or {},
        "connector_count": connector_ops.get("connector_count"),
        "configured_connectors": connector_ops.get("configured_connectors"),
        "connector_runs": connector_ops.get("connector_runs"),
        "successful_connector_runs": connector_ops.get("successful_connector_runs"),
        "failed_connector_runs": connector_ops.get("failed_connector_runs"),
        "pending_connector_runs": connector_ops.get("pending_connector_runs"),
        "recent_connector_runs": connector_ops.get("recent_connector_runs") or [],
    }


def _security_analytics(security: dict[str, Any]) -> dict[str, Any]:
    return {
        "summary": security.get("workspace_summary") or {},
        "roles": security.get("roles") or {},
        "permissions": security.get("permissions") or {},
        "policies": security.get("policies") or {},
        "role_assignments": security.get("role_assignments") or {},
        "effective_permissions": security.get("effective_permissions") or {},
        "access_diagnostics": security.get("access_diagnostics") or {},
    }


def _governance_analytics(governance: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    audit = _mapping(governance.get("audit_governance"))
    feedback = _mapping(governance.get("feedback_governance"))
    governance_analytics = {
        "summary": governance.get("workspace_summary") or {},
        "compliance_readiness": governance.get("compliance_readiness") or {},
        "classification_governance": governance.get("classification_governance") or {},
        "retention_governance": governance.get("retention_governance") or {},
        "policy_governance": governance.get("policy_governance") or {},
    }
    return governance_analytics, audit, feedback


def _reference_tenant_analytics(reference: dict[str, Any], reference_status: dict[str, Any]) -> dict[str, Any]:
    return {
        "reference_tenant_ready": reference.get("reference_tenant_ready"),
        "reference_tenant_status": "ready" if reference.get("reference_tenant_ready") else "degraded",
        "organization_ready": reference.get("organization_ready"),
        "documents_ready": reference.get("documents_ready"),
        "knowledge_ready": reference.get("knowledge_ready"),
        "search_ready": reference.get("search_ready"),
        "assistant_ready": reference.get("assistant_ready"),
        "chat_ready": reference.get("chat_ready"),
        "reference_documents_count": reference.get("reference_documents_count"),
        "domain_results": reference.get("domain_results") or {},
        "status": reference_status,
        "blocking_issues": reference.get("blocking_issues") or [],
        "warnings": reference.get("warnings") or [],
    }


def _readiness_scores(
    product: dict[str, Any],
    operations: dict[str, Any],
    knowledge: dict[str, Any],
    assistant: dict[str, Any],
    security: dict[str, Any],
    workflow: dict[str, Any],
    scheduler: dict[str, Any],
    governance: dict[str, Any],
) -> dict[str, Any]:
    product_score = _mapping(product.get("product_score"))
    product_overall = _mapping(product.get("overall"))
    operation_summary = _mapping(operations.get("workspace_summary"))
    scheduler_readiness = _mapping(scheduler.get("runtime_readiness"))
    return {
        "overall_product_score": _as_float(product_score.get("overall_score"))
        or _as_float(product_overall.get("integration_score")),
        "operational_score": 100.0 if operation_summary.get("operations_ready") else 0.0,
        "knowledge_score": 100.0 if _mapping(knowledge.get("workspace_summary")).get("knowledge_ready") else 0.0,
        "assistant_score": 100.0 if _mapping(assistant.get("workspace_summary")).get("assistants_ready") else 0.0,
        "security_score": 100.0 if _mapping(security.get("workspace_summary")).get("security_ready") else 0.0,
        "workflow_score": _as_float(_mapping(workflow.get("workflow_readiness")).get("workflow_score")),
        "scheduler_score": _as_float(scheduler_readiness.get("readiness_score")),
        "governance_score": 100.0 if _mapping(governance.get("workspace_summary")).get("governance_ready") else 0.0,
    }


def _trend_sections(
    kpis: dict[str, Any],
    readiness: dict[str, Any],
    scheduler: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    product_trends = {
        "current_snapshot_at": datetime.now(UTC),
        "historical_snapshot_available": False,
        "items": [
            _trend_snapshot(
                key="overall_product_score",
                label="Overall product score",
                current=readiness.get("overall_product_score"),
            ),
            _trend_snapshot(
                key="reference_tenant_status",
                label="Reference tenant status",
                current=kpis.get("reference_tenant_status"),
            ),
        ],
    }
    runtime_trends = {
        "current_snapshot_at": datetime.now(UTC),
        "historical_snapshot_available": False,
        "items": [
            _trend_snapshot(
                key="runtime_executions",
                label="Runtime executions",
                current=kpis.get("runtime_executions"),
            ),
            _trend_snapshot(key="workflow_count", label="Workflow count", current=kpis.get("workflow_count")),
        ],
    }
    operational_trends = {
        "current_snapshot_at": datetime.now(UTC),
        "historical_snapshot_available": False,
        "items": [
            _trend_snapshot(
                key="registered_documents",
                label="Registered documents",
                current=kpis.get("registered_documents"),
            ),
            _trend_snapshot(
                key="indexed_chunks",
                label="Indexed chunks",
                current=kpis.get("indexed_chunks"),
            ),
            _trend_snapshot(
                key="scheduler_jobs",
                label="Scheduler jobs",
                current=kpis.get("scheduler_jobs"),
                warnings=scheduler.get("warnings") or [],
            ),
        ],
    }
    return product_trends, runtime_trends, operational_trends


def _diagnostics(
    dashboard: dict[str, Any],
    product: dict[str, Any],
    scheduler: dict[str, Any],
    workflow: dict[str, Any],
    governance: dict[str, Any],
    security: dict[str, Any],
) -> dict[str, Any]:
    product_diagnostics = _mapping(product.get("diagnostics"))
    return {
        "blocking_issues": _listing(product_diagnostics.get("blocking_issues")),
        "warnings": [
            *_listing(_mapping(dashboard.get("alerts_and_diagnostics")).get("warnings")),
            *_listing(scheduler.get("warnings")),
            *_listing(workflow.get("warnings")),
            *_listing(_mapping(governance.get("diagnostics")).get("warnings")),
            *_listing(security.get("warnings")),
        ],
        "pending_capabilities": [
            *_listing(product_diagnostics.get("pending_capabilities")),
            *_listing(scheduler.get("pending_capabilities")),
            *_listing(workflow.get("pending_capabilities")),
        ],
        "degraded_domains": _listing(_mapping(dashboard.get("alerts_and_diagnostics")).get("degraded_domains")),
    }


def _recommendations(
    diagnostics: dict[str, Any],
    scheduler: dict[str, Any],
    workflow: dict[str, Any],
    search: dict[str, Any],
) -> list[dict[str, Any]]:
    recommendations = []
    recommendations.extend(_listing(scheduler.get("runtime_recommendations")))
    recommendations.extend(_listing(workflow.get("workflow_recommendations")))
    recommendations.extend(_listing(search.get("recommendations")))
    if diagnostics.get("blocking_issues"):
        recommendations.append({"code": "review_blocking_issues", "label": "Review product blocking issues"})
    if diagnostics.get("pending_capabilities"):
        recommendations.append({"code": "review_pending_capabilities", "label": "Review pending capabilities"})
    if not recommendations:
        recommendations.append({"code": "monitor_platform_analytics", "label": "Monitor platform analytics snapshots"})
    return recommendations


def build_reporting_analytics_runtime(
    db: Session,
    *,
    organization_id: uuid.UUID | None = None,
    platform_scope: bool = True,
) -> dict[str, Any]:
    dependency_status: list[dict[str, Any]] = []
    dashboard, dependency = compose_runtime_dependency(
        db,
        runtime=REPORTING_ANALYTICS_RUNTIME_NAME,
        organization_id=organization_id,
        dependency="platform_dashboard",
        required=True,
        builder=lambda: build_platform_dashboard_runtime(
            db,
            organization_id=organization_id,
            platform_scope=platform_scope,
        ),
        optional_default={},
    )
    dependency_status.append(dependency)
    operations = build_operations_center_runtime(db) if platform_scope else {}
    scheduler = build_scheduler_background_services_runtime(db) if platform_scope else {}
    workflow = build_workflow_studio_runtime(db) if platform_scope else {}
    knowledge, dependency = compose_runtime_dependency(
        db,
        runtime=REPORTING_ANALYTICS_RUNTIME_NAME,
        organization_id=organization_id,
        dependency="knowledge_workspace",
        required=True,
        builder=lambda: build_knowledge_workspace_runtime(
            db,
            organization_id=organization_id,
            platform_scope=platform_scope,
            source_runtimes={"dashboard": dashboard},
        ),
        optional_default={},
    )
    dependency_status.append(dependency)
    document, dependency = compose_runtime_dependency(
        db,
        runtime=REPORTING_ANALYTICS_RUNTIME_NAME,
        organization_id=organization_id,
        dependency="document_workspace",
        required=True,
        builder=lambda: build_document_workspace_runtime(
            db,
            organization_id=organization_id,
            platform_scope=platform_scope,
            source_runtimes={"dashboard": dashboard, "knowledge": knowledge},
        ),
        optional_default={},
    )
    dependency_status.append(dependency)
    assistant, dependency = compose_runtime_dependency(
        db,
        runtime=REPORTING_ANALYTICS_RUNTIME_NAME,
        organization_id=organization_id,
        dependency="assistant_workspace",
        required=False,
        builder=lambda: build_assistant_workspace_runtime(
            db,
            organization_id=organization_id,
            platform_scope=platform_scope,
            source_runtimes={"dashboard": dashboard},
        ),
        optional_default={"runtime_status": "unavailable"},
    )
    dependency_status.append(dependency)
    ai_studio, dependency = compose_runtime_dependency(
        db,
        runtime=REPORTING_ANALYTICS_RUNTIME_NAME,
        organization_id=organization_id,
        dependency="ai_studio",
        required=False,
        builder=lambda: build_ai_studio_runtime(
            db,
            organization_id=organization_id,
            platform_scope=platform_scope,
        ),
        optional_default={"runtime_status": "optional_not_configured"},
    )
    dependency_status.append(dependency)
    models = {"runtime_status": ai_studio.get("runtime_status")}
    connector, dependency = compose_runtime_dependency(
        db,
        runtime=REPORTING_ANALYTICS_RUNTIME_NAME,
        organization_id=organization_id,
        dependency="connector_workspace",
        required=False,
        builder=lambda: build_connector_workspace_runtime(
            db,
            organization_id=organization_id,
            platform_scope=platform_scope,
        ),
        optional_default={"runtime_status": "optional_not_configured"},
    )
    dependency_status.append(dependency)
    governance = build_governance_center_runtime(db) if platform_scope else {}
    security, dependency = compose_runtime_dependency(
        db,
        runtime=REPORTING_ANALYTICS_RUNTIME_NAME,
        organization_id=organization_id,
        dependency="security_center",
        required=False,
        builder=lambda: build_security_center_runtime(
            db,
            organization_id=organization_id,
            platform_scope=platform_scope,
        ),
        optional_default={"runtime_status": "unavailable"},
    )
    dependency_status.append(dependency)
    reference = build_reference_tenant_readiness(db) if platform_scope else {}
    reference_validation = validate_reference_tenant(db) if platform_scope else {}
    reference_status = build_reference_tenant_status(db) if platform_scope else {}
    search = build_search_discovery_runtime(
        db,
        source_runtimes={
            "dashboard": dashboard,
            "knowledge": knowledge,
            "documents": document,
            "assistants": assistant,
            "reference_readiness": reference,
        },
        organization_id=organization_id,
        platform_scope=platform_scope,
    )
    product = build_product_integration_runtime(
        db,
        source_runtimes={
            "dashboard": dashboard,
            "administration": {},
            "operations": operations,
            "governance": governance,
            "documents": document,
            "knowledge": knowledge,
            "assistants": assistant,
            "connectors": connector,
            "ai_studio": ai_studio,
            "reference_readiness": reference,
            "reference_validation": reference_validation,
            "reference_status": reference_status,
        },
    )

    platform = _platform_summary(dashboard, product)
    kpis = _executive_kpis(operations, scheduler, workflow, connector, governance, reference)
    dashboard_search = _mapping(_mapping(dashboard.get("dashboard_sections")).get("enterprise_search"))
    chunk_overview = _mapping(knowledge.get("chunk_overview"))
    assistant_runs = _mapping(assistant.get("runtime_executions"))
    kpis.update(
        {
            "registered_documents": len(_listing(document.get("document_registry"))),
            "knowledge_documents": len(_listing(knowledge.get("knowledge_documents"))),
            "knowledge_chunks": _as_int(chunk_overview.get("total_chunks")),
            "indexed_documents": len(
                [
                    item
                    for item in _listing(knowledge.get("knowledge_documents"))
                    if item.get("status") == "indexed"
                ]
            ),
            "indexed_chunks": _as_int(chunk_overview.get("indexed_chunks")),
            "search_requests": _as_int(dashboard_search.get("search_requests")),
            "assistant_requests": _as_int(assistant_runs.get("assistant_runtime_executions")),
            "conversation_count": len(_listing(assistant.get("conversations"))),
            "connector_count": len(_listing(connector.get("connectors"))),
        }
    )
    assistant_analytics, conversation_analytics = _assistant_analytics(assistant, operations)
    scheduler_analytics, background_analytics = _scheduler_analytics(scheduler)
    governance_analytics, audit_analytics, feedback_analytics = _governance_analytics(governance)
    readiness = _readiness_scores(product, operations, knowledge, assistant, security, workflow, scheduler, governance)
    product_trends, runtime_trends, operational_trends = _trend_sections(kpis, readiness, scheduler)
    diagnostics = _diagnostics(dashboard, product, scheduler, workflow, governance, security)
    diagnostics["dependencies"] = dependency_status
    diagnostics["warnings"] = [
        *_listing(diagnostics.get("warnings")),
        *[
            {
                "code": "optional_analytics_dependency_unavailable",
                "dependency": item["dependency"],
                "error_type": item.get("error_type"),
            }
            for item in dependency_status
            if not item["required"] and item["status"] == "unavailable"
        ],
    ]
    recommendations = _recommendations(diagnostics, scheduler, workflow, search)
    runtime_status = "ready" if not diagnostics.get("blocking_issues") else "degraded"

    return {
        "reporting_analytics_runtime_schema_version": REPORTING_ANALYTICS_RUNTIME_SCHEMA_VERSION,
        "runtime_name": REPORTING_ANALYTICS_RUNTIME_NAME,
        "runtime_status": runtime_status,
        "workspace_summary": {
            "runtime_status": runtime_status,
            "analytics_ready": True,
            "overall_product_score": readiness.get("overall_product_score"),
            "executive_kpis_ready": bool(kpis),
            "trend_sections_ready": True,
            "postgresql_source_of_truth": True,
            "side_effects_performed": False,
            "external_calls_performed": False,
            "llm_used": False,
            "qdrant_used": False,
            "metric_scope": "platform" if platform_scope else "selected_organization",
            "included_data_origins": ["operational", "reference"],
            "period": "all_time",
        },
        "platform_summary": platform,
        "executive_kpis": kpis,
        "document_analytics": _document_analytics(document, operations),
        "knowledge_analytics": _knowledge_analytics(knowledge, operations),
        "enterprise_search_analytics": _search_analytics(search, operations),
        "assistant_analytics": assistant_analytics,
        "conversation_analytics": conversation_analytics,
        "workflow_analytics": _workflow_analytics(workflow),
        "scheduler_analytics": scheduler_analytics,
        "background_services_analytics": background_analytics,
        "connector_analytics": _connector_analytics(connector, operations),
        "security_analytics": _security_analytics(security),
        "governance_analytics": governance_analytics,
        "audit_analytics": audit_analytics,
        "feedback_analytics": feedback_analytics,
        "reference_tenant_analytics": _reference_tenant_analytics(reference, reference_status),
        "product_readiness_trends": product_trends,
        "runtime_health_trends": runtime_trends,
        "operational_trends": operational_trends,
        "readiness_scores": readiness,
        "diagnostics": diagnostics,
        "recommendations": recommendations,
        "warnings": diagnostics.get("warnings") or [],
        "postgresql_source_of_truth": True,
        "side_effects_performed": False,
        "external_calls_performed": False,
        "llm_used": False,
        "qdrant_used": False,
        "source_runtimes": {
            "platform_dashboard": dashboard.get("runtime_status"),
            "operations_center": operations.get("runtime_status"),
            "scheduler_background_services": scheduler.get("runtime_status"),
            "workflow_studio": workflow.get("runtime_status"),
            "knowledge_workspace": knowledge.get("runtime_status"),
            "document_workspace": document.get("runtime_status"),
            "search_discovery": search.get("runtime_status"),
            "assistant_workspace": assistant.get("runtime_status"),
            "ai_studio": ai_studio.get("runtime_status"),
            "model_provider_center": models.get("runtime_status"),
            "connector_workspace": connector.get("runtime_status"),
            "governance_center": governance.get("runtime_status"),
            "security_center": security.get("runtime_status"),
            "product_integration": product.get("runtime_status"),
        },
    }
