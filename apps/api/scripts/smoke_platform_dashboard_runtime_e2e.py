#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any

API_BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000/api").rstrip("/")


def http_get_json(path: str) -> dict[str, Any]:
    request = urllib.request.Request(
        f"{API_BASE_URL}{path}",
        headers={"Accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8")
        try:
            parsed: Any = json.loads(details)
        except json.JSONDecodeError:
            parsed = details
        return {"_http_error": True, "status_code": exc.code, "details": parsed}
    except urllib.error.URLError as exc:
        return {"_http_error": True, "error": "connection_failed", "details": str(exc)}


def _mapping(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    return value if isinstance(value, dict) else {}


def _list(payload: dict[str, Any], key: str) -> list[Any]:
    value = payload.get(key)
    return value if isinstance(value, list) else []


def main() -> int:
    payload = http_get_json("/platform/dashboard/runtime")
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    if payload.get("_http_error"):
        errors.append({"code": "platform_dashboard_runtime_unavailable", "details": payload})
        result = {
            "passed": False,
            "api_base_url": API_BASE_URL,
            "runtime_returned": False,
            "warnings": warnings,
            "errors": errors,
        }
        print(json.dumps(result, indent=2, sort_keys=True, default=str))
        return 1

    platform_summary = _mapping(payload, "platform_summary")
    administration_summary = _mapping(payload, "administration_summary")
    operations_summary = _mapping(payload, "operations_summary")
    readiness_summary = _mapping(payload, "readiness_summary")
    dashboard_sections = _mapping(payload, "dashboard_sections")
    navigation = _list(payload, "navigation")
    navigation_keys = {
        item.get("key") for item in navigation if isinstance(item, dict) and isinstance(item.get("key"), str)
    }
    core_domains = {
        "platform",
        "administration",
        "operations",
        "organizations",
        "security",
        "documents",
        "knowledge",
        "search",
        "assistants",
        "conversations",
        "feedback",
        "audit",
        "reference_tenant",
    }
    missing_core_domains = sorted(core_domains - navigation_keys)
    checks = {
        "runtime_returned": True,
        "runtime_status_ready": payload.get("runtime_status") == "ready",
        "product_baseline_present": bool(platform_summary.get("product_baseline_status")),
        "administration_summary_exists": bool(administration_summary),
        "operations_summary_exists": bool(operations_summary),
        "readiness_summary_exists": bool(readiness_summary),
        "dashboard_sections_exists": bool(dashboard_sections),
        "platform_health_exists": bool(_mapping(dashboard_sections, "platform_health")),
        "organizations_exists": bool(_mapping(dashboard_sections, "organizations")),
        "documents_exists": bool(_mapping(dashboard_sections, "documents")),
        "knowledge_exists": bool(_mapping(dashboard_sections, "knowledge")),
        "enterprise_search_exists": bool(_mapping(dashboard_sections, "enterprise_search")),
        "conversations_exists": bool(_mapping(dashboard_sections, "conversations")),
        "workers_exists": bool(_mapping(dashboard_sections, "workers")),
        "scheduler_exists": bool(_mapping(dashboard_sections, "scheduler")),
        "runtime_executions_exists": bool(_mapping(dashboard_sections, "runtime_executions")),
        "storage_exists": bool(_mapping(dashboard_sections, "storage")),
        "connectors_exists": bool(_mapping(dashboard_sections, "connectors")),
        "ai_exists": bool(_mapping(dashboard_sections, "ai")),
        "recent_activity_exists": isinstance(dashboard_sections.get("recent_activity"), list),
        "navigation_model_exists": bool(navigation),
        "core_domains_present": not missing_core_domains,
        "postgresql_source_of_truth": payload.get("postgresql_source_of_truth") is True,
        "llm_used": payload.get("llm_used") is True,
        "qdrant_used": payload.get("qdrant_used") is True,
    }
    if not checks["runtime_status_ready"]:
        errors.append(
            {
                "code": "platform_dashboard_runtime_not_ready",
                "runtime_status": payload.get("runtime_status"),
                "readiness_summary": readiness_summary,
            }
        )
    if not checks["product_baseline_present"]:
        errors.append({"code": "product_baseline_missing"})
    if not checks["administration_summary_exists"]:
        errors.append({"code": "administration_summary_missing"})
    if not checks["operations_summary_exists"]:
        errors.append({"code": "operations_summary_missing"})
    if not checks["readiness_summary_exists"]:
        errors.append({"code": "readiness_summary_missing"})
    for check_name, error_code in (
        ("dashboard_sections_exists", "dashboard_sections_missing"),
        ("platform_health_exists", "platform_health_missing"),
        ("organizations_exists", "organizations_section_missing"),
        ("documents_exists", "documents_section_missing"),
        ("knowledge_exists", "knowledge_section_missing"),
        ("enterprise_search_exists", "enterprise_search_section_missing"),
        ("conversations_exists", "conversations_section_missing"),
        ("workers_exists", "workers_section_missing"),
        ("scheduler_exists", "scheduler_section_missing"),
        ("runtime_executions_exists", "runtime_executions_section_missing"),
        ("storage_exists", "storage_section_missing"),
        ("connectors_exists", "connectors_section_missing"),
        ("ai_exists", "ai_section_missing"),
        ("recent_activity_exists", "recent_activity_section_missing"),
    ):
        if not checks[check_name]:
            errors.append({"code": error_code})
    if not checks["navigation_model_exists"]:
        errors.append({"code": "navigation_model_missing"})
    if missing_core_domains:
        errors.append({"code": "core_navigation_domains_missing", "domains": missing_core_domains})
    if not checks["postgresql_source_of_truth"]:
        errors.append({"code": "postgresql_source_of_truth_not_confirmed"})
    for flag in ("llm_used", "qdrant_used"):
        if checks[flag]:
            errors.append(
                {
                    "code": flag,
                    "message": "Platform Dashboard Runtime must not execute AI or vector infrastructure.",
                }
            )

    diagnostics = _mapping(payload, "alerts_and_diagnostics")
    warnings.extend(diagnostics.get("warnings") or [])
    result = {
        "passed": not errors,
        "api_base_url": API_BASE_URL,
        "runtime_returned": checks["runtime_returned"],
        "runtime_status": payload.get("runtime_status"),
        "product_baseline_present": checks["product_baseline_present"],
        "administration_summary_exists": checks["administration_summary_exists"],
        "operations_summary_exists": checks["operations_summary_exists"],
        "readiness_summary_exists": checks["readiness_summary_exists"],
        "dashboard_sections_exists": checks["dashboard_sections_exists"],
        "platform_health_exists": checks["platform_health_exists"],
        "organizations_exists": checks["organizations_exists"],
        "documents_exists": checks["documents_exists"],
        "knowledge_exists": checks["knowledge_exists"],
        "enterprise_search_exists": checks["enterprise_search_exists"],
        "conversations_exists": checks["conversations_exists"],
        "workers_exists": checks["workers_exists"],
        "scheduler_exists": checks["scheduler_exists"],
        "runtime_executions_exists": checks["runtime_executions_exists"],
        "storage_exists": checks["storage_exists"],
        "connectors_exists": checks["connectors_exists"],
        "ai_exists": checks["ai_exists"],
        "recent_activity_exists": checks["recent_activity_exists"],
        "navigation_model_exists": checks["navigation_model_exists"],
        "core_domains_present": checks["core_domains_present"],
        "missing_core_domains": missing_core_domains,
        "postgresql_source_of_truth": checks["postgresql_source_of_truth"],
        "llm_used": checks["llm_used"],
        "qdrant_used": checks["qdrant_used"],
        "warnings": warnings,
        "errors": errors,
    }
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
