from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.services.ai_studio_runtime import build_ai_studio_runtime
from app.services.assistant_workspace_runtime import build_assistant_workspace_runtime
from app.services.connector_workspace_runtime import build_connector_workspace_runtime
from app.services.document_workspace_runtime import build_document_workspace_runtime
from app.services.governance_center_runtime import build_governance_center_runtime
from app.services.knowledge_workspace_runtime import build_knowledge_workspace_runtime
from app.services.operations_center_runtime import build_operations_center_runtime
from app.services.platform_administration_runtime import build_platform_administration_runtime
from app.services.platform_dashboard_runtime import build_platform_dashboard_runtime
from app.services.platform_read_projections import build_platform_read_projections
from app.services.production_acceptance_runtime import build_production_workspace_runtime
from app.services.reference_tenant import (
    build_reference_tenant_readiness,
    build_reference_tenant_status,
    validate_reference_tenant,
)

PRODUCT_INTEGRATION_RUNTIME_SCHEMA_VERSION = "1"
PRODUCT_INTEGRATION_RUNTIME_NAME = "product_integration_runtime"
PLATFORM_STAGE = "pre-production"
READY = "READY"
DEGRADED = "DEGRADED"
OPTIONAL_NOT_CONFIGURED = "OPTIONAL_NOT_CONFIGURED"
SKIPPED = "SKIPPED"
BLOCKED = "BLOCKED"
WORKSPACE_KEYS = (
    "platform_home",
    "platform_dashboard",
    "administration",
    "operations",
    "governance",
    "documents",
    "knowledge",
    "assistants",
    "ai_studio",
    "connectors",
)
REQUIRED_DOMAIN_KEYS = (
    "platform",
    "administration",
    "documents",
    "knowledge",
    "enterprise_search",
    "assistants",
    "operations",
    "governance",
    "reference_tenant",
)
OPTIONAL_DOMAIN_KEYS = (
    "connectors",
    "ai_models",
    "ai_providers",
    "external_llm",
    "qdrant",
    "embeddings",
    "external_integrations",
)


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _listing(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _ready_from_status(value: Any) -> bool:
    return str(value or "").lower() == "ready"


def _domain_score(flags: dict[str, bool]) -> int:
    if not flags:
        return 0
    ready = len([value for value in flags.values() if value])
    return int(round(ready / len(flags) * 100))


def _matrix_status(ready: bool) -> str:
    return READY if ready else DEGRADED


def _status_from_flags(flags: dict[str, bool], required: bool) -> str:
    if flags and all(flags.values()):
        return READY
    if required:
        return DEGRADED
    if not flags or not any(flags.values()):
        return OPTIONAL_NOT_CONFIGURED
    return DEGRADED


def _domain_readiness_item(
    domain: str,
    *,
    required: bool,
    flags: dict[str, bool],
    status: str | None = None,
    reason: str | None = None,
    blocking_issues: list[Any] | None = None,
    warnings: list[Any] | None = None,
    pending_capabilities: list[Any] | None = None,
) -> dict[str, Any]:
    resolved_status = status or _status_from_flags(flags, required)
    blocking = resolved_status == BLOCKED
    ready = resolved_status == READY
    return {
        "domain": domain,
        "required": required,
        "status": resolved_status,
        "ready": ready,
        "score": _domain_score(flags),
        "blocking": blocking,
        "warnings": warnings or [],
        "pending_capabilities": pending_capabilities or [],
        "reason": reason,
        "checks": flags,
        "blocking_issues": blocking_issues or [],
    }


def _workspace_result(
    key: str,
    label: str,
    runtime: dict[str, Any],
    *,
    path: str,
) -> dict[str, Any]:
    diagnostics = _mapping(runtime.get("diagnostics"))
    runtime_ready = _ready_from_status(runtime.get("runtime_status"))
    return {
        "key": key,
        "label": label,
        "path": path,
        "reachable": bool(runtime),
        "runtime_ready": runtime_ready,
        "diagnostics_ready": bool(diagnostics),
        "warnings": _listing(diagnostics.get("warnings")),
        "pending_capabilities": _listing(diagnostics.get("pending_capabilities")),
    }


def _platform_section(
    dashboard: dict[str, Any],
    administration: dict[str, Any],
    workspaces: dict[str, dict[str, Any]],
    integration_ready: bool,
) -> dict[str, Any]:
    platform_summary = _mapping(dashboard.get("platform_summary"))
    administration_platform = _mapping(administration.get("platform"))
    implemented = len([workspace for workspace in workspaces.values() if workspace["reachable"]])
    ready = len([workspace for workspace in workspaces.values() if workspace["runtime_ready"]])
    return {
        "platform_ready": integration_ready,
        "platform_version": platform_summary.get("platform_version") or administration_platform.get("version"),
        "platform_stage": PLATFORM_STAGE,
        "runtime_status": "ready" if integration_ready else "degraded",
        "postgresql_source_of_truth": True,
        "workspace_count": len(WORKSPACE_KEYS),
        "implemented_workspace_count": implemented,
        "pending_workspace_count": max(len(WORKSPACE_KEYS) - ready, 0),
    }


def _administration_section(administration: dict[str, Any]) -> dict[str, bool]:
    health = _mapping(administration.get("health_summary"))
    domain_ready = _mapping(health.get("domain_ready"))
    security = _mapping(administration.get("security"))
    security_totals = _mapping(security.get("effective_totals"))
    documents = _mapping(administration.get("documents"))
    return {
        "organizations_ready": bool(domain_ready.get("organizations")),
        "roles_ready": int(security_totals.get("roles") or 0) > 0,
        "permissions_ready": int(security_totals.get("permissions") or 0) > 0,
        "policies_ready": int(security_totals.get("policies") or 0) > 0,
        "collections_ready": bool(_listing(documents.get("collections"))),
        "metadata_templates_ready": bool(_listing(documents.get("metadata_templates"))),
        "classification_ready": bool(_listing(documents.get("classification_rules"))),
        "retention_ready": bool(_listing(documents.get("retention_policies"))),
    }


def _documents_section(document_workspace: dict[str, Any], knowledge_workspace: dict[str, Any]) -> dict[str, bool]:
    summary = _mapping(document_workspace.get("workspace_summary"))
    storage = _mapping(document_workspace.get("storage"))
    processing = _mapping(document_workspace.get("processing"))
    chunks = _mapping(document_workspace.get("chunks"))
    knowledge_chunk_overview = _mapping(knowledge_workspace.get("chunk_overview"))
    knowledge = _mapping(document_workspace.get("knowledge"))
    enterprise_search = _mapping(document_workspace.get("enterprise_search"))
    registry = _listing(document_workspace.get("document_registry"))
    chunking_ready = (
        int(chunks.get("chunk_count") or 0) > 0
        or int(knowledge_chunk_overview.get("total_chunks") or 0) > 0
        or int(knowledge_chunk_overview.get("indexed_chunks") or 0) > 0
    )
    return {
        "registration_ready": bool(registry) or bool(summary.get("documents_ready")),
        "versioning_ready": bool(_listing(document_workspace.get("versions"))),
        "storage_ready": bool(storage.get("storage_verification")),
        "processing_ready": bool(summary.get("processing_ready")) or processing.get("processing_state") == "ready",
        "chunking_ready": chunking_ready,
        "knowledge_publication_ready": bool(knowledge.get("knowledge_publication")),
        "knowledge_index_ready": bool(enterprise_search.get("knowledge_index_readiness")),
        "enterprise_search_ready": bool(enterprise_search.get("fts_readiness")),
    }


def _knowledge_section(knowledge_workspace: dict[str, Any]) -> dict[str, bool]:
    summary = _mapping(knowledge_workspace.get("workspace_summary"))
    chunk_overview = _mapping(knowledge_workspace.get("chunk_overview"))
    enterprise_search = _mapping(knowledge_workspace.get("enterprise_search"))
    return {
        "knowledge_collections_ready": bool(_listing(knowledge_workspace.get("collections"))),
        "knowledge_sources_ready": bool(_listing(knowledge_workspace.get("knowledge_sources"))),
        "knowledge_documents_ready": bool(_listing(knowledge_workspace.get("knowledge_documents"))),
        "knowledge_chunks_ready": int(chunk_overview.get("total_chunks") or 0) > 0,
        "knowledge_workspace_ready": bool(summary.get("knowledge_ready"))
        and bool(enterprise_search.get("search_ready")),
    }


def _assistants_section(assistant_workspace: dict[str, Any]) -> dict[str, bool]:
    summary = _mapping(assistant_workspace.get("workspace_summary"))
    runtime_executions = _mapping(assistant_workspace.get("runtime_executions"))
    retrieval = _mapping(assistant_workspace.get("retrieval_and_citations"))
    return {
        "assistant_ready": bool(summary.get("assistants_ready")),
        "conversation_ready": bool(summary.get("conversations_ready")),
        "retrieval_ready": bool(retrieval.get("enterprise_search_ready")),
        "context_builder_ready": int(runtime_executions.get("context_builder_executions") or 0) >= 0,
        "prompt_assembly_ready": int(runtime_executions.get("prompt_assembly_executions") or 0) >= 0,
        "gateway_ready": int(runtime_executions.get("llm_gateway_executions") or 0) >= 0,
        "citation_ready": bool(summary.get("citations_ready")) or int(retrieval.get("citation_count") or 0) >= 0,
        "response_ready": int(runtime_executions.get("response_executions") or 0) >= 0,
        "conversation_runtime_ready": bool(summary.get("conversations_ready")),
    }


def _operations_section(operations_center: dict[str, Any]) -> dict[str, bool]:
    summary = _mapping(operations_center.get("workspace_summary"))
    processing = _mapping(operations_center.get("processing_workers"))
    diagnostics = _mapping(operations_center.get("diagnostics"))
    return {
        "runtime_persistence_ready": bool(summary.get("runtime_persistence_ready")),
        "operations_center_ready": _ready_from_status(operations_center.get("runtime_status")),
        "worker_runtime_ready": int(processing.get("processing_failed") or 0) == 0,
        "diagnostics_ready": bool(diagnostics),
    }


def _governance_section(governance_center: dict[str, Any]) -> dict[str, bool]:
    summary = _mapping(governance_center.get("workspace_summary"))
    policy = _mapping(governance_center.get("policy_governance"))
    policy_readiness = _mapping(policy.get("policy_readiness"))
    return {
        "audit_ready": bool(summary.get("audit_ready")),
        "feedback_ready": bool(summary.get("feedback_ready")),
        "policy_security_ready": policy_readiness.get("status") == "ready",
        "lineage_ready": bool(summary.get("lineage_ready")),
        "runtime_evidence_ready": bool(summary.get("evidence_ready")),
        "governance_ready": bool(summary.get("governance_ready")),
    }


def _connectors_section(connector_workspace: dict[str, Any]) -> dict[str, bool]:
    summary = _mapping(connector_workspace.get("workspace_summary"))
    return {
        "connector_catalog_ready": bool(summary.get("connector_types_ready")),
        "connector_configuration_ready": bool(summary.get("connector_configs_ready")),
        "connector_runtime_ready": bool(summary.get("connector_runs_ready")) or bool(summary.get("connectors_ready")),
    }


def _connectors_configured(connector_workspace: dict[str, Any]) -> bool:
    return bool(_listing(connector_workspace.get("connectors")))


def _connectors_failing(connector_workspace: dict[str, Any]) -> bool:
    for run in _listing(connector_workspace.get("connector_runs")):
        status = str(run.get("status") or run.get("run_status") or "").lower()
        if status in {"failed", "error", "blocked", "dead_lettered"}:
            return True
    return False


def _ai_studio_section(ai_studio: dict[str, Any]) -> dict[str, bool]:
    summary = _mapping(ai_studio.get("workspace_summary"))
    return {
        "models_ready": bool(summary.get("models_ready")),
        "providers_ready": bool(_listing(_mapping(ai_studio.get("models_and_providers")).get("providers"))),
        "prompts_ready": bool(summary.get("prompts_ready")),
        "guardrails_ready": bool(summary.get("guardrails_ready")),
        "assistant_configuration_ready": bool(summary.get("assistants_ready")),
    }


def _reference_section(readiness: dict[str, Any], validation: dict[str, Any], status: dict[str, Any]) -> dict[str, Any]:
    return {
        "reference_tenant_ready": bool(readiness.get("reference_tenant_ready")),
        "reference_documents_ready": bool(readiness.get("documents_ready"))
        and bool(readiness.get("reference_content_provisioned")),
        "reference_knowledge_ready": bool(readiness.get("knowledge_ready"))
        and bool(readiness.get("knowledge_indexed")),
        "reference_search_ready": bool(readiness.get("search_ready")),
        "reference_chat_ready": bool(readiness.get("chat_ready")),
        "readiness": readiness,
        "validation": validation,
        "status": status,
    }


def _collect_diagnostics(*payloads: dict[str, Any]) -> dict[str, list[Any]]:
    blocking: list[Any] = []
    warnings: list[Any] = []
    pending: list[Any] = []
    for payload in payloads:
        diagnostics = _mapping(payload.get("diagnostics"))
        blocking.extend(_listing(payload.get("blocking_issues")))
        blocking.extend(_listing(diagnostics.get("blocking_issues")))
        warnings.extend(_listing(payload.get("warnings")))
        warnings.extend(_listing(diagnostics.get("warnings")))
        pending.extend(_listing(payload.get("pending_capabilities")))
        pending.extend(_listing(diagnostics.get("pending_capabilities")))
    return {
        "blocking_issues": blocking,
        "warnings": warnings,
        "pending_capabilities": pending,
    }


def _overall(
    required_domains: list[dict[str, Any]],
    optional_domains: list[dict[str, Any]],
    workspaces: dict[str, dict[str, Any]],
    reference: dict[str, Any],
    diagnostics: dict[str, list[Any]],
) -> dict[str, Any]:
    domain_ready = all(domain["ready"] and not domain["blocking"] for domain in required_domains)
    required_workspace_keys = {
        "platform_home",
        "platform_dashboard",
        "administration",
        "operations",
        "governance",
        "documents",
        "knowledge",
        "assistants",
    }
    workspaces_ready = all(workspaces[key]["reachable"] for key in required_workspace_keys)
    reference_ready = bool(reference.get("reference_tenant_ready"))
    optional_blocking = [domain for domain in optional_domains if domain["blocking"]]
    product_baseline_ready = domain_ready and workspaces_ready and reference_ready and not optional_blocking
    blocking = [
        *diagnostics["blocking_issues"],
        *[
            {
                "code": "required_domain_not_ready",
                "domain": domain["domain"],
                "status": domain["status"],
                "reason": domain.get("reason"),
            }
            for domain in required_domains
            if not domain["ready"] or domain["blocking"]
        ],
        *[
            {
                "code": "optional_domain_configured_and_blocked",
                "domain": domain["domain"],
                "status": domain["status"],
                "reason": domain.get("reason"),
            }
            for domain in optional_blocking
        ],
    ]
    if not product_baseline_ready:
        blocking.append(
            {
                "code": "product_baseline_not_ready",
                "message": "One or more platform domains or workspaces are not ready.",
            }
        )
    recommendations = []
    if diagnostics["pending_capabilities"]:
        recommendations.append({"code": "review_pending_capabilities"})
    if blocking:
        recommendations.append({"code": "resolve_blocking_issues"})
    if not reference_ready:
        recommendations.append({"code": "review_reference_tenant"})
    return {
        "product_baseline_ready": product_baseline_ready,
        "integration_ready": product_baseline_ready and not blocking,
        "production_candidate": product_baseline_ready and not blocking,
        "blocking_issues": blocking,
        "warnings": diagnostics["warnings"],
        "recommendations": recommendations,
        "pending_capabilities": diagnostics["pending_capabilities"],
    }


def _domain_readiness(
    domain_sections: dict[str, dict[str, bool]],
    workspaces: dict[str, dict[str, Any]],
    reference: dict[str, Any],
    connector_workspace: dict[str, Any],
    ai_studio: dict[str, Any],
) -> dict[str, Any]:
    governance_required = {
        "audit_ready": domain_sections["governance"]["audit_ready"],
        "feedback_ready": domain_sections["governance"]["feedback_ready"],
        "runtime_evidence_ready": domain_sections["governance"]["runtime_evidence_ready"],
        "policy_security_ready": domain_sections["governance"]["policy_security_ready"],
    }
    governance_optional = {
        "lineage_ready": domain_sections["governance"]["lineage_ready"],
        "compliance_ready": domain_sections["governance"]["governance_ready"],
    }
    enterprise_search = {
        "document_enterprise_search_ready": domain_sections["documents"]["enterprise_search_ready"],
        "knowledge_workspace_ready": domain_sections["knowledge"]["knowledge_workspace_ready"],
    }
    platform = {
        "platform_home_reachable": workspaces["platform_home"]["reachable"],
        "platform_dashboard_reachable": workspaces["platform_dashboard"]["reachable"],
        "platform_dashboard_ready": workspaces["platform_dashboard"]["runtime_ready"],
    }
    reference_flags = {
        "reference_tenant_ready": bool(reference.get("reference_tenant_ready")),
        "reference_documents_ready": bool(reference.get("reference_documents_ready")),
        "reference_knowledge_ready": bool(reference.get("reference_knowledge_ready")),
        "reference_search_ready": bool(reference.get("reference_search_ready")),
        "reference_chat_ready": bool(reference.get("reference_chat_ready")),
    }
    required_domains = [
        _domain_readiness_item("platform", required=True, flags=platform),
        _domain_readiness_item("administration", required=True, flags=domain_sections["administration"]),
        _domain_readiness_item("documents", required=True, flags=domain_sections["documents"]),
        _domain_readiness_item("knowledge", required=True, flags=domain_sections["knowledge"]),
        _domain_readiness_item("enterprise_search", required=True, flags=enterprise_search),
        _domain_readiness_item("assistants", required=True, flags=domain_sections["assistants"]),
        _domain_readiness_item("operations", required=True, flags=domain_sections["operations"]),
        _domain_readiness_item(
            "governance",
            required=True,
            flags=governance_required,
            pending_capabilities=[
                {"code": key, "status": "pending"} for key, ready in governance_optional.items() if not ready
            ],
            reason="Lineage and compliance depth are reported as non-blocking governance maturity signals.",
        ),
        _domain_readiness_item("reference_tenant", required=True, flags=reference_flags),
    ]
    connectors_configured = _connectors_configured(connector_workspace)
    connectors_failing = _connectors_failing(connector_workspace)
    connector_status = (
        BLOCKED
        if connectors_configured and connectors_failing
        else DEGRADED
        if connectors_configured and not all(domain_sections["connectors"].values())
        else OPTIONAL_NOT_CONFIGURED
    )
    ai_models = _listing(_mapping(ai_studio.get("models_and_providers")).get("models"))
    ai_providers = _listing(_mapping(ai_studio.get("models_and_providers")).get("providers"))
    optional_domains = [
        _domain_readiness_item(
            "connectors",
            required=False,
            flags=domain_sections["connectors"] if connectors_configured else {},
            status=connector_status,
            reason="No configured connectors are required for the current pre-production product baseline."
            if not connectors_configured
            else None,
        ),
        _domain_readiness_item(
            "ai_models",
            required=False,
            flags={"models_configured": bool(ai_models)},
            status=READY if ai_models else OPTIONAL_NOT_CONFIGURED,
            reason="AI models are optional; assistants and search remain PostgreSQL-backed without model execution.",
        ),
        _domain_readiness_item(
            "ai_providers",
            required=False,
            flags={"providers_configured": bool(ai_providers)},
            status=READY if ai_providers else OPTIONAL_NOT_CONFIGURED,
            reason="External AI providers are optional and are not required for the baseline.",
        ),
        _domain_readiness_item(
            "external_llm",
            required=False,
            flags={},
            status=SKIPPED,
            reason="LLM execution is intentionally skipped for this read-only baseline gate.",
        ),
        _domain_readiness_item(
            "qdrant",
            required=False,
            flags={},
            status=SKIPPED,
            reason="Qdrant is not required; PostgreSQL is the source of truth.",
        ),
        _domain_readiness_item(
            "embeddings",
            required=False,
            flags={},
            status=SKIPPED,
            reason="Embeddings are optional derived capabilities and are not required for the baseline.",
        ),
        _domain_readiness_item(
            "external_integrations",
            required=False,
            flags={},
            status=SKIPPED,
            reason="External integrations are intentionally not executed by Product Integration Runtime.",
        ),
    ]
    return {
        "required_domains": required_domains,
        "optional_domains": optional_domains,
        "all_domains": required_domains + optional_domains,
        "required_domain_keys": list(REQUIRED_DOMAIN_KEYS),
        "optional_domain_keys": list(OPTIONAL_DOMAIN_KEYS),
    }


def _rc_gate(
    overall: dict[str, Any],
    domain_readiness: dict[str, Any],
    product_state: dict[str, Any],
    *,
    side_effects_performed: bool,
    external_calls_performed: bool,
    llm_used: bool,
    qdrant_used: bool,
) -> dict[str, Any]:
    required_domains = _listing(domain_readiness.get("required_domains"))
    optional_domains = _listing(domain_readiness.get("optional_domains"))
    required_domains_ready = all(domain.get("ready") and not domain.get("blocking") for domain in required_domains)
    optional_domains_non_blocking = not any(domain.get("blocking") for domain in optional_domains)
    side_effect_free = not side_effects_performed
    external_calls_free = not external_calls_performed
    ai_execution_free = not llm_used and not qdrant_used
    blocking_issues = list(overall.get("blocking_issues") or [])
    normalization_debt = [
        {
            "code": "optional_domain_not_configured",
            "domain": domain.get("domain"),
            "status": domain.get("status"),
            "reason": domain.get("reason"),
        }
        for domain in optional_domains
        if domain.get("status") in {OPTIONAL_NOT_CONFIGURED, SKIPPED}
    ]
    domain_integration_ready = bool(
        overall.get("product_baseline_ready")
        and overall.get("integration_ready")
        and required_domains_ready
        and optional_domains_non_blocking
        and side_effect_free
        and external_calls_free
        and ai_execution_free
        and not blocking_issues
    )
    release_eligibility = _mapping(product_state.get("release_eligibility"))
    return {
        "domain_integration_ready": domain_integration_ready,
        "production_candidate": bool(release_eligibility.get("eligible")),
        "release_candidate_eligible": bool(release_eligibility.get("eligible")),
        "release_eligibility_status": release_eligibility.get("status") or "unavailable",
        "release_eligibility_reason": release_eligibility.get("reason"),
        "release_eligibility_blocking_reasons": release_eligibility.get("blocking_reasons") or [],
        "required_domains_ready": required_domains_ready,
        "optional_domains_non_blocking": optional_domains_non_blocking,
        "side_effect_free": side_effect_free,
        "external_calls_free": external_calls_free,
        "ai_execution_free": ai_execution_free,
        "blocking_issues": blocking_issues,
        "warnings": list(overall.get("warnings") or []),
        "normalization_debt": normalization_debt,
    }


def _scores(domain_sections: dict[str, dict[str, bool]]) -> dict[str, int]:
    scores = {
        "administration_score": _domain_score(domain_sections["administration"]),
        "documents_score": _domain_score(domain_sections["documents"]),
        "knowledge_score": _domain_score(domain_sections["knowledge"]),
        "assistant_score": _domain_score(domain_sections["assistants"]),
        "operations_score": _domain_score(domain_sections["operations"]),
        "governance_score": _domain_score(domain_sections["governance"]),
        "connector_score": _domain_score(domain_sections["connectors"]),
        "ai_score": _domain_score(domain_sections["ai_studio"]),
    }
    scores["overall_score"] = int(round(sum(scores.values()) / len(scores))) if scores else 0
    return scores


def _readiness_matrix(domain_sections: dict[str, dict[str, bool]], reference: dict[str, Any]) -> dict[str, Any]:
    domains = {
        "Administration": all(domain_sections["administration"].values()),
        "Documents": all(domain_sections["documents"].values()),
        "Knowledge": all(domain_sections["knowledge"].values()),
        "Search": domain_sections["documents"]["enterprise_search_ready"],
        "Assistant": all(domain_sections["assistants"].values()),
        "Operations": all(domain_sections["operations"].values()),
        "Governance": all(domain_sections["governance"].values()),
        "Connectors": all(domain_sections["connectors"].values()),
        "AI Studio": all(domain_sections["ai_studio"].values()),
        "Reference Tenant": bool(reference.get("reference_tenant_ready")),
    }
    return {
        "domains": [
            {"domain": domain, "ready": ready, "status": _matrix_status(ready)} for domain, ready in domains.items()
        ],
        "summary": {
            "ready_domains": len([ready for ready in domains.values() if ready]),
            "total_domains": len(domains),
        },
    }


def _readiness_matrix_from_domains(domain_readiness: dict[str, Any]) -> dict[str, Any]:
    domains = _listing(domain_readiness.get("all_domains"))
    return {
        "domains": [
            {
                "domain": domain["domain"],
                "required": domain["required"],
                "ready": domain["ready"],
                "status": domain["status"],
                "score": domain["score"],
                "blocking": domain["blocking"],
            }
            for domain in domains
        ],
        "summary": {
            "ready_domains": len([domain for domain in domains if domain.get("ready")]),
            "total_domains": len(domains),
            "required_domains": len([domain for domain in domains if domain.get("required")]),
            "optional_domains": len([domain for domain in domains if not domain.get("required")]),
            "blocked_domains": len([domain for domain in domains if domain.get("blocking")]),
        },
    }


def build_product_integration_runtime(
    db: Session,
    *,
    source_runtimes: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    sources = source_runtimes or {}
    projections = build_platform_read_projections(db) if source_runtimes is None else {}
    dashboard = sources["dashboard"] if "dashboard" in sources else build_platform_dashboard_runtime(db)
    administration_runtime = (
        sources["administration"]
        if "administration" in sources
        else build_platform_administration_runtime(db)
    )
    operations_center = (
        sources["operations"] if "operations" in sources else build_operations_center_runtime(db)
    )
    governance_center = (
        sources["governance"] if "governance" in sources else build_governance_center_runtime(db)
    )
    document_workspace = (
        sources["documents"]
        if "documents" in sources
        else projections.get("documents") or build_document_workspace_runtime(db)
    )
    knowledge_workspace = (
        sources["knowledge"]
        if "knowledge" in sources
        else projections.get("knowledge") or build_knowledge_workspace_runtime(db)
    )
    assistant_workspace = (
        sources["assistants"]
        if "assistants" in sources
        else projections.get("assistants") or build_assistant_workspace_runtime(db, platform_scope=True)
    )
    connector_workspace = (
        sources["connectors"] if "connectors" in sources else build_connector_workspace_runtime(db)
    )
    ai_studio = sources["ai_studio"] if "ai_studio" in sources else build_ai_studio_runtime(db)
    reference_readiness = (
        sources["reference_readiness"]
        if "reference_readiness" in sources
        else build_reference_tenant_readiness(db)
    )
    reference_validation = (
        sources["reference_validation"]
        if "reference_validation" in sources
        else validate_reference_tenant(db)
    )
    reference_status = (
        sources["reference_status"]
        if "reference_status" in sources
        else build_reference_tenant_status(db)
    )
    production_acceptance_source = sources.get("production_acceptance")
    if isinstance(production_acceptance_source, dict):
        production_acceptance = production_acceptance_source
    elif source_runtimes is not None:
        production_acceptance = {
            "product_acceptance": {"status": "unavailable", "historical_result": "unavailable"},
            "evidence_freshness": {"status": "unavailable"},
            "release_eligibility": {
                "eligible": False,
                "status": "unavailable",
                "reason": "Current Product Acceptance evidence is required.",
                "blocking_reasons": ["product_acceptance_evidence_missing"],
            },
        }
    else:
        production_acceptance = build_production_workspace_runtime(
            db, scope="platform", organization_id=None
        ).model_dump(mode="json")
    product_state = {
        "product_acceptance": _mapping(production_acceptance.get("product_acceptance")),
        "evidence_freshness": _mapping(production_acceptance.get("evidence_freshness")),
        "release_eligibility": _mapping(production_acceptance.get("release_eligibility")),
    }

    workspaces = {
        "platform_home": {
            "key": "platform_home",
            "label": "Platform Home",
            "path": "/",
            "reachable": True,
            "runtime_ready": True,
            "diagnostics_ready": True,
            "warnings": [],
            "pending_capabilities": [],
        },
        "platform_dashboard": _workspace_result("platform_dashboard", "Platform Dashboard", dashboard, path="/"),
        "administration": _workspace_result(
            "administration", "Administration", administration_runtime, path="/organization"
        ),
        "operations": _workspace_result("operations", "Operations", operations_center, path="/operations"),
        "governance": _workspace_result("governance", "Governance", governance_center, path="/governance"),
        "documents": _workspace_result("documents", "Documents", document_workspace, path="/documents"),
        "knowledge": _workspace_result("knowledge", "Knowledge", knowledge_workspace, path="/knowledge"),
        "assistants": _workspace_result("assistants", "Assistants", assistant_workspace, path="/ai"),
        "ai_studio": _workspace_result("ai_studio", "AI Studio", ai_studio, path="/ai"),
        "connectors": _workspace_result("connectors", "Connectors", connector_workspace, path="/connectors"),
    }
    domain_sections = {
        "administration": _administration_section(administration_runtime),
        "documents": _documents_section(document_workspace, knowledge_workspace),
        "knowledge": _knowledge_section(knowledge_workspace),
        "assistants": _assistants_section(assistant_workspace),
        "operations": _operations_section(operations_center),
        "governance": _governance_section(governance_center),
        "connectors": _connectors_section(connector_workspace),
        "ai_studio": _ai_studio_section(ai_studio),
    }
    reference = _reference_section(reference_readiness, reference_validation, reference_status)
    diagnostics = _collect_diagnostics(
        dashboard,
        administration_runtime,
        operations_center,
        governance_center,
        document_workspace,
        knowledge_workspace,
        assistant_workspace,
        connector_workspace,
        ai_studio,
        reference_readiness,
        reference_validation,
    )
    domain_readiness = _domain_readiness(
        domain_sections,
        workspaces,
        reference,
        connector_workspace,
        ai_studio,
    )
    overall = _overall(
        _listing(domain_readiness.get("required_domains")),
        _listing(domain_readiness.get("optional_domains")),
        workspaces,
        reference,
        diagnostics,
    )
    integration_ready = bool(overall["integration_ready"])
    platform = _platform_section(dashboard, administration_runtime, workspaces, integration_ready)
    scores = _scores(domain_sections)
    readiness_matrix = _readiness_matrix_from_domains(domain_readiness)
    rc_gate = _rc_gate(
        overall,
        domain_readiness,
        product_state,
        side_effects_performed=False,
        external_calls_performed=False,
        llm_used=False,
        qdrant_used=False,
    )
    overall["production_candidate"] = rc_gate["production_candidate"]
    overall["domain_integration_ready"] = rc_gate["domain_integration_ready"]
    overall["release_candidate_eligible"] = rc_gate["release_candidate_eligible"]
    runtime_validation = {
        "dashboard_runtime_ready": _ready_from_status(dashboard.get("runtime_status")),
        "administration_runtime_ready": _ready_from_status(administration_runtime.get("runtime_status")),
        "operations_center_ready": _ready_from_status(operations_center.get("runtime_status")),
        "governance_center_ready": _ready_from_status(governance_center.get("runtime_status")),
        "document_workspace_ready": _ready_from_status(document_workspace.get("runtime_status")),
        "knowledge_workspace_ready": _ready_from_status(knowledge_workspace.get("runtime_status")),
        "assistant_workspace_ready": _ready_from_status(assistant_workspace.get("runtime_status")),
        "connector_workspace_ready": _ready_from_status(connector_workspace.get("runtime_status")),
        "ai_studio_ready": _ready_from_status(ai_studio.get("runtime_status")),
    }
    return {
        "product_integration_runtime_schema_version": PRODUCT_INTEGRATION_RUNTIME_SCHEMA_VERSION,
        "runtime_name": PRODUCT_INTEGRATION_RUNTIME_NAME,
        "runtime_status": "ready" if integration_ready else "degraded",
        "platform": platform,
        **domain_sections,
        "workspace_validation": {
            "workspaces": list(workspaces.values()),
            "workspace_count": len(workspaces),
            "implemented_workspace_count": len(
                [workspace for workspace in workspaces.values() if workspace["reachable"]]
            ),
            "ready_workspace_count": len(
                [workspace for workspace in workspaces.values() if workspace["runtime_ready"]]
            ),
        },
        "runtime_validation": runtime_validation,
        "reference_tenant": reference,
        "domain_readiness": domain_readiness,
        "rc_gate": rc_gate,
        **product_state,
        "overall": overall,
        "product_score": scores,
        "readiness_matrix": readiness_matrix,
        "diagnostics": {
            "blocking_issues": overall["blocking_issues"],
            "warnings": overall["warnings"],
            "pending_capabilities": overall["pending_capabilities"],
            "recommendations": overall["recommendations"],
        },
        "postgresql_source_of_truth": True,
        "side_effects_performed": False,
        "external_calls_performed": False,
        "llm_used": False,
        "qdrant_used": False,
    }
