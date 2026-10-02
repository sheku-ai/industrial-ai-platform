from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.connectors import Connector, ConnectorConfig, ConnectorRun, ConnectorType
from app.models.control_plane import OperationalJob, OperationalSchedule, SchedulerClaim, SchedulerRun
from app.models.core import Organization
from app.models.documents import Artifact, DocumentVersion
from app.models.runtime import RuntimeExecution, RuntimePersistenceRecord
from app.models.runtime_worker import RuntimeWorker
from app.services.platform_administration_runtime import build_platform_administration_runtime
from app.services.platform_operations_runtime import build_platform_operations_runtime
from app.services.runtime_composition import compose_runtime_dependency

PLATFORM_DASHBOARD_RUNTIME_SCHEMA_VERSION = "1"
PLATFORM_DASHBOARD_RUNTIME_NAME = "platform_dashboard_runtime"


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _listing(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _count(db: Session, model: Any, *criteria: Any) -> int:
    statement = select(func.count(model.id))
    if criteria:
        statement = statement.where(*criteria)
    return int(db.scalar(statement) or 0)


def _count_by(db: Session, model: Any, column: Any) -> dict[str, int]:
    rows = db.execute(select(column, func.count()).select_from(model).group_by(column)).all()
    return {str(value or "unknown"): int(count or 0) for value, count in rows}


def _iso(value: Any) -> str | None:
    return value.isoformat() if hasattr(value, "isoformat") else None


def _ready_status(ready: bool) -> str:
    return "ready" if ready else "degraded"


def _navigation_item(
    key: str,
    label: str,
    path: str,
    *,
    ready: bool,
    count: int | None = None,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "key": key,
        "label": label,
        "path": path,
        "readiness": "ready" if ready else "pending",
        "status": _ready_status(ready),
    }
    if count is not None:
        item["count"] = count
    return item


def _admin_count(administration: dict[str, Any], section: str, key: str) -> int:
    return _int(_mapping(_mapping(administration.get(section)).get("counts")).get(key))


def _platform_summary(
    administration: dict[str, Any],
    operations: dict[str, Any],
    runtime_status: str,
) -> dict[str, Any]:
    platform = _mapping(administration.get("platform"))
    platform_runtime = _mapping(operations.get("platform_runtime"))
    reference_tenant = _mapping(administration.get("reference_tenant"))
    product_baseline = _mapping(reference_tenant.get("product_baseline"))
    return {
        "platform_version": platform.get("version") or platform_runtime.get("current_version"),
        "edition": platform.get("edition") or "community",
        "runtime_status": runtime_status,
        "product_baseline_status": "ready" if bool(product_baseline.get("product_baseline_ready")) else "pending",
        "postgresql_source_of_truth": True,
        "ai_required": False,
        "llm_used": False,
        "embeddings_used": False,
        "qdrant_used": False,
    }


def _readiness_summary(administration: dict[str, Any], operations: dict[str, Any]) -> dict[str, bool]:
    admin_health = _mapping(administration.get("health_summary"))
    admin_domain_ready = _mapping(admin_health.get("domain_ready"))
    operations_readiness = _mapping(operations.get("operational_readiness"))
    operations_domain_ready = _mapping(operations_readiness.get("domain_ready"))
    reference_tenant = _mapping(administration.get("reference_tenant"))
    reference_readiness = _mapping(reference_tenant.get("readiness"))
    return {
        "administration_ready": administration.get("runtime_status") == "ready",
        "operations_ready": bool(operations_readiness.get("ready")),
        "reference_tenant_ready": bool(reference_readiness.get("reference_tenant_ready"))
        or bool(operations_domain_ready.get("reference_tenant")),
        "documents_ready": bool(admin_domain_ready.get("documents")) and bool(operations_domain_ready.get("documents")),
        "knowledge_ready": bool(admin_domain_ready.get("knowledge")) and bool(operations_domain_ready.get("knowledge")),
        "search_ready": bool(admin_domain_ready.get("enterprise_search"))
        and bool(operations_domain_ready.get("enterprise_search")),
        "assistant_ready": bool(admin_domain_ready.get("assistants"))
        and bool(operations_domain_ready.get("assistant")),
        "chat_ready": bool(reference_readiness.get("chat_ready")),
        "feedback_ready": bool(_mapping(operations.get("feedback")).get("ready")),
        "audit_ready": bool(_mapping(operations.get("feedback")).get("ready")),
    }


def _operational_summary(administration: dict[str, Any], operations: dict[str, Any]) -> dict[str, Any]:
    documents = _mapping(operations.get("documents"))
    knowledge = _mapping(operations.get("knowledge"))
    enterprise_search = _mapping(operations.get("enterprise_search"))
    assistant = _mapping(operations.get("assistant"))
    feedback = _mapping(operations.get("feedback"))
    assistants = _mapping(administration.get("assistants"))
    return {
        "registered_documents": _int(documents.get("registered_documents")),
        "processed_documents": _int(documents.get("processing_completed")),
        "knowledge_documents": _int(knowledge.get("knowledge_documents")),
        "indexed_documents": _int(knowledge.get("indexed_documents")),
        "indexed_knowledge_documents": _int(knowledge.get("indexed_documents")),
        "knowledge_chunks": _int(knowledge.get("knowledge_chunks")),
        "search_readiness": _mapping(enterprise_search.get("fts_readiness")),
        "search_requests": _int(enterprise_search.get("search_requests")),
        "assistant_definitions": len(_listing(assistants.get("assistant_definitions"))),
        "assistant_executions": _int(assistant.get("assistant_executions")),
        "conversations": _int(assistant.get("conversation_count")),
        "feedback_count": _int(feedback.get("feedback_received")),
        "audit_count": _int(feedback.get("audit_events")),
    }


def _organization_summary(
    db: Session,
    *,
    organization_id: uuid.UUID | None,
    platform_scope: bool,
) -> dict[str, Any]:
    statement = select(Organization)
    if not platform_scope:
        statement = statement.where(Organization.id == organization_id)
    organizations = list(db.scalars(statement).all())

    def validation_generated(item: Organization) -> bool:
        config = item.config or {}
        return bool(
            config.get("smoke") is True
            or config.get("validation_generated") is True
            or config.get("scenario") == "local_product_acceptance"
            or config.get("execution_key")
        )

    product_organizations = [item for item in organizations if not validation_generated(item)]
    active = [item for item in product_organizations if item.status == "active"]
    reference = [item for item in product_organizations if (item.config or {}).get("reference_tenant") is True]
    return {
        "status": "ready" if active else "not_configured",
        "total_organizations": len(product_organizations),
        "active_organizations": len(active),
        "archived_organizations": len([item for item in product_organizations if item.status == "archived"]),
        "validation_generated_excluded": len(organizations) - len(product_organizations),
        "reference_tenant_configured": bool(reference),
        "latest_organization_at": _iso(max((item.created_at for item in product_organizations), default=None)),
    }


def _worker_summary(db: Session) -> dict[str, Any]:
    total = _count(db, RuntimeWorker)
    ready = _count(db, RuntimeWorker, RuntimeWorker.observed_state == "ready")
    stale = _count(db, RuntimeWorker, RuntimeWorker.heartbeat_at.is_(None))
    failed = _count(db, RuntimeWorker, RuntimeWorker.observed_state == "failed")
    paused = _count(db, RuntimeWorker, RuntimeWorker.desired_state == "paused")
    return {
        "status": "ready" if total and ready else ("not_configured" if total == 0 else "degraded"),
        "total_workers": total,
        "ready_workers": ready,
        "paused_workers": paused,
        "failed_workers": failed,
        "workers_without_heartbeat": stale,
        "workers_by_state": _count_by(db, RuntimeWorker, RuntimeWorker.observed_state),
    }


def _scheduler_summary(db: Session) -> dict[str, Any]:
    jobs = _count(db, OperationalJob)
    enabled_jobs = _count(db, OperationalJob, OperationalJob.enabled.is_(True))
    schedules = _count(db, OperationalSchedule)
    enabled_schedules = _count(db, OperationalSchedule, OperationalSchedule.enabled.is_(True))
    pending_runs = _count(db, SchedulerRun, SchedulerRun.status.in_(("pending", "claimed", "dispatched")))
    failed_runs = _count(db, SchedulerRun, SchedulerRun.status == "failed")
    active_claims = _count(db, SchedulerClaim)
    return {
        "status": "ready" if jobs or schedules else "not_configured",
        "jobs": jobs,
        "enabled_jobs": enabled_jobs,
        "schedules": schedules,
        "enabled_schedules": enabled_schedules,
        "pending_runs": pending_runs,
        "failed_runs": failed_runs,
        "active_claims": active_claims,
        "runs_by_status": _count_by(db, SchedulerRun, SchedulerRun.status),
    }


def _storage_summary(
    db: Session,
    *,
    organization_id: uuid.UUID | None,
    platform_scope: bool,
) -> dict[str, Any]:
    settings = get_settings()
    version_criteria = () if platform_scope else (DocumentVersion.organization_id == organization_id,)
    artifact_criteria = () if platform_scope else (Artifact.organization_id == organization_id,)
    stored_versions = _count(
        db,
        DocumentVersion,
        *version_criteria,
        DocumentVersion.object_store_key.is_not(None),
    )
    verified_versions = _count(
        db,
        DocumentVersion,
        *version_criteria,
        DocumentVersion.object_store_key.is_not(None),
        DocumentVersion.checksum_sha256.is_not(None),
        DocumentVersion.size_bytes.is_not(None),
    )
    artifacts = _count(db, Artifact, *artifact_criteria, Artifact.object_key.is_not(None))
    storage_records = (
        _count(
            db,
            RuntimePersistenceRecord,
            RuntimePersistenceRecord.runtime_domain == "storage",
            RuntimePersistenceRecord.persistence_status == "persisted",
        )
        if platform_scope
        else 0
    )
    provider_statement = select(DocumentVersion.object_store_provider).where(
        *version_criteria,
        DocumentVersion.object_store_provider.is_not(None),
    )
    provider = db.scalar(
        provider_statement
        .order_by(DocumentVersion.updated_at.desc())
        .limit(1)
    )
    external_configured = bool(getattr(settings, "object_storage_endpoint_url", ""))
    return {
        "status": "ready" if verified_versions else "not_configured",
        "provider": provider or "filesystem",
        "external_object_storage_configured": external_configured,
        "stored_document_versions": stored_versions,
        "verified_document_versions": verified_versions,
        "stored_artifacts": artifacts,
        "storage_runtime_records": storage_records,
    }


def _connector_summary(
    db: Session,
    *,
    organization_id: uuid.UUID | None,
    platform_scope: bool,
) -> dict[str, Any]:
    if platform_scope:
        types = _count(db, ConnectorType)
        connectors = _count(db, Connector)
        active_configs = _count(db, ConnectorConfig, ConnectorConfig.is_active.is_(True))
        runs = _count(db, ConnectorRun)
        failed_runs = _count(db, ConnectorRun, ConnectorRun.run_status == "failed")
        runs_by_status = _count_by(db, ConnectorRun, ConnectorRun.run_status)
    else:
        owned = Connector.organization_id == organization_id
        types = int(
            db.scalar(select(func.count(func.distinct(Connector.connector_type_id))).where(owned))
            or 0
        )
        connectors = _count(db, Connector, owned)
        active_configs = int(
            db.scalar(
                select(func.count(ConnectorConfig.id))
                .join(Connector, Connector.id == ConnectorConfig.connector_id)
                .where(owned, ConnectorConfig.is_active.is_(True))
            )
            or 0
        )
        runs = int(
            db.scalar(
                select(func.count(ConnectorRun.id))
                .join(Connector, Connector.id == ConnectorRun.connector_id)
                .where(owned)
            )
            or 0
        )
        failed_runs = int(
            db.scalar(
                select(func.count(ConnectorRun.id))
                .join(Connector, Connector.id == ConnectorRun.connector_id)
                .where(owned, ConnectorRun.run_status == "failed")
            )
            or 0
        )
        rows = db.execute(
            select(ConnectorRun.run_status, func.count(ConnectorRun.id))
            .join(Connector, Connector.id == ConnectorRun.connector_id)
            .where(owned)
            .group_by(ConnectorRun.run_status)
        ).all()
        runs_by_status = {str(status or "unknown"): int(count or 0) for status, count in rows}
    return {
        "status": "ready" if connectors and active_configs else ("not_configured" if connectors == 0 else "degraded"),
        "connector_types": types,
        "connectors": connectors,
        "active_configurations": active_configs,
        "connector_runs": runs,
        "failed_connector_runs": failed_runs,
        "runs_by_status": runs_by_status,
    }


def _runtime_execution_summary(
    db: Session,
    operations: dict[str, Any],
    *,
    organization_id: uuid.UUID | None,
    platform_scope: bool,
) -> dict[str, Any]:
    runtime = _mapping(operations.get("runtime"))
    statement = select(RuntimeExecution)
    if not platform_scope:
        statement = statement.where(RuntimeExecution.organization_id == organization_id)
    recent = db.scalars(statement.order_by(RuntimeExecution.created_at.desc()).limit(8)).all()
    return {
        "status": "ready",
        "active_executions": _int(runtime.get("active_runtime_sessions")),
        "completed_executions": _int(runtime.get("completed_runtime_sessions")),
        "failed_executions": _int(runtime.get("runtime_failures")),
        "retries": _int(runtime.get("runtime_retries")),
        "executions_by_status": _mapping(runtime.get("runtime_executions_by_status")),
        "recent_executions": [
            {
                "id": str(item.id),
                "execution_type": item.execution_type,
                "status": item.status,
                "requested_at": _iso(item.requested_at),
                "finished_at": _iso(item.finished_at),
            }
            for item in recent
        ],
    }


def _ai_summary(operations: dict[str, Any]) -> dict[str, Any]:
    assistant = _mapping(operations.get("assistant"))
    provider_calls = not bool(assistant.get("llm_disabled_indicator"))
    return {
        "status": "ready" if _int(assistant.get("assistant_executions")) >= 0 else "unavailable",
        "mode": "provider_configured" if provider_calls else "deterministic",
        "provider_configured": provider_calls,
        "ai_required": False,
        "llm_used": provider_calls,
        "assistant_executions": _int(assistant.get("assistant_executions")),
        "llm_executions": _int(assistant.get("llm_executions")),
    }


def _recent_activity(operations: dict[str, Any]) -> list[dict[str, Any]]:
    feedback = _mapping(operations.get("feedback"))
    return [
        {
            "id": str(item.get("id")),
            "resource_type": item.get("resource_type") or "platform_event",
            "summary": item.get("summary") or "Platform activity recorded.",
            "created_at": _iso(item.get("created_at")),
        }
        for item in _listing(feedback.get("recent_activity"))[:8]
        if isinstance(item, dict)
    ]


def _alerts_and_diagnostics(
    administration: dict[str, Any],
    operations: dict[str, Any],
    readiness: dict[str, bool],
) -> dict[str, Any]:
    reference_tenant = _mapping(administration.get("reference_tenant"))
    product_baseline = _mapping(reference_tenant.get("product_baseline"))
    operation_readiness = _mapping(operations.get("operational_readiness"))
    pending_capabilities = [
        *_listing(product_baseline.get("pending_capabilities")),
        *_listing(_mapping(operations.get("reference_tenant")).get("pending_capabilities")),
    ]
    blocking_issues = [
        *_listing(administration.get("blocking_issues")),
        *_listing(operations.get("blocking_issues")),
        *_listing(product_baseline.get("blocking_issues")),
    ]
    unavailable_domains = _listing(operation_readiness.get("unavailable_domains"))
    degraded_domains = sorted(domain.removesuffix("_ready") for domain, ready in readiness.items() if not ready)
    return {
        "blocking_issues": blocking_issues,
        "warnings": [
            *_listing(administration.get("warnings")),
            *_listing(operations.get("warnings")),
        ],
        "pending_capabilities": pending_capabilities,
        "unavailable_domains": unavailable_domains,
        "degraded_domains": degraded_domains,
    }


def _navigation(
    administration: dict[str, Any],
    operations: dict[str, Any],
    readiness: dict[str, bool],
    operational: dict[str, Any],
) -> list[dict[str, Any]]:
    organizations = _admin_count(administration, "organizations", "organizations")
    security = _mapping(administration.get("security"))
    security_totals = _mapping(security.get("effective_totals"))
    documents = _mapping(operations.get("documents"))
    return [
        _navigation_item("platform", "Platform", "/", ready=True),
        _navigation_item(
            "administration",
            "Administration",
            "/organization",
            ready=readiness["administration_ready"],
        ),
        _navigation_item(
            "operations",
            "Operations",
            "/operations",
            ready=readiness["operations_ready"],
        ),
        _navigation_item(
            "organizations",
            "Organizations",
            "/organization",
            ready=organizations > 0,
            count=organizations,
        ),
        _navigation_item(
            "security",
            "Security",
            "/security",
            ready=readiness["administration_ready"],
            count=_int(security_totals.get("roles")) + _int(security_totals.get("permissions")),
        ),
        _navigation_item(
            "documents",
            "Documents",
            "/documents",
            ready=readiness["documents_ready"],
            count=_int(documents.get("registered_documents")),
        ),
        _navigation_item(
            "knowledge",
            "Knowledge",
            "/knowledge",
            ready=readiness["knowledge_ready"],
            count=_int(operational.get("indexed_knowledge_documents")),
        ),
        _navigation_item(
            "search",
            "Search",
            "/search",
            ready=readiness["search_ready"],
            count=_int(_mapping(operations.get("enterprise_search")).get("search_requests")),
        ),
        _navigation_item(
            "assistants",
            "Assistants",
            "/ai",
            ready=readiness["assistant_ready"],
            count=_int(operational.get("assistant_definitions")),
        ),
        _navigation_item(
            "conversations",
            "Conversations",
            "/ai",
            ready=readiness["chat_ready"],
            count=_int(operational.get("conversations")),
        ),
        _navigation_item(
            "feedback",
            "Feedback",
            "/governance",
            ready=readiness["feedback_ready"],
            count=_int(operational.get("feedback_count")),
        ),
        _navigation_item(
            "audit",
            "Audit",
            "/governance",
            ready=readiness["audit_ready"],
            count=_int(operational.get("audit_count")),
        ),
        _navigation_item(
            "reference_tenant",
            "Reference Tenant",
            "/product",
            ready=readiness["reference_tenant_ready"],
        ),
    ]


def _recommended_next_actions(alerts: dict[str, Any], operational: dict[str, Any]) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    degraded_domains = _listing(alerts.get("degraded_domains"))
    if degraded_domains:
        actions.append(
            {
                "key": "configure_missing_domain",
                "label": "Configure missing domain",
                "reason": "One or more platform domains are not ready.",
                "domains": degraded_domains,
            }
        )
    if _listing(alerts.get("pending_capabilities")):
        actions.append(
            {
                "key": "review_pending_capabilities",
                "label": "Review pending capabilities",
                "reason": "Pending capabilities are visible in dashboard diagnostics.",
            }
        )
    if _listing(alerts.get("blocking_issues")):
        actions.append(
            {
                "key": "inspect_failed_runtime",
                "label": "Inspect failed runtime",
                "reason": "Blocking issues require runtime inspection.",
            }
        )
    if "reference_tenant" in degraded_domains:
        actions.append(
            {
                "key": "open_reference_tenant",
                "label": "Open reference tenant",
                "reason": "Reference tenant is not fully ready.",
            }
        )
    if _int(operational.get("feedback_count")) > 0:
        actions.append(
            {
                "key": "review_feedback",
                "label": "Review feedback",
                "reason": "Feedback records are available.",
            }
        )
    if _int(operational.get("audit_count")) > 0:
        actions.append(
            {
                "key": "inspect_audit_history",
                "label": "Inspect audit history",
                "reason": "Audit events are available.",
            }
        )
    if not actions:
        actions.append(
            {
                "key": "review_product_baseline",
                "label": "Review product baseline",
                "reason": "Platform dashboard is ready.",
            }
        )
    return actions


def _runtime_ready(
    readiness: dict[str, bool],
    alerts: dict[str, Any],
    *,
    platform_scope: bool,
) -> bool:
    required_domains = [
        "administration_ready",
        "operations_ready",
        "documents_ready",
        "knowledge_ready",
        "search_ready",
        "assistant_ready",
        "chat_ready",
        "feedback_ready",
        "audit_ready",
    ]
    if platform_scope:
        required_domains.append("reference_tenant_ready")
    return all(readiness.get(domain) is True for domain in required_domains) and not _listing(
        alerts.get("blocking_issues")
    )


def build_platform_dashboard_runtime(
    db: Session,
    *,
    organization_id: uuid.UUID | None = None,
    platform_scope: bool = True,
    permissions: frozenset[str] | None = None,
) -> dict[str, Any]:
    dependency_status: list[dict[str, Any]] = []
    administration, dependency = compose_runtime_dependency(
        db,
        runtime=PLATFORM_DASHBOARD_RUNTIME_NAME,
        organization_id=organization_id,
        dependency="platform_administration",
        required=True,
        builder=lambda: build_platform_administration_runtime(
            db,
            organization_id=organization_id,
            platform_scope=platform_scope,
        ),
        optional_default={},
    )
    dependency_status.append(dependency)
    operations, dependency = compose_runtime_dependency(
        db,
        runtime=PLATFORM_DASHBOARD_RUNTIME_NAME,
        organization_id=organization_id,
        dependency="platform_operations",
        required=True,
        builder=lambda: build_platform_operations_runtime(
            db,
            organization_id=organization_id,
            platform_scope=platform_scope,
        ),
        optional_default={},
    )
    dependency_status.append(dependency)
    readiness = _readiness_summary(administration, operations)
    effective_permissions = permissions or frozenset()
    authorization_evaluated = permissions is not None
    search_authorized = not authorization_evaluated or "knowledge_collections:read" in effective_permissions
    assistant_read = not authorization_evaluated or "platform.assistants:read" in effective_permissions
    assistant_administer = not authorization_evaluated or "platform.assistants:administer" in effective_permissions
    assistant_configured = bool(_listing(_mapping(administration.get("assistants")).get("assistant_definitions")))
    readiness["search_ready"] = bool(readiness.get("search_ready")) and search_authorized
    readiness["assistant_ready"] = assistant_configured and assistant_read
    readiness["chat_ready"] = assistant_configured and assistant_administer
    operational = _operational_summary(administration, operations)
    organization_summary = _organization_summary(
        db,
        organization_id=organization_id,
        platform_scope=platform_scope,
    )
    worker_summary = _worker_summary(db) if platform_scope else {}
    scheduler_summary = _scheduler_summary(db) if platform_scope else {}
    storage_summary = _storage_summary(
        db,
        organization_id=organization_id,
        platform_scope=platform_scope,
    )
    connector_summary = _connector_summary(
        db,
        organization_id=organization_id,
        platform_scope=platform_scope,
    )
    runtime_execution_summary = _runtime_execution_summary(
        db,
        operations,
        organization_id=organization_id,
        platform_scope=platform_scope,
    )
    ai_summary = _ai_summary(operations)
    alerts = _alerts_and_diagnostics(administration, operations, readiness)
    alerts["dependencies"] = dependency_status
    runtime_status = (
        "ready" if _runtime_ready(readiness, alerts, platform_scope=platform_scope) else "degraded"
    )
    return {
        "platform_dashboard_runtime_schema_version": PLATFORM_DASHBOARD_RUNTIME_SCHEMA_VERSION,
        "runtime_name": PLATFORM_DASHBOARD_RUNTIME_NAME,
        "runtime_status": runtime_status,
        "platform_summary": _platform_summary(administration, operations, runtime_status),
        "administration_summary": {
            "runtime_name": administration.get("runtime_name"),
            "runtime_status": administration.get("runtime_status"),
            "ready": administration.get("runtime_status") == "ready",
        },
        "operations_summary": {
            "runtime_name": operations.get("runtime_name"),
            "runtime_status": operations.get("runtime_status"),
            "ready": operations.get("runtime_status") == "ready",
        },
        "readiness_summary": readiness,
        "operational_summary": operational,
        "functional_capabilities": {
            "authorization_evaluated": authorization_evaluated,
            "organization_id": str(organization_id) if organization_id else None,
            "enterprise_search": {
                "available": readiness["search_ready"],
                "authorized": search_authorized,
                "reason": None if search_authorized else "knowledge_collection_read_permission_required",
            },
            "assistant_workspace": {
                "available": readiness["assistant_ready"],
                "authorized": assistant_read,
                "reason": None if assistant_read else "assistant_read_permission_required",
            },
            "conversation_chat": {
                "available": readiness["chat_ready"],
                "authorized": assistant_administer,
                "reason": None if assistant_administer else "assistant_administer_permission_required",
            },
        },
        "dashboard_sections": {
            "platform_health": {
                "status": "ready" if runtime_status == "ready" else "degraded",
                "runtime_status": runtime_status,
                "product_baseline_status": "ready"
                if _mapping(_mapping(administration.get("reference_tenant")).get("product_baseline")).get(
                    "product_baseline_ready"
                )
                else "warning",
                "postgresql_source_of_truth": True,
            },
            "organizations": organization_summary,
            "documents": _mapping(operations.get("documents")),
            "knowledge": _mapping(operations.get("knowledge")),
            "enterprise_search": _mapping(operations.get("enterprise_search")),
            "conversations": _mapping(operations.get("assistant")),
            "workers": worker_summary,
            "scheduler": scheduler_summary,
            "runtime_executions": runtime_execution_summary,
            "storage": storage_summary,
            "connectors": connector_summary,
            "ai": ai_summary,
            "recent_activity": _recent_activity(operations),
        },
        "alerts_and_diagnostics": alerts,
        "navigation": _navigation(administration, operations, readiness, operational),
        "recommended_next_actions": _recommended_next_actions(alerts, operational),
        "source_runtimes": {
            "platform_administration_runtime": {
                "schema_version": administration.get("platform_administration_runtime_schema_version"),
                "runtime_status": administration.get("runtime_status"),
            },
            "platform_operations_runtime": {
                "schema_version": operations.get("platform_operations_runtime_schema_version"),
                "runtime_status": operations.get("runtime_status"),
            },
        },
        "postgresql_source_of_truth": True,
        "ai_required": False,
        "llm_used": False,
        "embeddings_used": False,
        "qdrant_used": False,
    }
