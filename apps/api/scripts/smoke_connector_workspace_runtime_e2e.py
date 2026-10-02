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


def _list_present(payload: dict[str, Any], key: str) -> bool:
    return isinstance(payload.get(key), list)


def main() -> int:
    payload = http_get_json("/connectors/workspace/runtime")
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    if payload.get("_http_error"):
        errors.append({"code": "connector_workspace_runtime_unavailable", "details": payload})
        result = {
            "passed": False,
            "api_base_url": API_BASE_URL,
            "endpoint_reachable": False,
            "warnings": warnings,
            "errors": errors,
        }
        print(json.dumps(result, indent=2, sort_keys=True, default=str))
        return 1

    diagnostics = _mapping(payload, "diagnostics")
    checks = {
        "endpoint_reachable": True,
        "runtime_status_present": bool(payload.get("runtime_status")),
        "workspace_summary_present": bool(_mapping(payload, "workspace_summary")),
        "connector_types_section_present": _list_present(payload, "connector_types"),
        "connectors_section_present": _list_present(payload, "connectors"),
        "connector_configurations_section_present": _list_present(payload, "connector_configurations"),
        "connector_runs_section_present": bool(_mapping(payload, "connector_runs")),
        "sync_impact_section_present": bool(_mapping(payload, "sync_ingestion_impact")),
        "audit_trace_section_present": bool(_mapping(payload, "audit_trace")),
        "diagnostics_present": bool(diagnostics),
        "postgresql_source_of_truth": payload.get("postgresql_source_of_truth") is True,
        "external_calls_performed": payload.get("external_calls_performed") is True,
        "llm_used": payload.get("llm_used") is True,
        "qdrant_used": payload.get("qdrant_used") is True,
    }
    for key, code in (
        ("runtime_status_present", "runtime_status_missing"),
        ("workspace_summary_present", "workspace_summary_missing"),
        ("connector_types_section_present", "connector_types_section_missing"),
        ("connectors_section_present", "connectors_section_missing"),
        ("connector_configurations_section_present", "connector_configurations_section_missing"),
        ("connector_runs_section_present", "connector_runs_section_missing"),
        ("sync_impact_section_present", "sync_impact_section_missing"),
        ("audit_trace_section_present", "audit_trace_section_missing"),
        ("diagnostics_present", "diagnostics_missing"),
    ):
        if not checks[key]:
            errors.append({"code": code})
    if not checks["postgresql_source_of_truth"]:
        errors.append({"code": "postgresql_source_of_truth_not_confirmed"})
    for flag in ("external_calls_performed", "llm_used", "qdrant_used"):
        if checks[flag]:
            errors.append(
                {
                    "code": flag,
                    "message": "Connector Workspace Runtime must not execute external, AI, or vector infrastructure.",
                }
            )

    warnings.extend(diagnostics.get("warnings") or [])
    result = {
        "passed": not errors,
        "api_base_url": API_BASE_URL,
        "endpoint_reachable": checks["endpoint_reachable"],
        "runtime_status": payload.get("runtime_status"),
        "runtime_status_present": checks["runtime_status_present"],
        "workspace_summary_present": checks["workspace_summary_present"],
        "connector_types_section_present": checks["connector_types_section_present"],
        "connectors_section_present": checks["connectors_section_present"],
        "connector_configurations_section_present": checks["connector_configurations_section_present"],
        "connector_runs_section_present": checks["connector_runs_section_present"],
        "sync_impact_section_present": checks["sync_impact_section_present"],
        "audit_trace_section_present": checks["audit_trace_section_present"],
        "diagnostics_present": checks["diagnostics_present"],
        "postgresql_source_of_truth": checks["postgresql_source_of_truth"],
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
