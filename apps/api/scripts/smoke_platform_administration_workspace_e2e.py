#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any

API_BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000/api").rstrip("/")
FRONTEND_BASE_URL = os.getenv("FRONTEND_BASE_URL", "").rstrip("/")


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


def http_get_text(url: str) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"Accept": "text/html"}, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return {"reachable": True, "status_code": response.status, "body": response.read().decode("utf-8")}
    except urllib.error.HTTPError as exc:
        return {"reachable": False, "status_code": exc.code, "body": exc.read().decode("utf-8")}
    except urllib.error.URLError as exc:
        return {"reachable": False, "error": "connection_failed", "details": str(exc)}


def _mapping(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    return value if isinstance(value, dict) else {}


def main() -> int:
    payload = http_get_json("/platform/administration/runtime")
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    if payload.get("_http_error"):
        errors.append({"code": "platform_administration_runtime_unavailable", "details": payload})
        result = {
            "passed": False,
            "api_base_url": API_BASE_URL,
            "administration_runtime_endpoint_reachable": False,
            "warnings": warnings,
            "errors": errors,
        }
        print(json.dumps(result, indent=2, sort_keys=True, default=str))
        return 1

    checks = {
        "administration_runtime_endpoint_reachable": True,
        "organizations_section_present": bool(_mapping(payload, "organizations")),
        "security_section_present": bool(_mapping(payload, "security")),
        "documents_section_present": bool(_mapping(payload, "documents")),
        "knowledge_section_present": bool(_mapping(payload, "knowledge")),
        "assistants_section_present": bool(_mapping(payload, "assistants")),
        "reference_tenant_section_present": bool(_mapping(payload, "reference_tenant")),
        "diagnostics_section_present": isinstance(payload.get("blocking_issues"), list)
        and isinstance(payload.get("warnings"), list),
        "postgresql_source_of_truth": payload.get("postgresql_source_of_truth") is True,
    }
    for key, code in (
        ("organizations_section_present", "organizations_section_missing"),
        ("security_section_present", "security_section_missing"),
        ("documents_section_present", "documents_section_missing"),
        ("knowledge_section_present", "knowledge_section_missing"),
        ("assistants_section_present", "assistants_section_missing"),
        ("reference_tenant_section_present", "reference_tenant_section_missing"),
        ("diagnostics_section_present", "diagnostics_section_missing"),
    ):
        if not checks[key]:
            errors.append({"code": code})
    if not checks["postgresql_source_of_truth"]:
        errors.append({"code": "postgresql_source_of_truth_not_confirmed"})

    frontend_reachable = None
    if FRONTEND_BASE_URL:
        frontend = http_get_text(f"{FRONTEND_BASE_URL}/organization")
        frontend_reachable = bool(frontend.get("reachable"))
        if not frontend_reachable:
            warnings.append({"code": "frontend_administration_page_unreachable", "details": frontend})

    warnings.extend(payload.get("warnings") or [])
    result = {
        "passed": not errors,
        "api_base_url": API_BASE_URL,
        "frontend_base_url": FRONTEND_BASE_URL or None,
        "frontend_administration_page_reachable": frontend_reachable,
        "administration_runtime_endpoint_reachable": checks["administration_runtime_endpoint_reachable"],
        "organizations_section_present": checks["organizations_section_present"],
        "security_section_present": checks["security_section_present"],
        "documents_section_present": checks["documents_section_present"],
        "knowledge_section_present": checks["knowledge_section_present"],
        "assistants_section_present": checks["assistants_section_present"],
        "reference_tenant_section_present": checks["reference_tenant_section_present"],
        "diagnostics_section_present": checks["diagnostics_section_present"],
        "postgresql_source_of_truth": checks["postgresql_source_of_truth"],
        "warnings": warnings,
        "errors": errors,
    }
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
