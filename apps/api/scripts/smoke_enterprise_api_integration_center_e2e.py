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
    payload = http_get_json("/enterprise/api-integration/center/runtime")
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    if payload.get("_http_error"):
        errors.append({"code": "enterprise_api_integration_center_unavailable", "details": payload})
        result = {
            "passed": False,
            "api_base_url": API_BASE_URL,
            "endpoint_reachable": False,
            "warnings": warnings,
            "errors": errors,
        }
        print(json.dumps(result, indent=2, sort_keys=True, default=str))
        return 1

    checks = {
        "endpoint_reachable": True,
        "workspace_summary_present": bool(_mapping(payload, "workspace_summary")),
        "api_inventory_present": bool(_mapping(payload, "platform_api_inventory")),
        "endpoint_catalog_present": bool(_listing(payload, "endpoint_catalog")),
        "integration_inventory_present": bool(_mapping(payload, "connector_integrations")),
        "security_readiness_present": bool(_mapping(payload, "authorization_model")),
        "reference_tenant_readiness_present": bool(_mapping(payload, "reference_tenant_integration_readiness")),
        "diagnostics_present": bool(_mapping(payload, "integration_diagnostics")),
        "recommendations_present": isinstance(payload.get("operational_recommendations"), list),
        "postgresql_source_of_truth": payload.get("postgresql_source_of_truth") is True,
        "side_effects_performed": payload.get("side_effects_performed") is True,
        "external_calls_performed": payload.get("external_calls_performed") is True,
        "llm_used": payload.get("llm_used") is True,
        "qdrant_used": payload.get("qdrant_used") is True,
    }
    required = (
        ("workspace_summary_present", "workspace_summary_missing"),
        ("api_inventory_present", "api_inventory_missing"),
        ("endpoint_catalog_present", "endpoint_catalog_missing"),
        ("integration_inventory_present", "integration_inventory_missing"),
        ("security_readiness_present", "security_readiness_missing"),
        ("reference_tenant_readiness_present", "reference_tenant_readiness_missing"),
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
                    "message": "Enterprise API & Integration Center must remain read-only and execution-free.",
                }
            )

    warnings.extend(payload.get("warnings") or [])
    result = {
        "passed": not errors,
        "api_base_url": API_BASE_URL,
        "endpoint_reachable": checks["endpoint_reachable"],
        "runtime_status": payload.get("runtime_status"),
        "workspace_summary_present": checks["workspace_summary_present"],
        "api_inventory_present": checks["api_inventory_present"],
        "endpoint_catalog_present": checks["endpoint_catalog_present"],
        "integration_inventory_present": checks["integration_inventory_present"],
        "security_readiness_present": checks["security_readiness_present"],
        "reference_tenant_readiness_present": checks["reference_tenant_readiness_present"],
        "diagnostics_present": checks["diagnostics_present"],
        "recommendations_present": checks["recommendations_present"],
        "postgresql_source_of_truth": checks["postgresql_source_of_truth"],
        "side_effects_performed": checks["side_effects_performed"],
        "external_calls_performed": checks["external_calls_performed"],
        "llm_used": checks["llm_used"],
        "qdrant_used": checks["qdrant_used"],
        "endpoint_count": len(_listing(payload, "endpoint_catalog")),
        "runtime_endpoint_count": len(_listing(payload, "runtime_endpoint_catalog")),
        "warnings": warnings,
        "errors": errors,
    }
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
