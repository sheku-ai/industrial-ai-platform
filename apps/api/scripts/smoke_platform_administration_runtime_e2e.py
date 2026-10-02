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


def _has_mapping(payload: dict[str, Any], key: str) -> bool:
    return isinstance(payload.get(key), dict)


def main() -> int:
    payload = http_get_json("/platform/administration/runtime")
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    if payload.get("_http_error"):
        errors.append({"code": "platform_administration_runtime_unavailable", "details": payload})
        result = {
            "passed": False,
            "api_base_url": API_BASE_URL,
            "runtime_returned": False,
            "warnings": warnings,
            "errors": errors,
        }
        print(json.dumps(result, indent=2, sort_keys=True, default=str))
        return 1

    mandatory_sections = (
        "platform",
        "organizations",
        "security",
        "documents",
        "knowledge",
        "enterprise_search",
        "assistants",
        "reference_tenant",
    )
    checks = {
        "runtime_returned": True,
        "schema_version_present": bool(payload.get("platform_administration_runtime_schema_version")),
        "postgresql_source_of_truth": payload.get("postgresql_source_of_truth") is True,
        "llm_used": payload.get("llm_used") is True,
        "embeddings_used": payload.get("embeddings_used") is True,
        "qdrant_used": payload.get("qdrant_used") is True,
        "platform_present": _has_mapping(payload, "platform"),
        "organizations_present": _has_mapping(payload, "organizations"),
        "security_present": _has_mapping(payload, "security"),
        "documents_present": _has_mapping(payload, "documents"),
        "knowledge_present": _has_mapping(payload, "knowledge"),
        "enterprise_search_present": _has_mapping(payload, "enterprise_search"),
        "assistants_present": _has_mapping(payload, "assistants"),
        "reference_tenant_present": _has_mapping(payload, "reference_tenant"),
        "health_summary_present": _has_mapping(payload, "health_summary"),
    }
    for section in mandatory_sections:
        if not checks[f"{section}_present"]:
            errors.append({"code": "mandatory_section_missing", "section": section})
    if not checks["schema_version_present"]:
        errors.append({"code": "schema_version_missing"})
    if not checks["postgresql_source_of_truth"]:
        errors.append({"code": "postgresql_source_of_truth_not_confirmed"})
    for flag in ("llm_used", "embeddings_used", "qdrant_used"):
        if checks[flag]:
            errors.append(
                {
                    "code": flag,
                    "message": "Platform Administration Runtime must not require AI/vector execution.",
                }
            )

    platform = payload.get("platform") if isinstance(payload.get("platform"), dict) else {}
    health_summary = payload.get("health_summary") if isinstance(payload.get("health_summary"), dict) else {}
    configured_capabilities = (
        platform.get("configured_capabilities") if isinstance(platform.get("configured_capabilities"), dict) else {}
    )
    installed_capabilities = (
        platform.get("installed_capabilities") if isinstance(platform.get("installed_capabilities"), list) else []
    )
    domain_ready = health_summary.get("domain_ready") if isinstance(health_summary.get("domain_ready"), dict) else {}
    missing_runtime_domains = [
        domain for domain in mandatory_sections if domain not in {"platform"} and domain not in domain_ready
    ]
    if missing_runtime_domains:
        errors.append({"code": "mandatory_runtime_domain_missing", "domains": missing_runtime_domains})

    warnings.extend(payload.get("warnings") or [])
    result = {
        "passed": not errors,
        "api_base_url": API_BASE_URL,
        "runtime_returned": checks["runtime_returned"],
        "schema_version_present": checks["schema_version_present"],
        "runtime_status": payload.get("runtime_status"),
        "platform_present": checks["platform_present"],
        "organizations_present": checks["organizations_present"],
        "security_present": checks["security_present"],
        "documents_present": checks["documents_present"],
        "knowledge_present": checks["knowledge_present"],
        "enterprise_search_present": checks["enterprise_search_present"],
        "assistants_present": checks["assistants_present"],
        "reference_tenant_present": checks["reference_tenant_present"],
        "health_summary_present": checks["health_summary_present"],
        "configured_capabilities": configured_capabilities,
        "installed_capabilities": installed_capabilities,
        "domain_ready": domain_ready,
        "missing_runtime_domains": missing_runtime_domains,
        "postgresql_source_of_truth": checks["postgresql_source_of_truth"],
        "llm_used": checks["llm_used"],
        "embeddings_used": checks["embeddings_used"],
        "qdrant_used": checks["qdrant_used"],
        "warnings": warnings,
        "errors": errors,
    }
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
