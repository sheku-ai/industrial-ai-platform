from __future__ import annotations

import uuid
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.audit import AuditEvent
from app.models.connectors import Connector, ConnectorConfig, ConnectorRun, ConnectorType
from app.models.runtime import RuntimePersistenceRecord
from app.services.connector_configuration import (
    ConnectorConfigurationError,
    connector_is_enabled,
    connector_type_contract,
    connector_type_is_usable,
    validate_connector_configuration,
)

CONNECTOR_WORKSPACE_RUNTIME_SCHEMA_VERSION = "2"
CONNECTOR_WORKSPACE_RUNTIME_NAME = "connector_workspace_runtime"
RECENT_LIMIT = 10


def _readiness(status: str, blocking_issues: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    issues = blocking_issues or []
    return {
        "status": "blocked" if issues else status,
        "blocking_issues": issues,
    }


def _safe_error_summary(summary: dict[str, Any]) -> str | None:
    for key in ("error_summary", "error", "error_message", "failure_reason", "message"):
        value = summary.get(key)
        if value:
            return str(value)[:500]
    return None


def _duration_seconds(started_at: datetime | None, finished_at: datetime | None) -> float | None:
    if not started_at or not finished_at:
        return None
    return max((finished_at - started_at).total_seconds(), 0)


def _connector_types_payload(
    connector_types: list[ConnectorType],
    *,
    credential_resolver_types: tuple[str, ...],
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for connector_type in connector_types:
        schema = connector_type.config_schema or {}
        contract = connector_type_contract(
            connector_type,
            resolver_types=credential_resolver_types,
        )
        items.append(
            {
                "connector_type_id": connector_type.id,
                "code": connector_type.code,
                "name": connector_type.name,
                "description": connector_type.description,
                "category": connector_type.connector_kind,
                "status": connector_type.status,
                "enabled": connector_type_is_usable(connector_type),
                "configuration_schema_present": bool(schema),
                "runtime_capabilities": schema.get("runtime_capabilities") or schema.get("capabilities") or [],
                **contract,
                "readiness": _readiness(
                    "ready" if connector_type_is_usable(connector_type) else "disabled"
                ),
            }
        )
    return items


def _connector_configurations_payload(
    configs: list[ConnectorConfig],
    connector_type_by_connector: dict[Any, ConnectorType],
    connectors_by_id: dict[Any, Connector],
    *,
    credential_resolver_types: tuple[str, ...],
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for config in configs:
        connector_type = connector_type_by_connector.get(config.connector_id)
        diagnostics: list[dict[str, Any]] = []
        configuration: dict[str, Any] = {}
        configuration_status = "legacy_requires_review"
        if connector_type is None:
            diagnostics.append({"code": "connector_type_missing"})
        else:
            try:
                configuration = validate_connector_configuration(
                    connector_type,
                    config.config or {},
                    resolver_types=credential_resolver_types,
                    allow_read_only=True,
                )
                configuration_status = "valid"
            except ConnectorConfigurationError:
                diagnostics.append({"code": "legacy_connector_configuration_requires_review"})
        connector = connectors_by_id.get(config.connector_id)
        items.append(
            {
                "connector_config_id": config.id,
                "connector_id": config.connector_id,
                "configuration_version": config.version,
                "configuration_status": configuration_status,
                "configuration": configuration,
                "active": config.is_active,
                "credential_configured": bool(connector and connector.credential_reference),
                "credential_resolver_type": (
                    connector.credential_resolver_type
                    if connector and connector.credential_reference
                    else None
                ),
                "readiness": _readiness("ready" if config.is_active and not diagnostics else "pending", diagnostics),
                "diagnostics": diagnostics,
            }
        )
    return items


def _connectors_payload(
    connectors: list[Connector],
    connector_types_by_id: dict[Any, ConnectorType],
    configs_by_connector: dict[Any, list[ConnectorConfig]],
    runs_by_connector: dict[Any, list[ConnectorRun]],
    *,
    credential_resolver_types: tuple[str, ...],
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for connector in connectors:
        connector_type = connector_types_by_id.get(connector.connector_type_id)
        connector_runs = sorted(
            runs_by_connector.get(connector.id, []),
            key=lambda item: item.created_at,
            reverse=True,
        )
        last_run = connector_runs[0] if connector_runs else None
        connector_configs = sorted(
            configs_by_connector.get(connector.id, []),
            key=lambda item: (item.is_active, item.version, item.created_at),
            reverse=True,
        )
        current_config = connector_configs[0] if connector_configs else None
        configuration: dict[str, Any] = {}
        configuration_validation_status = "valid"
        blocking_issues = []
        if connector_type is None:
            blocking_issues.append({"code": "connector_type_missing"})
            configuration_validation_status = "legacy_requires_review"
        else:
            try:
                configuration = validate_connector_configuration(
                    connector_type,
                    current_config.config if current_config else {},
                    resolver_types=credential_resolver_types,
                    allow_read_only=True,
                )
            except ConnectorConfigurationError:
                configuration_validation_status = "legacy_requires_review"
                blocking_issues.append({"code": "legacy_connector_configuration_requires_review"})
        items.append(
            {
                "connector_id": connector.id,
                "connector_type_id": connector.connector_type_id,
                "code": connector.code,
                "name": connector.name,
                "status": connector.status,
                "enabled": connector_is_enabled(connector.status),
                "organization_id": connector.organization_id,
                "collection_id": (connector.config or {}).get("collection_id"),
                "configuration_status": "configured" if current_config else "not_configured",
                "configuration_validation_status": configuration_validation_status,
                "configuration_version": current_config.version if current_config else 0,
                "configuration": configuration,
                "credential_configured": bool(connector.credential_reference),
                "credential_resolver_type": (
                    connector.credential_resolver_type
                    if connector.credential_reference
                    else None
                ),
                "last_run_status": last_run.run_status if last_run else None,
                "last_run_at": last_run.finished_at or last_run.started_at if last_run else None,
                "readiness": _readiness(
                    "ready"
                    if connector_is_enabled(connector.status)
                    and current_config is not None
                    and not blocking_issues
                    else "pending",
                    blocking_issues,
                ),
            }
        )
    return items


def _connector_runs_payload(runs: list[ConnectorRun]) -> dict[str, Any]:
    runs_by_status = Counter(str(run.run_status or "unknown").lower() for run in runs)
    recent_runs = sorted(runs, key=lambda item: item.created_at, reverse=True)[:RECENT_LIMIT]
    return {
        "total_runs": len(runs),
        "running_runs": runs_by_status.get("running", 0),
        "successful_runs": sum(runs_by_status.get(status, 0) for status in ("success", "succeeded", "completed")),
        "failed_runs": sum(runs_by_status.get(status, 0) for status in ("failed", "error")),
        "pending_runs": runs_by_status.get("pending", 0),
        "cancelled_runs": sum(runs_by_status.get(status, 0) for status in ("cancelled", "canceled")),
        "last_run": _run_item(recent_runs[0]) if recent_runs else None,
        "runs_by_status": dict(runs_by_status),
        "recent_runs": [_run_item(run) for run in recent_runs],
    }


def _run_item(run: ConnectorRun) -> dict[str, Any]:
    summary = run.summary or {}
    return {
        "connector_run_id": run.id,
        "connector_id": run.connector_id,
        "status": run.run_status,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "duration": _duration_seconds(run.started_at, run.finished_at),
        "records_seen": summary.get("records_seen"),
        "records_processed": summary.get("records_processed"),
        "records_failed": summary.get("records_failed"),
        "error_summary": _safe_error_summary(summary),
    }


def _sync_ingestion_impact(runs: list[ConnectorRun]) -> dict[str, Any]:
    totals = {
        "documents_created": 0,
        "documents_updated": 0,
        "knowledge_publications_triggered": 0,
        "index_updates_triggered": 0,
    }
    observed = False
    for run in runs:
        summary = run.summary or {}
        for key in totals:
            value = summary.get(key)
            if isinstance(value, int | float):
                totals[key] += int(value)
                observed = True
    return {
        **totals,
        "sync_health": "observed" if observed else "pending",
        "pending_capabilities": []
        if observed
        else [{"code": "connector_sync_impact_not_reported", "reason": "connector_run_summary_has_no_sync_metrics"}],
    }


def _audit_trace(audit_events: list[AuditEvent], runtime_records: list[RuntimePersistenceRecord]) -> dict[str, Any]:
    connector_audit = [
        event for event in audit_events if str(event.resource_type or "").lower().startswith("connector")
    ]
    recent_audit = sorted(connector_audit, key=lambda item: item.created_at, reverse=True)[:RECENT_LIMIT]
    return {
        "audit_events_count": len(connector_audit),
        "recent_audit_events": [
            {
                "audit_event_id": event.id,
                "resource_type": event.resource_type,
                "resource_id": event.resource_id,
                "summary": event.summary,
                "created_at": event.created_at,
            }
            for event in recent_audit
        ],
        "runtime_trace_available": bool(runtime_records),
        "recent_runtime_records": [
            {
                "runtime_record_id": record.id,
                "runtime_domain": record.runtime_domain,
                "record_type": record.record_type,
                "record_key": record.record_key,
                "execution_status": record.execution_status,
                "persistence_status": record.persistence_status,
                "occurred_at": record.occurred_at,
            }
            for record in sorted(runtime_records, key=lambda item: item.occurred_at, reverse=True)[:RECENT_LIMIT]
        ],
    }


def build_connector_workspace_runtime(
    db: Session,
    *,
    organization_id: uuid.UUID | None = None,
    platform_scope: bool = True,
    capabilities: dict[str, bool] | None = None,
    credential_resolver_types: tuple[str, ...] = (),
) -> dict[str, Any]:
    connector_types = list(db.scalars(select(ConnectorType).order_by(ConnectorType.code.asc())).all())
    connector_statement = select(Connector)
    if not platform_scope:
        connector_statement = connector_statement.where(Connector.organization_id == organization_id)
    connectors = list(db.scalars(connector_statement.order_by(Connector.code.asc())).all())
    connector_ids = [connector.id for connector in connectors]
    configuration_statement = select(ConnectorConfig).where(
        ConnectorConfig.connector_id.in_(connector_ids)
    )
    run_statement = select(ConnectorRun).where(
        ConnectorRun.connector_id.in_(connector_ids)
    )
    if not platform_scope:
        configuration_statement = (
            configuration_statement
            .join(Connector, Connector.id == ConnectorConfig.connector_id)
            .where(Connector.organization_id == organization_id)
        )
        run_statement = (
            run_statement
            .join(Connector, Connector.id == ConnectorRun.connector_id)
            .where(Connector.organization_id == organization_id)
        )
    configs = list(
        db.scalars(
            configuration_statement.order_by(ConnectorConfig.created_at.desc())
        ).all()
    )
    runs = list(
        db.scalars(
            run_statement.order_by(ConnectorRun.created_at.desc())
        ).all()
    )
    audit_statement = select(AuditEvent)
    if not platform_scope:
        audit_statement = audit_statement.where(AuditEvent.organization_id == organization_id)
    audit_events = list(db.scalars(audit_statement.order_by(AuditEvent.created_at.desc())).all())
    runtime_records = (
        list(
            db.scalars(
                select(RuntimePersistenceRecord).where(
                    RuntimePersistenceRecord.runtime_domain.in_(
                        [
                            "processing",
                            "knowledge_publication",
                            "knowledge_index",
                            "enterprise_search",
                            "runtime_persistence",
                        ]
                    )
                )
            ).all()
        )
        if platform_scope
        else []
    )

    connector_types_by_id = {item.id: item for item in connector_types}
    connectors_by_id = {item.id: item for item in connectors}
    configs_by_connector: dict[Any, list[ConnectorConfig]] = defaultdict(list)
    for config in configs:
        configs_by_connector[config.connector_id].append(config)
    runs_by_connector: dict[Any, list[ConnectorRun]] = defaultdict(list)
    for run in runs:
        runs_by_connector[run.connector_id].append(run)
    connector_type_by_connector = {
        connector.id: connector_types_by_id.get(connector.connector_type_id) for connector in connectors
    }

    sync_impact = _sync_ingestion_impact(runs)
    audit_trace = _audit_trace(audit_events, runtime_records)
    connector_types_ready = bool(connector_types)
    connectors_ready = bool(connectors)
    connector_configs_ready = bool(configs) or not connectors
    connector_runs_ready = bool(runs)
    audit_ready = True
    degraded_items = []
    for key, ready in {
        "connector_types": connector_types_ready,
        "connectors": connectors_ready,
        "connector_configurations": connector_configs_ready,
        "connector_runs": connector_runs_ready,
    }.items():
        if not ready:
            degraded_items.append({"item_type": "domain", "item_id": key, "status": "pending"})
    pending_capabilities = list(sync_impact.get("pending_capabilities") or [])
    runtime_status = "ready" if connector_types_ready and connectors_ready else "degraded"
    return {
        "connector_workspace_runtime_schema_version": CONNECTOR_WORKSPACE_RUNTIME_SCHEMA_VERSION,
        "runtime_name": CONNECTOR_WORKSPACE_RUNTIME_NAME,
        "runtime_status": runtime_status,
        "capabilities": capabilities or {},
        "credential_resolver_types": list(credential_resolver_types),
        "workspace_summary": {
            "runtime_status": runtime_status,
            "connectors_ready": connectors_ready,
            "connector_types_ready": connector_types_ready,
            "connector_configs_ready": connector_configs_ready,
            "connector_runs_ready": connector_runs_ready,
            "audit_ready": audit_ready,
            "postgresql_source_of_truth": True,
            "external_calls_performed": False,
            "llm_used": False,
            "qdrant_used": False,
        },
        "connector_types": _connector_types_payload(
            connector_types,
            credential_resolver_types=credential_resolver_types,
        ),
        "connectors": _connectors_payload(
            connectors,
            connector_types_by_id,
            configs_by_connector,
            runs_by_connector,
            credential_resolver_types=credential_resolver_types,
        ),
        "connector_configurations": _connector_configurations_payload(
            [
                sorted(
                    values,
                    key=lambda item: (item.is_active, item.version, item.created_at),
                    reverse=True,
                )[0]
                for values in configs_by_connector.values()
                if values
            ],
            connector_type_by_connector,
            connectors_by_id,
            credential_resolver_types=credential_resolver_types,
        ),
        "connector_runs": _connector_runs_payload(runs),
        "sync_ingestion_impact": sync_impact,
        "audit_trace": audit_trace,
        "diagnostics": {
            "blocking_issues": [],
            "warnings": [],
            "pending_capabilities": pending_capabilities,
            "degraded_items": degraded_items,
        },
        "postgresql_source_of_truth": True,
        "external_calls_performed": False,
        "llm_used": False,
        "qdrant_used": False,
    }
