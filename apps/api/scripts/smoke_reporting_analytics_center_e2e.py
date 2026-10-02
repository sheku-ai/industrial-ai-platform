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


def _listing(payload: dict[str, Any], key: str) -> list[Any]:
    value = payload.get(key)
    return value if isinstance(value, list) else []


def main() -> int:
    payload = http_get_json("/reporting/analytics/center/runtime")
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    if payload.get("_http_error"):
        errors.append({"code": "reporting_analytics_center_unavailable", "details": payload})
        result = {
            "passed": False,
            "api_base_url": API_BASE_URL,
            "endpoint_reachable": False,
            "warnings": warnings,
            "errors": errors,
        }
        print(json.dumps(result, indent=2, sort_keys=True, default=str))
        return 1

    analytics_sections = (
        "document_analytics",
        "knowledge_analytics",
        "enterprise_search_analytics",
        "assistant_analytics",
        "conversation_analytics",
        "workflow_analytics",
        "scheduler_analytics",
        "background_services_analytics",
        "connector_analytics",
        "security_analytics",
        "governance_analytics",
        "audit_analytics",
        "feedback_analytics",
    )
    trend_sections = (
        "product_readiness_trends",
        "runtime_health_trends",
        "operational_trends",
    )
    checks = {
        "endpoint_reachable": True,
        "workspace_summary_present": bool(_mapping(payload, "workspace_summary")),
        "executive_kpis_present": bool(_mapping(payload, "executive_kpis")),
        "analytics_sections_present": all(bool(_mapping(payload, key)) for key in analytics_sections),
        "trend_sections_present": all(bool(_mapping(payload, key)) for key in trend_sections),
        "reference_tenant_analytics_present": bool(_mapping(payload, "reference_tenant_analytics")),
        "readiness_present": bool(_mapping(payload, "readiness_scores")),
        "diagnostics_present": bool(_mapping(payload, "diagnostics")),
        "recommendations_present": isinstance(payload.get("recommendations"), list),
        "postgresql_source_of_truth": payload.get("postgresql_source_of_truth") is True,
        "side_effects_performed": payload.get("side_effects_performed") is True,
        "external_calls_performed": payload.get("external_calls_performed") is True,
        "llm_used": payload.get("llm_used") is True,
        "qdrant_used": payload.get("qdrant_used") is True,
    }
    required = (
        ("workspace_summary_present", "workspace_summary_missing"),
        ("executive_kpis_present", "executive_kpis_missing"),
        ("analytics_sections_present", "analytics_sections_missing"),
        ("trend_sections_present", "trend_sections_missing"),
        ("reference_tenant_analytics_present", "reference_tenant_analytics_missing"),
        ("readiness_present", "readiness_missing"),
        ("diagnostics_present", "diagnostics_missing"),
        ("recommendations_present", "recommendations_missing"),
    )
    for key, code in required:
        if not checks[key]:
            errors.append({"code": code})
    if not checks["postgresql_source_of_truth"]:
        errors.append({"code": "postgresql_source_of_truth_not_confirmed"})
    for flag in ("side_effects_performed", "external_calls_performed", "llm_used", "qdrant_used"):
        if checks[flag]:
            errors.append(
                {
                    "code": flag,
                    "message": "Reporting & Analytics Center must remain read-only and execution-free.",
                }
            )

    warnings.extend(payload.get("warnings") or [])
    result = {
        "passed": not errors,
        "api_base_url": API_BASE_URL,
        "endpoint_reachable": checks["endpoint_reachable"],
        "runtime_status": payload.get("runtime_status"),
        "workspace_summary_present": checks["workspace_summary_present"],
        "executive_kpis_present": checks["executive_kpis_present"],
        "analytics_sections_present": checks["analytics_sections_present"],
        "trend_sections_present": checks["trend_sections_present"],
        "reference_tenant_analytics_present": checks["reference_tenant_analytics_present"],
        "readiness_present": checks["readiness_present"],
        "diagnostics_present": checks["diagnostics_present"],
        "recommendations_present": checks["recommendations_present"],
        "postgresql_source_of_truth": checks["postgresql_source_of_truth"],
        "side_effects_performed": checks["side_effects_performed"],
        "external_calls_performed": checks["external_calls_performed"],
        "llm_used": checks["llm_used"],
        "qdrant_used": checks["qdrant_used"],
        "kpi_count": len(_mapping(payload, "executive_kpis")),
        "recommendation_count": len(_listing(payload, "recommendations")),
        "warnings": warnings,
        "errors": errors,
    }
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
