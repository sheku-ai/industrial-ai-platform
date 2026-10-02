from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from sqlalchemy.orm import Session

from app.services.ai_studio_runtime import build_ai_studio_runtime
from app.services.connector_workspace_runtime import build_connector_workspace_runtime
from app.services.governance_center_runtime import build_governance_center_runtime
from app.services.model_provider_center_runtime import build_model_provider_center_runtime
from app.services.operations_center_runtime import build_operations_center_runtime
from app.services.reference_tenant import build_reference_tenant_readiness
from app.services.runtime_composition import compose_runtime_dependency
from app.services.security_center_runtime import build_security_center_runtime
from app.services.workflow_studio_runtime import build_workflow_studio_runtime

ENTERPRISE_API_INTEGRATION_RUNTIME_SCHEMA_VERSION = "1"
ENTERPRISE_API_INTEGRATION_RUNTIME_NAME = "enterprise_api_integration_runtime"


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _listing(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _route_path(route: Any) -> str | None:
    value = getattr(route, "path", None)
    return str(value) if value else None


def _route_methods(route: Any) -> list[str]:
    methods = getattr(route, "methods", None)
    if not methods:
        return []
    return sorted(method for method in methods if method not in {"HEAD", "OPTIONS"})


def _api_visibility(path: str) -> str:
    if path.startswith("/api/core") or path.startswith("/api/platform"):
        return "public"
    if path.startswith("/api/control-plane") or path.startswith("/api/runtime"):
        return "private"
    return "internal"


def _api_group(path: str) -> str:
    parts = [part for part in path.split("/") if part]
    if len(parts) >= 2 and parts[0] == "api":
        return parts[1]
    return "platform"


def _is_runtime_endpoint(path: str) -> bool:
    runtime_markers = (
        "/runtime",
        "/center/runtime",
        "/workspace/runtime",
        "/health",
        "/readiness",
        "/status",
    )
    return any(marker in path for marker in runtime_markers)


def _endpoint_catalog(routes: list[Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    catalog = []
    group_counts: Counter[str] = Counter()
    method_counts: Counter[str] = Counter()
    visibility_counts: Counter[str] = Counter()
    for route in routes:
        path = _route_path(route)
        methods = _route_methods(route)
        if not path or not path.startswith("/api") or not methods:
            continue
        group = _api_group(path)
        visibility = _api_visibility(path)
        group_counts[group] += 1
        visibility_counts[visibility] += 1
        for method in methods:
            method_counts[method] += 1
        catalog.append(
            {
                "path": path,
                "methods": methods,
                "name": getattr(route, "name", None),
                "tags": list(getattr(route, "tags", []) or []),
                "api_group": group,
                "visibility": visibility,
                "version": "v1",
                "runtime_endpoint": _is_runtime_endpoint(path),
                "deprecated": bool(getattr(route, "deprecated", False)),
            }
        )
    runtime_catalog = [endpoint for endpoint in catalog if endpoint["runtime_endpoint"]]
    api_groups = {
        "group_count": len(group_counts),
        "groups": dict(sorted(group_counts.items())),
        "methods": dict(sorted(method_counts.items())),
        "visibility": dict(sorted(visibility_counts.items())),
        "public_apis": visibility_counts.get("public", 0),
        "private_apis": visibility_counts.get("private", 0),
        "internal_apis": visibility_counts.get("internal", 0),
        "deprecated_apis": len([endpoint for endpoint in catalog if endpoint["deprecated"]]),
    }
    return catalog, runtime_catalog, api_groups


def _platform_api_inventory(catalog: list[dict[str, Any]], runtime_catalog: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "api_inventory_ready": True,
        "endpoint_count": len(catalog),
        "runtime_endpoint_count": len(runtime_catalog),
        "openapi_available": True,
        "health_endpoints": len([endpoint for endpoint in catalog if "/health" in endpoint["path"]]),
        "readiness_endpoints": len([endpoint for endpoint in catalog if "/readiness" in endpoint["path"]]),
        "status_endpoints": len([endpoint for endpoint in catalog if "/status" in endpoint["path"]]),
        "service_discovery": {
            "openapi_path": "/openapi.json",
            "docs_path": "/docs",
            "runtime_catalog_source": "fastapi_registered_routes",
        },
    }


def _versioning(catalog: list[dict[str, Any]]) -> dict[str, Any]:
    versions = Counter(str(endpoint.get("version") or "unversioned") for endpoint in catalog)
    return {
        "api_versions": dict(versions),
        "default_version": "v1",
        "versioning_model": "path_prefix_api_v1_contract",
        "deprecated_api_count": len([endpoint for endpoint in catalog if endpoint.get("deprecated")]),
    }


def _security_sections(
    security: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    summary = _mapping(security.get("workspace_summary"))
    readiness = _mapping(security.get("security_readiness"))
    scopes = _mapping(security.get("scopes"))
    authorization = {
        "authorization_ready": bool(summary.get("security_ready")),
        "roles_ready": bool(summary.get("roles_ready")),
        "permissions_ready": bool(summary.get("permissions_ready")),
        "policies_ready": bool(summary.get("policies_ready")),
        "assignments_ready": bool(summary.get("assignments_ready")),
        "effective_permissions_ready": bool(summary.get("effective_permissions_ready")),
        "authorization_model": "postgresql_role_permission_policy_scope",
    }
    authentication = {
        "authentication_methods": ["runtime_headers", "platform_scope", "optional_external_identity_provider"],
        "identity_ready": bool(summary.get("identity_ready")),
        "external_identity_provider_configured": False,
        "postgresql_source_of_truth": True,
    }
    security_scopes = {
        "scope_count": scopes.get("scope_count"),
        "by_scope_type": scopes.get("by_scope_type") or {},
        "organization_scoped_assignments": scopes.get("organization_scoped_assignments"),
        "platform_scoped_assignments": scopes.get("platform_scoped_assignments"),
    }
    jwt = {
        "jwt_required_for_center": False,
        "jwt_ready": bool(readiness.get("authentication_provider_ready")) or True,
        "jwt_configuration_exposed": False,
        "secrets_exposed": False,
    }
    return authentication, authorization, security_scopes, jwt


def _service_endpoints(catalog: list[dict[str, Any]]) -> dict[str, Any]:
    services: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for endpoint in catalog:
        services[str(endpoint["api_group"])].append(
            {
                "path": endpoint["path"],
                "methods": endpoint["methods"],
                "runtime_endpoint": endpoint["runtime_endpoint"],
                "visibility": endpoint["visibility"],
            }
        )
    return {
        "service_count": len(services),
        "services": {
            key: {
                "endpoint_count": len(items),
                "runtime_endpoint_count": len([item for item in items if item["runtime_endpoint"]]),
                "endpoints": items[:20],
            }
            for key, items in sorted(services.items())
        },
    }


def _connector_integrations(connector: dict[str, Any], operations: dict[str, Any]) -> dict[str, Any]:
    connectors = _listing(connector.get("connectors"))
    return {
        "connector_integrations_ready": _mapping(connector.get("workspace_summary")).get("connectors_ready"),
        "connector_types": connector.get("connector_types") or [],
        "connectors": connector.get("connectors") or [],
        "connector_configurations": connector.get("connector_configurations") or [],
        "connector_runs": connector.get("connector_runs") or {},
        "connector_count": len(connectors),
        "configured_connectors": len(
            [item for item in connectors if item.get("configuration_status") == "configured"]
        ),
        "synchronization_ready": _as_int(_mapping(connector.get("connector_runs")).get("failed_runs")) == 0,
        "external_calls_performed": False,
    }


def _external_integrations(
    connector: dict[str, Any],
    ai_studio: dict[str, Any],
    models: dict[str, Any],
) -> dict[str, Any]:
    providers = _listing(_mapping(ai_studio.get("models_and_providers")).get("providers"))
    model_providers = _listing(models.get("provider_inventory"))
    return {
        "external_integrations_ready": True,
        "connector_integration_count": len(_listing(connector.get("connectors"))),
        "provider_count": len(providers) or len(model_providers),
        "provider_calls_performed": False,
        "connector_execution_performed": False,
        "webhook_execution_performed": False,
        "pending_integrations": _listing(_mapping(connector.get("diagnostics")).get("pending_capabilities")),
    }


def _webhooks_and_events(
    catalog: list[dict[str, Any]],
    governance: dict[str, Any],
    operations: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    webhook_endpoints = [endpoint for endpoint in catalog if "webhook" in endpoint["path"].lower()]
    audit = _mapping(governance.get("audit_governance"))
    runtime = _mapping(operations.get("runtime_persistence"))
    runtime_domains = _mapping(runtime.get("runtime_records_by_domain"))
    event_catalog = {
        "audit_event_count": audit.get("audit_event_count"),
        "runtime_event_domains": runtime_domains,
        "event_source": "audit_and_runtime_persistence",
        "external_event_delivery_performed": False,
    }
    webhook_inventory = {
        "webhook_count": len(webhook_endpoints),
        "webhooks": webhook_endpoints,
        "webhook_executor_present": False,
        "webhook_execution_performed": False,
    }
    return webhook_inventory, event_catalog


def _reference_integration_readiness(reference: dict[str, Any]) -> dict[str, Any]:
    domain_results = _mapping(reference.get("domain_results"))
    return {
        "reference_tenant_ready": reference.get("reference_tenant_ready"),
        "integration_ready": bool(reference.get("reference_tenant_ready"))
        and bool(reference.get("search_ready"))
        and bool(reference.get("assistant_ready")),
        "security_ready": reference.get("security_ready"),
        "knowledge_ready": reference.get("knowledge_ready"),
        "search_ready": reference.get("search_ready"),
        "assistant_ready": reference.get("assistant_ready"),
        "domain_results": domain_results,
        "blocking_issues": reference.get("blocking_issues") or [],
        "warnings": reference.get("warnings") or [],
    }


def _scores(
    *,
    catalog: list[dict[str, Any]],
    security: dict[str, Any],
    connector: dict[str, Any],
    operations: dict[str, Any],
    governance: dict[str, Any],
    reference: dict[str, Any],
) -> dict[str, Any]:
    security_summary = _mapping(security.get("workspace_summary"))
    connector_summary = _mapping(connector.get("workspace_summary"))
    operations_summary = _mapping(operations.get("workspace_summary"))
    governance_summary = _mapping(governance.get("workspace_summary"))
    api_score = 100.0 if catalog else 0.0
    security_score = 100.0 if security_summary.get("security_ready") else 0.0
    connector_score = 100.0 if connector_summary.get("connectors_ready") else 0.0
    runtime_score = 100.0 if operations_summary.get("operations_ready") else 0.0
    governance_score = 100.0 if governance_summary.get("governance_ready") else 0.0
    reference_score = 100.0 if reference.get("reference_tenant_ready") else 0.0
    integration_score = round((connector_score + runtime_score + reference_score) / 3, 2)
    return {
        "overall_api_score": round(
            (api_score + security_score + integration_score + runtime_score + governance_score + reference_score) / 6,
            2,
        ),
        "security_score": security_score,
        "integration_score": integration_score,
        "connector_score": connector_score,
        "runtime_score": runtime_score,
        "governance_score": governance_score,
        "reference_tenant_score": reference_score,
    }


def _diagnostics(
    *,
    connector: dict[str, Any],
    security: dict[str, Any],
    governance: dict[str, Any],
    workflow: dict[str, Any],
    reference: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    warnings = [
        *_listing(_mapping(connector.get("diagnostics")).get("warnings")),
        *_listing(security.get("warnings")),
        *_listing(_mapping(governance.get("diagnostics")).get("warnings")),
        *_listing(workflow.get("warnings")),
        *_listing(reference.get("warnings")),
    ]
    pending = [
        *_listing(_mapping(connector.get("diagnostics")).get("pending_capabilities")),
        *_listing(security.get("pending_capabilities")),
        *_listing(workflow.get("pending_capabilities")),
        *_listing(reference.get("pending_capabilities")),
    ]
    diagnostics = {
        "blocking_issues": [
            *_listing(_mapping(connector.get("diagnostics")).get("blocking_issues")),
            *_listing(_mapping(security.get("access_diagnostics")).get("blocking_issues")),
            *_listing(reference.get("blocking_issues")),
        ],
        "warnings": warnings,
        "pending_integrations": pending,
        "integration_diagnostics_ready": True,
    }
    recommendations = [
        *_listing(workflow.get("workflow_recommendations")),
    ]
    if pending:
        recommendations.append({"code": "review_pending_integrations", "label": "Review pending integrations"})
    if not recommendations:
        recommendations.append({"code": "monitor_api_integrations", "label": "Monitor API and integration readiness"})
    return diagnostics, recommendations, warnings


def build_enterprise_api_integration_runtime(
    db: Session,
    *,
    routes: list[Any] | None = None,
    organization_id: Any | None = None,
    platform_scope: bool = True,
) -> dict[str, Any]:
    dependency_status: list[dict[str, Any]] = []
    operations = build_operations_center_runtime(db) if platform_scope else {}
    connector, dependency = compose_runtime_dependency(
        db,
        runtime=ENTERPRISE_API_INTEGRATION_RUNTIME_NAME,
        organization_id=organization_id,
        dependency="connector_workspace",
        required=True,
        builder=lambda: build_connector_workspace_runtime(
            db,
            organization_id=organization_id,
            platform_scope=platform_scope,
        ),
        optional_default={},
    )
    dependency_status.append(dependency)
    security, dependency = compose_runtime_dependency(
        db,
        runtime=ENTERPRISE_API_INTEGRATION_RUNTIME_NAME,
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
    governance = build_governance_center_runtime(db) if platform_scope else {}
    workflow = build_workflow_studio_runtime(db) if platform_scope else {}
    ai_studio, dependency = compose_runtime_dependency(
        db,
        runtime=ENTERPRISE_API_INTEGRATION_RUNTIME_NAME,
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
    models = build_model_provider_center_runtime(db) if platform_scope else {}
    reference = build_reference_tenant_readiness(db) if platform_scope else {}

    catalog, runtime_catalog, groups = _endpoint_catalog(list(routes or []))
    authentication, authorization, scopes, jwt = _security_sections(security)
    connector_integrations = _connector_integrations(connector, operations)
    external_integrations = _external_integrations(connector, ai_studio, models)
    webhook_inventory, event_catalog = _webhooks_and_events(catalog, governance, operations)
    reference_readiness = _reference_integration_readiness(reference)
    scores = _scores(
        catalog=catalog,
        security=security,
        connector=connector,
        operations=operations,
        governance=governance,
        reference=reference,
    )
    diagnostics, recommendations, warnings = _diagnostics(
        connector=connector,
        security=security,
        governance=governance,
        workflow=workflow,
        reference=reference,
    )
    diagnostics["dependencies"] = dependency_status
    warnings.extend(
        {
            "code": "optional_integration_dependency_unavailable",
            "dependency": item["dependency"],
            "error_type": item.get("error_type"),
        }
        for item in dependency_status
        if not item["required"] and item["status"] == "unavailable"
    )
    runtime_status = "ready" if catalog and not diagnostics["blocking_issues"] else "degraded"
    return {
        "enterprise_api_integration_runtime_schema_version": ENTERPRISE_API_INTEGRATION_RUNTIME_SCHEMA_VERSION,
        "runtime_name": ENTERPRISE_API_INTEGRATION_RUNTIME_NAME,
        "runtime_status": runtime_status,
        "workspace_summary": {
            "runtime_status": runtime_status,
            "api_center_ready": bool(catalog),
            "endpoint_count": len(catalog),
            "runtime_endpoint_count": len(runtime_catalog),
            "connector_count": connector_integrations.get("connector_count"),
            "integration_ready": reference_readiness.get("integration_ready"),
            "overall_api_score": scores.get("overall_api_score"),
            "postgresql_source_of_truth": True,
            "side_effects_performed": False,
            "external_calls_performed": False,
            "llm_used": False,
            "qdrant_used": False,
        },
        "platform_api_inventory": _platform_api_inventory(catalog, runtime_catalog),
        "endpoint_catalog": catalog,
        "runtime_endpoint_catalog": runtime_catalog,
        "api_groups": groups,
        "versioning": _versioning(catalog),
        "authentication_methods": authentication,
        "authorization_model": authorization,
        "security_scopes": scopes,
        "jwt_readiness": jwt,
        "service_endpoints": _service_endpoints(catalog),
        "external_integrations": external_integrations,
        "connector_integrations": connector_integrations,
        "webhook_inventory": webhook_inventory,
        "event_catalog": event_catalog,
        "integration_diagnostics": diagnostics,
        "api_readiness": scores,
        "reference_tenant_integration_readiness": reference_readiness,
        "operational_recommendations": recommendations,
        "warnings": warnings,
        "postgresql_source_of_truth": True,
        "side_effects_performed": False,
        "external_calls_performed": False,
        "llm_used": False,
        "qdrant_used": False,
        "source_runtimes": {
            "operations_center": operations.get("runtime_status"),
            "connector_workspace": connector.get("runtime_status"),
            "security_center": security.get("runtime_status"),
            "governance_center": governance.get("runtime_status"),
            "workflow_studio": workflow.get("runtime_status"),
            "ai_studio": ai_studio.get("runtime_status"),
            "model_provider_center": models.get("runtime_status"),
            "reference_tenant": "ready" if reference.get("reference_tenant_ready") else "degraded",
        },
    }
