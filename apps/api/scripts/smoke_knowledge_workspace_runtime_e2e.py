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
    payload = http_get_json("/knowledge/workspace/runtime")
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    if payload.get("_http_error"):
        errors.append({"code": "knowledge_workspace_runtime_unavailable", "details": payload})
        result = {
            "passed": False,
            "api_base_url": API_BASE_URL,
            "endpoint_reachable": False,
            "warnings": warnings,
            "errors": errors,
        }
        print(json.dumps(result, indent=2, sort_keys=True, default=str))
        return 1

    workspace_summary = _mapping(payload, "workspace_summary")
    chunk_overview = _mapping(payload, "chunk_overview")
    enterprise_search = _mapping(payload, "enterprise_search")
    diagnostics = _mapping(payload, "diagnostics")
    checks = {
        "endpoint_reachable": True,
        "runtime_status_present": bool(payload.get("runtime_status")),
        "postgresql_source_of_truth": payload.get("postgresql_source_of_truth") is True,
        "collections_section_present": isinstance(payload.get("collections"), list),
        "knowledge_documents_section_present": isinstance(payload.get("knowledge_documents"), list),
        "chunk_overview_present": bool(chunk_overview),
        "enterprise_search_section_present": bool(enterprise_search),
        "diagnostics_present": bool(diagnostics),
        "llm_used": payload.get("llm_used") is True,
        "qdrant_used": payload.get("qdrant_used") is True,
        "workspace_summary_present": bool(workspace_summary),
    }
    if not checks["runtime_status_present"]:
        errors.append({"code": "runtime_status_missing"})
    if not checks["postgresql_source_of_truth"]:
        errors.append({"code": "postgresql_source_of_truth_not_confirmed"})
    if not checks["collections_section_present"]:
        errors.append({"code": "collections_section_missing"})
    if not checks["knowledge_documents_section_present"]:
        errors.append({"code": "knowledge_documents_section_missing"})
    if not checks["chunk_overview_present"]:
        errors.append({"code": "chunk_overview_missing"})
    if not checks["enterprise_search_section_present"]:
        errors.append({"code": "enterprise_search_section_missing"})
    if not checks["diagnostics_present"]:
        errors.append({"code": "diagnostics_missing"})
    if not checks["workspace_summary_present"]:
        errors.append({"code": "workspace_summary_missing"})
    for flag in ("llm_used", "qdrant_used"):
        if checks[flag]:
            errors.append(
                {
                    "code": flag,
                    "message": "Knowledge Workspace Runtime must not execute AI or vector infrastructure.",
                }
            )

    warnings.extend(_list(diagnostics, "warnings"))
    result = {
        "passed": not errors,
        "api_base_url": API_BASE_URL,
        "endpoint_reachable": checks["endpoint_reachable"],
        "runtime_status": payload.get("runtime_status"),
        "runtime_status_present": checks["runtime_status_present"],
        "postgresql_source_of_truth": checks["postgresql_source_of_truth"],
        "collections_section_present": checks["collections_section_present"],
        "knowledge_documents_section_present": checks["knowledge_documents_section_present"],
        "chunk_overview_present": checks["chunk_overview_present"],
        "enterprise_search_section_present": checks["enterprise_search_section_present"],
        "diagnostics_present": checks["diagnostics_present"],
        "collection_count": len(_list(payload, "collections")),
        "knowledge_document_count": len(_list(payload, "knowledge_documents")),
        "llm_used": checks["llm_used"],
        "qdrant_used": checks["qdrant_used"],
        "warnings": warnings,
        "errors": errors,
    }
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
