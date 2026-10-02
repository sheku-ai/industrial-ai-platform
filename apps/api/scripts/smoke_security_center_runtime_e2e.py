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


def main() -> int:
    payload = http_get_json("/security/center/runtime")
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    if payload.get("_http_error"):
        errors.append({"code": "security_center_runtime_unavailable", "details": payload})
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
        "roles_section_present": bool(_mapping(payload, "roles")),
        "permissions_section_present": bool(_mapping(payload, "permissions")),
        "policies_section_present": bool(_mapping(payload, "policies")),
        "assignments_section_present": bool(_mapping(payload, "role_assignments")),
        "effective_permissions_section_present": bool(_mapping(payload, "effective_permissions")),
        "diagnostics_present": bool(_mapping(payload, "access_diagnostics")),
        "reference_tenant_security_present": bool(_mapping(payload, "reference_tenant_security")),
        "postgresql_source_of_truth": payload.get("postgresql_source_of_truth") is True,
        "side_effects_performed": payload.get("side_effects_performed") is True,
        "external_calls_performed": payload.get("external_calls_performed") is True,
        "llm_used": payload.get("llm_used") is True,
        "qdrant_used": payload.get("qdrant_used") is True,
    }
    required = (
        ("workspace_summary_present", "workspace_summary_missing"),
        ("roles_section_present", "roles_section_missing"),
        ("permissions_section_present", "permissions_section_missing"),
        ("policies_section_present", "policies_section_missing"),
        ("assignments_section_present", "assignments_section_missing"),
        ("effective_permissions_section_present", "effective_permissions_section_missing"),
        ("diagnostics_present", "diagnostics_missing"),
        ("reference_tenant_security_present", "reference_tenant_security_missing"),
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
                    "message": (
                        "Security Center Runtime must be read-only and must not execute external infrastructure."
                    ),
                }
            )

    warnings.extend(payload.get("warnings") or [])
    result = {
        "passed": not errors,
        "api_base_url": API_BASE_URL,
        "endpoint_reachable": checks["endpoint_reachable"],
        "runtime_status": payload.get("runtime_status"),
        "workspace_summary_present": checks["workspace_summary_present"],
        "roles_section_present": checks["roles_section_present"],
        "permissions_section_present": checks["permissions_section_present"],
        "policies_section_present": checks["policies_section_present"],
        "assignments_section_present": checks["assignments_section_present"],
        "effective_permissions_section_present": checks["effective_permissions_section_present"],
        "diagnostics_present": checks["diagnostics_present"],
        "reference_tenant_security_present": checks["reference_tenant_security_present"],
        "postgresql_source_of_truth": checks["postgresql_source_of_truth"],
        "side_effects_performed": checks["side_effects_performed"],
        "external_calls_performed": checks["external_calls_performed"],
        "llm_used": checks["llm_used"],
        "qdrant_used": checks["qdrant_used"],
        "warnings": warnings,
        "errors": errors,
    }
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
