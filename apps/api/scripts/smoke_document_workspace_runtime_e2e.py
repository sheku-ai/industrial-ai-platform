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
    payload = http_get_json("/documents/workspace/runtime")
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    if payload.get("_http_error"):
        errors.append({"code": "document_workspace_runtime_unavailable", "details": payload})
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
        "runtime_ready": payload.get("runtime_status") == "ready",
        "workspace_summary_present": bool(_mapping(payload, "workspace_summary")),
        "registry_present": isinstance(payload.get("document_registry"), list),
        "versions_present": isinstance(payload.get("versions"), list),
        "lifecycle_present": bool(_mapping(payload, "lifecycle")),
        "storage_present": bool(_mapping(payload, "storage")),
        "processing_present": bool(_mapping(payload, "processing")),
        "chunks_present": bool(_mapping(payload, "chunks")),
        "knowledge_present": bool(_mapping(payload, "knowledge")),
        "enterprise_search_present": bool(_mapping(payload, "enterprise_search")),
        "diagnostics_present": bool(diagnostics),
        "postgresql_source_of_truth": payload.get("postgresql_source_of_truth") is True,
        "llm_used": payload.get("llm_used") is True,
        "qdrant_used": payload.get("qdrant_used") is True,
    }
    if not checks["runtime_ready"]:
        errors.append({"code": "document_workspace_runtime_not_ready", "runtime_status": payload.get("runtime_status")})
    for key, code in (
        ("workspace_summary_present", "workspace_summary_missing"),
        ("registry_present", "registry_missing"),
        ("versions_present", "versions_missing"),
        ("lifecycle_present", "lifecycle_missing"),
        ("storage_present", "storage_missing"),
        ("processing_present", "processing_missing"),
        ("chunks_present", "chunks_missing"),
        ("knowledge_present", "knowledge_missing"),
        ("enterprise_search_present", "enterprise_search_missing"),
        ("diagnostics_present", "diagnostics_missing"),
    ):
        if not checks[key]:
            errors.append({"code": code})
    if not checks["postgresql_source_of_truth"]:
        errors.append({"code": "postgresql_source_of_truth_not_confirmed"})
    for flag in ("llm_used", "qdrant_used"):
        if checks[flag]:
            errors.append(
                {
                    "code": flag,
                    "message": "Document Workspace Runtime must not execute AI or vector infrastructure.",
                }
            )

    warnings.extend(_list(diagnostics, "warnings"))
    result = {
        "passed": not errors,
        "api_base_url": API_BASE_URL,
        "endpoint_reachable": checks["endpoint_reachable"],
        "runtime_status": payload.get("runtime_status"),
        "runtime_ready": checks["runtime_ready"],
        "workspace_summary_present": checks["workspace_summary_present"],
        "registry_present": checks["registry_present"],
        "versions_present": checks["versions_present"],
        "lifecycle_present": checks["lifecycle_present"],
        "storage_present": checks["storage_present"],
        "processing_present": checks["processing_present"],
        "chunks_present": checks["chunks_present"],
        "knowledge_present": checks["knowledge_present"],
        "enterprise_search_present": checks["enterprise_search_present"],
        "diagnostics_present": checks["diagnostics_present"],
        "document_count": len(_list(payload, "document_registry")),
        "version_count": len(_list(payload, "versions")),
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
