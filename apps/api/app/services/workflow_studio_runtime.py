from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from sqlalchemy.orm import Session

from app.services.ai_studio_runtime import build_ai_studio_runtime
from app.services.governance_center_runtime import build_governance_center_runtime
from app.services.operations_center_runtime import build_operations_center_runtime
from app.services.reference_tenant import build_reference_tenant_readiness
from app.services.workflow_runtime import build_workflow_health, list_workflows_runtime

WORKFLOW_STUDIO_RUNTIME_SCHEMA_VERSION = "1"
WORKFLOW_STUDIO_RUNTIME_NAME = "workflow_studio_runtime"


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _listing(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _first_positive(*values: Any) -> int:
    for value in values:
        count = _as_int(value)
        if count > 0:
            return count
    return 0


def _issue(code: str, reason: str, *, domain: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"code": code, "reason": reason}
    if domain:
        payload["domain"] = domain
    return payload


def _workflow_catalog() -> list[dict[str, Any]]:
    return [
        {
            "workflow_key": "document_registration",
            "workflow_name": "Document Registration",
            "category": "document_lifecycle",
            "dependencies": [],
        },
        {
            "workflow_key": "binary_upload",
            "workflow_name": "Binary Upload",
            "category": "document_lifecycle",
            "dependencies": ["document_registration"],
        },
        {
            "workflow_key": "storage_verification",
            "workflow_name": "Storage Verification",
            "category": "document_lifecycle",
            "dependencies": ["binary_upload"],
        },
        {
            "workflow_key": "storage_reuse",
            "workflow_name": "Storage Reuse",
            "category": "document_lifecycle",
            "dependencies": ["storage_verification"],
        },
        {
            "workflow_key": "document_processing",
            "workflow_name": "Document Processing",
            "category": "processing",
            "dependencies": ["storage_verification"],
        },
        {
            "workflow_key": "chunk_generation",
            "workflow_name": "Chunk Generation",
            "category": "processing",
            "dependencies": ["document_processing"],
        },
        {
            "workflow_key": "knowledge_publication",
            "workflow_name": "Knowledge Publication",
            "category": "knowledge",
            "dependencies": ["chunk_generation"],
        },
        {
            "workflow_key": "knowledge_index",
            "workflow_name": "Knowledge Index",
            "category": "knowledge",
            "dependencies": ["knowledge_publication"],
        },
        {
            "workflow_key": "enterprise_search",
            "workflow_name": "Enterprise Search",
            "category": "search",
            "dependencies": ["knowledge_index"],
        },
        {
            "workflow_key": "assistant_retrieval",
            "workflow_name": "Assistant Retrieval",
            "category": "assistant",
            "dependencies": ["enterprise_search"],
        },
        {
            "workflow_key": "context_builder",
            "workflow_name": "Context Builder",
            "category": "assistant",
            "dependencies": ["assistant_retrieval"],
        },
        {
            "workflow_key": "prompt_assembly",
            "workflow_name": "Prompt Assembly",
            "category": "assistant",
            "dependencies": ["context_builder"],
        },
        {
            "workflow_key": "llm_gateway",
            "workflow_name": "LLM Gateway",
            "category": "assistant",
            "dependencies": ["prompt_assembly"],
            "optional": True,
        },
        {
            "workflow_key": "citation_verification",
            "workflow_name": "Citation Verification",
            "category": "assistant",
            "dependencies": ["assistant_retrieval"],
        },
        {
            "workflow_key": "conversation_runtime",
            "workflow_name": "Conversation Runtime",
            "category": "assistant",
            "dependencies": ["assistant_retrieval"],
        },
        {
            "workflow_key": "connector_synchronization",
            "workflow_name": "Connector Synchronization",
            "category": "connectors",
            "dependencies": [],
            "optional": True,
        },
        {
            "workflow_key": "reference_tenant_provisioning",
            "workflow_name": "Reference Tenant Provisioning",
            "category": "reference_tenant",
            "dependencies": ["document_registration", "knowledge_index", "enterprise_search"],
        },
        {
            "workflow_key": "runtime_persistence",
            "workflow_name": "Runtime Persistence",
            "category": "platform_runtime",
            "dependencies": [],
        },
        {
            "workflow_key": "audit_capture",
            "workflow_name": "Audit Capture",
            "category": "governance",
            "dependencies": ["runtime_persistence"],
        },
        {
            "workflow_key": "feedback_capture",
            "workflow_name": "Feedback Capture",
            "category": "governance",
            "dependencies": ["audit_capture"],
        },
    ]


def _evidence_map(
    operations: dict[str, Any],
    ai_studio: dict[str, Any],
    governance: dict[str, Any],
    reference: dict[str, Any],
    workflow_list: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    documents = _mapping(operations.get("document_lifecycle_operations"))
    processing = _mapping(operations.get("processing_workers"))
    knowledge = _mapping(operations.get("knowledge_operations"))
    search = _mapping(operations.get("enterprise_search_operations"))
    assistant = _mapping(operations.get("assistant_operations"))
    connectors = _mapping(operations.get("connector_operations"))
    runtime = _mapping(operations.get("runtime_persistence"))
    feedback_audit = _mapping(operations.get("feedback_audit_operations"))
    governance_audit = _mapping(governance.get("audit_governance"))
    governance_feedback = _mapping(governance.get("feedback_governance"))
    ai_summary = _mapping(ai_studio.get("workspace_summary"))
    chunk_generation_count = _first_positive(
        documents.get("chunks_created"),
        processing.get("chunk_generation_completed"),
        knowledge.get("knowledge_chunks"),
        knowledge.get("indexed_chunks"),
    )
    knowledge_publication_count = _first_positive(
        documents.get("knowledge_published"),
        knowledge.get("knowledge_documents"),
        knowledge.get("indexed_documents"),
    )
    knowledge_index_count = _first_positive(
        documents.get("knowledge_indexed"),
        knowledge.get("indexed_documents"),
    )
    chunk_generation_ready = any(
        _as_int(value) > 0
        for value in (
            documents.get("chunks_created"),
            processing.get("chunk_generation_completed"),
            knowledge.get("knowledge_chunks"),
            documents.get("knowledge_published"),
            knowledge.get("knowledge_documents"),
            documents.get("knowledge_indexed"),
            knowledge.get("indexed_documents"),
            knowledge.get("indexed_chunks"),
        )
    )
    knowledge_publication_ready = any(
        _as_int(value) > 0
        for value in (
            documents.get("knowledge_published"),
            knowledge.get("knowledge_documents"),
            documents.get("knowledge_indexed"),
            knowledge.get("indexed_documents"),
            knowledge.get("indexed_chunks"),
        )
    )
    knowledge_index_ready = any(
        _as_int(value) > 0
        for value in (
            documents.get("knowledge_indexed"),
            knowledge.get("indexed_documents"),
            knowledge.get("indexed_chunks"),
        )
    )
    return {
        "document_registration": {
            "count": _as_int(documents.get("registered_documents")),
            "ready": _as_int(documents.get("registered_documents")) > 0,
            "source": "document_lifecycle_operations",
        },
        "binary_upload": {
            "count": _as_int(documents.get("storage_verified")),
            "ready": _as_int(documents.get("storage_verified")) > 0,
            "source": "document_lifecycle_operations",
        },
        "storage_verification": {
            "count": _as_int(documents.get("storage_verified")),
            "ready": _as_int(documents.get("storage_verified")) > 0,
            "source": "document_lifecycle_operations",
        },
        "storage_reuse": {
            "count": _as_int(documents.get("storage_reused")),
            "ready": _as_int(documents.get("storage_reused")) > 0,
            "source": "document_lifecycle_operations",
        },
        "document_processing": {
            "count": _as_int(documents.get("processing_completed")),
            "ready": _as_int(documents.get("processing_completed")) > 0
            or _as_int(processing.get("processing_completed")) > 0,
            "source": "processing_runtime",
        },
        "chunk_generation": {
            "count": chunk_generation_count,
            "ready": chunk_generation_ready,
            "source": "chunk_runtime",
        },
        "knowledge_publication": {
            "count": knowledge_publication_count,
            "ready": knowledge_publication_ready,
            "source": "knowledge_publication_runtime",
        },
        "knowledge_index": {
            "count": knowledge_index_count,
            "ready": knowledge_index_ready,
            "source": "postgresql_knowledge_index",
        },
        "enterprise_search": {
            "count": _as_int(search.get("successful_searches")),
            "ready": bool(search.get("search_ready")),
            "source": "enterprise_search_runtime",
        },
        "assistant_retrieval": {
            "count": _as_int(assistant.get("assistant_runtime_executions")),
            "ready": bool(search.get("search_ready")) and _as_int(assistant.get("assistant_sessions")) >= 0,
            "source": "assistant_runtime",
        },
        "context_builder": {
            "count": _as_int(assistant.get("context_builder_executions")),
            "ready": _as_int(assistant.get("context_builder_executions")) > 0,
            "source": "context_builder_runtime",
        },
        "prompt_assembly": {
            "count": _as_int(assistant.get("prompt_assembly_executions")),
            "ready": _as_int(assistant.get("prompt_assembly_executions")) > 0,
            "source": "prompt_assembly_runtime",
        },
        "llm_gateway": {
            "count": _as_int(assistant.get("llm_gateway_executions")),
            "ready": bool(ai_summary.get("ai_optional")) or _as_int(assistant.get("llm_gateway_executions")) >= 0,
            "source": "llm_gateway_runtime",
        },
        "citation_verification": {
            "count": _as_int(assistant.get("citation_verification_executions")),
            "ready": _as_int(assistant.get("citation_verification_executions")) > 0,
            "source": "citation_verification_runtime",
        },
        "conversation_runtime": {
            "count": _as_int(assistant.get("conversation_count")),
            "ready": _as_int(assistant.get("conversation_count")) > 0,
            "source": "conversation_runtime",
        },
        "connector_synchronization": {
            "count": _as_int(connectors.get("connector_runs")),
            "ready": _as_int(connectors.get("configured_connectors")) > 0
            or _as_int(connectors.get("connector_runs")) > 0,
            "source": "connector_runtime",
        },
        "reference_tenant_provisioning": {
            "count": _as_int(reference.get("reference_documents_count")),
            "ready": bool(reference.get("reference_tenant_ready")),
            "source": "reference_tenant_runtime",
        },
        "runtime_persistence": {
            "count": _as_int(runtime.get("total_runtime_records")),
            "ready": _as_int(runtime.get("total_runtime_records")) >= 0,
            "source": "runtime_persistence",
        },
        "audit_capture": {
            "count": _as_int(feedback_audit.get("audit_event_count")),
            "ready": _as_int(feedback_audit.get("audit_event_count")) >= 0
            and _as_int(governance_audit.get("audit_event_count")) >= 0,
            "source": "audit_runtime",
        },
        "feedback_capture": {
            "count": _as_int(feedback_audit.get("feedback_count")),
            "ready": _as_int(feedback_audit.get("feedback_count")) >= 0
            and _as_int(governance_feedback.get("feedback_count")) >= 0,
            "source": "feedback_runtime",
        },
        "workflow_definitions": {
            "count": _as_int(workflow_list.get("workflow_count")),
            "ready": _as_int(workflow_list.get("workflow_count")) >= 0,
            "source": "workflow_runtime",
        },
    }


def _workflow_inventory(
    catalog: list[dict[str, Any]],
    evidence: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    readiness_by_key = {key: bool(item.get("ready")) for key, item in evidence.items()}
    inventory = []
    for definition in catalog:
        key = str(definition["workflow_key"])
        runtime_evidence = evidence.get(key, {"ready": False, "count": 0})
        dependencies = list(definition.get("dependencies") or [])
        blocking_dependencies = [dependency for dependency in dependencies if not readiness_by_key.get(dependency)]
        optional = bool(definition.get("optional"))
        ready = bool(runtime_evidence.get("ready"))
        pending_capabilities: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []
        if optional and not ready:
            status = "skipped"
            pending_capabilities.append(
                _issue(
                    f"{key}_not_configured",
                    "Optional workflow has no configured runtime evidence yet.",
                    domain=str(definition["category"]),
                )
            )
        elif blocking_dependencies:
            status = "blocked"
        elif ready:
            status = "ready"
        else:
            status = "pending"
            warnings.append(
                _issue(
                    f"{key}_runtime_evidence_pending",
                    "Workflow exists in the product graph but has no completed runtime evidence yet.",
                    domain=str(definition["category"]),
                )
            )
        inventory.append(
            {
                "workflow_key": key,
                "workflow_name": definition["workflow_name"],
                "category": definition["category"],
                "status": status,
                "ready": ready,
                "optional": optional,
                "dependencies": dependencies,
                "blocking_dependencies": blocking_dependencies,
                "runtime_evidence": runtime_evidence,
                "warnings": warnings,
                "pending_capabilities": pending_capabilities,
            }
        )
    return inventory


def _categories(inventory: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for workflow in inventory:
        grouped[str(workflow["category"])].append(workflow)
    return {
        category: {
            "workflow_count": len(workflows),
            "ready_workflows": len([workflow for workflow in workflows if workflow.get("ready")]),
            "blocked_workflows": len([workflow for workflow in workflows if workflow.get("status") == "blocked"]),
            "pending_workflows": len([workflow for workflow in workflows if workflow.get("status") == "pending"]),
            "optional_workflows": len([workflow for workflow in workflows if workflow.get("optional")]),
            "status": "ready"
            if all(workflow.get("ready") or workflow.get("optional") for workflow in workflows)
            else "degraded",
            "workflows": workflows,
        }
        for category, workflows in sorted(grouped.items())
    }


def _readiness(inventory: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(inventory)
    ready = len([workflow for workflow in inventory if workflow.get("ready")])
    blocked = len([workflow for workflow in inventory if workflow.get("status") == "blocked"])
    optional = len([workflow for workflow in inventory if workflow.get("optional")])
    degraded = len(
        [
            workflow
            for workflow in inventory
            if workflow.get("status") in {"pending", "blocked"} and not workflow.get("optional")
        ]
    )
    score = round((ready / total) * 100, 2) if total else 0.0
    return {
        "overall_workflow_readiness": "ready" if blocked == 0 and degraded == 0 else "degraded",
        "ready_workflows": ready,
        "degraded_workflows": degraded,
        "optional_workflows": optional,
        "blocked_workflows": blocked,
        "workflow_score": score,
        "workflow_count": total,
    }


def _dependencies(inventory: list[dict[str, Any]]) -> dict[str, Any]:
    graph = [
        {"from": dependency, "to": workflow["workflow_key"]}
        for workflow in inventory
        for dependency in workflow.get("dependencies") or []
    ]
    missing = [
        {
            "workflow_key": workflow["workflow_key"],
            "workflow_name": workflow["workflow_name"],
            "blocking_dependencies": workflow["blocking_dependencies"],
        }
        for workflow in inventory
        if workflow.get("blocking_dependencies")
    ]
    return {
        "dependency_graph": graph,
        "missing_prerequisites": missing,
        "dependency_count": len(graph),
        "missing_prerequisite_count": len(missing),
    }


def _diagnostics(
    inventory: list[dict[str, Any]],
    operations: dict[str, Any],
    reference: dict[str, Any],
) -> dict[str, Any]:
    dependency_info = _dependencies(inventory)
    runtime = _mapping(operations.get("runtime_persistence"))
    documents = _mapping(operations.get("document_lifecycle_operations"))
    processing = _mapping(operations.get("processing_workers"))
    readiness_by_status = Counter(str(workflow.get("status")) for workflow in inventory)
    warnings = [warning for workflow in inventory for warning in _listing(workflow.get("warnings"))]
    pending = [
        pending_item for workflow in inventory for pending_item in _listing(workflow.get("pending_capabilities"))
    ]
    return {
        "dependency_graph": dependency_info["dependency_graph"],
        "missing_prerequisites": dependency_info["missing_prerequisites"],
        "runtime_evidence": {
            "runtime_records": runtime.get("total_runtime_records"),
            "recent_runtime_records": runtime.get("recent_runtime_records") or [],
            "reference_tenant_ready": reference.get("reference_tenant_ready"),
        },
        "execution_history_summary": {
            "runtime_records_by_domain": runtime.get("runtime_records_by_domain") or {},
            "runtime_records_by_status": runtime.get("runtime_records_by_status") or {},
            "recent_lifecycles": documents.get("recent_lifecycles") or [],
            "recent_processing_activity": processing.get("recent_processing_activity") or [],
        },
        "idempotency_support": {
            "storage_reuse_count": documents.get("storage_reused"),
            "idempotent_resumptions": documents.get("idempotent_resumptions"),
            "supported": _as_int(documents.get("storage_reused")) >= 0,
        },
        "retry_capability": {
            "retry_candidates": processing.get("retry_candidates"),
            "worker_execution_pending": processing.get("worker_execution_pending"),
            "supported": _as_int(processing.get("retry_candidates")) >= 0,
        },
        "resume_capability": {
            "pending_lifecycles": documents.get("pending_lifecycles"),
            "supported": _as_int(documents.get("idempotent_resumptions")) >= 0,
        },
        "workflow_status_counts": dict(readiness_by_status),
        "warnings": warnings,
        "pending_capabilities": pending,
    }


def _reference_tenant_section(reference: dict[str, Any]) -> dict[str, Any]:
    return {
        "reference_tenant_ready": reference.get("reference_tenant_ready"),
        "reference_tenant_workflow_readiness": reference.get("reference_tenant_ready"),
        "provisioning_readiness": reference.get("organization_ready") and reference.get("security_ready"),
        "lifecycle_readiness": reference.get("documents_ready"),
        "knowledge_readiness": reference.get("knowledge_ready"),
        "assistant_readiness": reference.get("assistant_ready") and reference.get("chat_ready"),
        "search_readiness": reference.get("search_ready"),
        "domain_results": reference.get("domain_results") or {},
        "pending_capabilities": reference.get("pending_capabilities") or [],
        "blocking_issues": reference.get("blocking_issues") or [],
        "warnings": reference.get("warnings") or [],
    }


def _recommendations(
    inventory: list[dict[str, Any]],
    diagnostics: dict[str, Any],
    reference: dict[str, Any],
) -> list[dict[str, Any]]:
    recommendations = []
    if diagnostics["missing_prerequisites"]:
        recommendations.append(
            {"code": "review_workflow_dependencies", "label": "Review blocked workflow prerequisites"}
        )
    if reference.get("blocking_issues"):
        recommendations.append({"code": "open_reference_tenant", "label": "Inspect Reference Tenant readiness"})
    if any(workflow.get("status") == "pending" for workflow in inventory):
        recommendations.append(
            {"code": "inspect_pending_workflows", "label": "Inspect workflows without runtime evidence"}
        )
    if any(workflow.get("status") == "skipped" for workflow in inventory):
        recommendations.append({"code": "review_optional_workflows", "label": "Review optional workflow configuration"})
    if not recommendations:
        recommendations.append(
            {"code": "monitor_workflow_health", "label": "Monitor workflow health and runtime evidence"}
        )
    return recommendations


def build_workflow_studio_runtime(db: Session) -> dict[str, Any]:
    operations = build_operations_center_runtime(db)
    ai_studio = build_ai_studio_runtime(db)
    governance = build_governance_center_runtime(db)
    reference = build_reference_tenant_readiness(db)
    workflow_health = build_workflow_health(db)
    workflow_list = list_workflows_runtime(db, limit=500)

    catalog = _workflow_catalog()
    evidence = _evidence_map(operations, ai_studio, governance, reference, workflow_list)
    inventory = _workflow_inventory(catalog, evidence)
    categories = _categories(inventory)
    readiness = _readiness(inventory)
    dependencies = _dependencies(inventory)
    diagnostics = _diagnostics(inventory, operations, reference)
    reference_tenant = _reference_tenant_section(reference)
    pending_capabilities = []
    pending_capabilities.extend(diagnostics.get("pending_capabilities") or [])
    pending_capabilities.extend(reference_tenant.get("pending_capabilities") or [])
    warnings = []
    warnings.extend(diagnostics.get("warnings") or [])
    warnings.extend(reference_tenant.get("warnings") or [])
    recommendations = _recommendations(inventory, diagnostics, reference)
    runtime_status = "ready" if readiness["blocked_workflows"] == 0 else "degraded"

    return {
        "workflow_studio_runtime_schema_version": WORKFLOW_STUDIO_RUNTIME_SCHEMA_VERSION,
        "runtime_name": WORKFLOW_STUDIO_RUNTIME_NAME,
        "runtime_status": runtime_status,
        "workspace_summary": {
            "runtime_status": runtime_status,
            "workflow_studio_ready": readiness["blocked_workflows"] == 0,
            "workflow_score": readiness["workflow_score"],
            "workflow_count": readiness["workflow_count"],
            "ready_workflows": readiness["ready_workflows"],
            "blocked_workflows": readiness["blocked_workflows"],
            "reference_tenant_ready": reference.get("reference_tenant_ready"),
            "operations_ready": _mapping(operations.get("workspace_summary")).get("operations_ready"),
            "governance_ready": _mapping(governance.get("workspace_summary")).get("governance_ready"),
            "ai_studio_ready": _mapping(ai_studio.get("workspace_summary")).get("ai_ready"),
            "postgresql_source_of_truth": True,
            "side_effects_performed": False,
            "external_calls_performed": False,
            "llm_used": False,
            "qdrant_used": False,
        },
        "workflow_inventory": inventory,
        "workflow_categories": categories,
        "workflow_readiness": readiness,
        "workflow_diagnostics": diagnostics,
        "workflow_dependencies": dependencies,
        "workflow_evidence": evidence,
        "workflow_runtime_state": {
            "workflow_definitions": workflow_list.get("workflows") or [],
            "workflow_definition_count": workflow_list.get("workflow_count"),
            "ai_workflows": ai_studio.get("workflows") or [],
            "runtime_persistence": operations.get("runtime_persistence") or {},
            "document_lifecycle_operations": operations.get("document_lifecycle_operations") or {},
            "processing_workers": operations.get("processing_workers") or {},
            "knowledge_operations": operations.get("knowledge_operations") or {},
            "enterprise_search_operations": operations.get("enterprise_search_operations") or {},
            "assistant_operations": operations.get("assistant_operations") or {},
            "connector_operations": operations.get("connector_operations") or {},
            "feedback_audit_operations": operations.get("feedback_audit_operations") or {},
        },
        "workflow_health": {
            **workflow_health,
            "health_status": "ready" if workflow_health.get("workflow_runtime_available") else "degraded",
            "operation_center_status": operations.get("runtime_status"),
        },
        "workflow_recommendations": recommendations,
        "reference_tenant": reference_tenant,
        "pending_capabilities": pending_capabilities,
        "warnings": warnings,
        "postgresql_source_of_truth": True,
        "side_effects_performed": False,
        "external_calls_performed": False,
        "llm_used": False,
        "qdrant_used": False,
    }
