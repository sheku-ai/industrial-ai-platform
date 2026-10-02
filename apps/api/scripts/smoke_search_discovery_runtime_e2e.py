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
    payload = http_get_json("/search/discovery/runtime")
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    if payload.get("_http_error"):
        errors.append({"code": "search_discovery_runtime_unavailable", "details": payload})
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
        "knowledge_explorer_present": bool(payload.get("knowledge_documents") is not None),
        "document_explorer_present": bool(_mapping(payload, "document_explorer")),
        "chunk_explorer_present": bool(_mapping(payload, "chunk_explorer")),
        "citation_explorer_present": bool(_mapping(payload, "citation_explorer")),
        "search_diagnostics_present": bool(_mapping(payload, "search_diagnostics")),
        "coverage_diagnostics_present": bool(_mapping(payload, "coverage_diagnostics")),
        "reference_tenant_coverage_present": bool(_mapping(payload, "reference_tenant_coverage")),
        "postgresql_source_of_truth": payload.get("postgresql_source_of_truth") is True,
        "llm_used": payload.get("llm_used") is True,
        "qdrant_used": payload.get("qdrant_used") is True,
    }
    required = (
        ("workspace_summary_present", "workspace_summary_missing"),
        ("knowledge_explorer_present", "knowledge_explorer_missing"),
        ("document_explorer_present", "document_explorer_missing"),
        ("chunk_explorer_present", "chunk_explorer_missing"),
        ("citation_explorer_present", "citation_explorer_missing"),
        ("search_diagnostics_present", "search_diagnostics_missing"),
        ("coverage_diagnostics_present", "coverage_diagnostics_missing"),
        ("reference_tenant_coverage_present", "reference_tenant_coverage_missing"),
    )
    for key, code in required:
        if not checks[key]:
            errors.append({"code": code})
    if not checks["postgresql_source_of_truth"]:
        errors.append({"code": "postgresql_source_of_truth_not_confirmed"})
    for flag in ("llm_used", "qdrant_used"):
        if checks[flag]:
            errors.append(
                {
                    "code": flag,
                    "message": "Search Discovery Runtime must not execute AI or Qdrant.",
                }
            )

    warnings.extend(payload.get("warnings") or [])
    result = {
        "passed": not errors,
        "api_base_url": API_BASE_URL,
        "endpoint_reachable": checks["endpoint_reachable"],
        "runtime_status": payload.get("runtime_status"),
        "workspace_summary_present": checks["workspace_summary_present"],
        "knowledge_explorer_present": checks["knowledge_explorer_present"],
        "document_explorer_present": checks["document_explorer_present"],
        "chunk_explorer_present": checks["chunk_explorer_present"],
        "citation_explorer_present": checks["citation_explorer_present"],
        "search_diagnostics_present": checks["search_diagnostics_present"],
        "coverage_diagnostics_present": checks["coverage_diagnostics_present"],
        "reference_tenant_coverage_present": checks["reference_tenant_coverage_present"],
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
