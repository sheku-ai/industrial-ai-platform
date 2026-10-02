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
    payload = http_get_json("/models/providers/center/runtime")
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    if payload.get("_http_error"):
        errors.append({"code": "model_provider_center_runtime_unavailable", "details": payload})
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
        "model_inventory_present": isinstance(payload.get("model_inventory"), list),
        "provider_inventory_present": isinstance(payload.get("provider_inventory"), list),
        "gateway_readiness_present": bool(_mapping(payload, "gateway_readiness")),
        "capabilities_present": bool(_mapping(payload, "model_capabilities")),
        "assistant_usage_present": bool(_mapping(payload, "assistant_model_usage")),
        "diagnostics_present": bool(_mapping(payload, "configuration_diagnostics")),
        "optional_ai_status_present": bool(_mapping(payload, "optional_ai_status")),
        "postgresql_source_of_truth": payload.get("postgresql_source_of_truth") is True,
        "side_effects_performed": payload.get("side_effects_performed") is True,
        "external_calls_performed": payload.get("external_calls_performed") is True,
        "llm_used": payload.get("llm_used") is True,
        "qdrant_used": payload.get("qdrant_used") is True,
        "secrets_exposed": payload.get("secrets_exposed") is True,
    }
    required = (
        ("workspace_summary_present", "workspace_summary_missing"),
        ("model_inventory_present", "model_inventory_missing"),
        ("provider_inventory_present", "provider_inventory_missing"),
        ("gateway_readiness_present", "gateway_readiness_missing"),
        ("capabilities_present", "capabilities_missing"),
        ("assistant_usage_present", "assistant_usage_missing"),
        ("diagnostics_present", "diagnostics_missing"),
        ("optional_ai_status_present", "optional_ai_status_missing"),
    )
    for key, code in required:
        if not checks[key]:
            errors.append({"code": code})
    if not checks["postgresql_source_of_truth"]:
        errors.append({"code": "postgresql_source_of_truth_not_confirmed"})
    for flag in (
        "side_effects_performed",
        "external_calls_performed",
        "llm_used",
        "qdrant_used",
        "secrets_exposed",
    ):
        if checks[flag]:
            errors.append(
                {
                    "code": flag,
                    "message": "Model & Provider Center must be read-only, secret-safe and execution-free.",
                }
            )

    warnings.extend(payload.get("warnings") or [])
    result = {
        "passed": not errors,
        "api_base_url": API_BASE_URL,
        "endpoint_reachable": checks["endpoint_reachable"],
        "runtime_status": payload.get("runtime_status"),
        "workspace_summary_present": checks["workspace_summary_present"],
        "model_inventory_present": checks["model_inventory_present"],
        "provider_inventory_present": checks["provider_inventory_present"],
        "gateway_readiness_present": checks["gateway_readiness_present"],
        "capabilities_present": checks["capabilities_present"],
        "assistant_usage_present": checks["assistant_usage_present"],
        "diagnostics_present": checks["diagnostics_present"],
        "optional_ai_status_present": checks["optional_ai_status_present"],
        "postgresql_source_of_truth": checks["postgresql_source_of_truth"],
        "side_effects_performed": checks["side_effects_performed"],
        "external_calls_performed": checks["external_calls_performed"],
        "llm_used": checks["llm_used"],
        "qdrant_used": checks["qdrant_used"],
        "secrets_exposed": checks["secrets_exposed"],
        "model_count": len(_listing(payload, "model_inventory")),
        "provider_count": len(_listing(payload, "provider_inventory")),
        "warnings": warnings,
        "errors": errors,
    }
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
