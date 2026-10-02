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
    payload = http_get_json("/ai/studio/runtime")
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    if payload.get("_http_error"):
        errors.append({"code": "ai_studio_runtime_unavailable", "details": payload})
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
    models_providers = _mapping(payload, "models_and_providers")
    checks = {
        "endpoint_reachable": True,
        "runtime_status_present": bool(payload.get("runtime_status")),
        "workspace_summary_present": bool(_mapping(payload, "workspace_summary")),
        "models_providers_section_present": bool(models_providers)
        and isinstance(models_providers.get("models"), list)
        and isinstance(models_providers.get("providers"), list),
        "prompts_section_present": _list_present(payload, "prompts"),
        "guardrails_section_present": _list_present(payload, "guardrails"),
        "workflows_section_present": _list_present(payload, "workflows"),
        "assistants_section_present": _list_present(payload, "assistants"),
        "knowledge_sources_section_present": _list_present(payload, "knowledge_sources"),
        "runtime_executions_section_present": bool(_mapping(payload, "runtime_executions")),
        "policy_readiness_section_present": bool(_mapping(payload, "policy_readiness")),
        "audit_diagnostics_section_present": bool(_mapping(payload, "audit_diagnostics")),
        "diagnostics_present": bool(diagnostics),
        "postgresql_source_of_truth": payload.get("postgresql_source_of_truth") is True,
        "ai_required": payload.get("ai_required") is True,
        "llm_used": payload.get("llm_used") is True,
        "qdrant_used": payload.get("qdrant_used") is True,
        "external_provider_calls": payload.get("external_provider_calls") is True,
    }
    for key, code in (
        ("runtime_status_present", "runtime_status_missing"),
        ("workspace_summary_present", "workspace_summary_missing"),
        ("models_providers_section_present", "models_providers_section_missing"),
        ("prompts_section_present", "prompts_section_missing"),
        ("guardrails_section_present", "guardrails_section_missing"),
        ("workflows_section_present", "workflows_section_missing"),
        ("assistants_section_present", "assistants_section_missing"),
        ("knowledge_sources_section_present", "knowledge_sources_section_missing"),
        ("runtime_executions_section_present", "runtime_executions_section_missing"),
        ("policy_readiness_section_present", "policy_readiness_section_missing"),
        ("audit_diagnostics_section_present", "audit_diagnostics_section_missing"),
        ("diagnostics_present", "diagnostics_missing"),
    ):
        if not checks[key]:
            errors.append({"code": code})
    if not checks["postgresql_source_of_truth"]:
        errors.append({"code": "postgresql_source_of_truth_not_confirmed"})
    for flag in ("ai_required", "llm_used", "qdrant_used", "external_provider_calls"):
        if checks[flag]:
            errors.append(
                {
                    "code": flag,
                    "message": (
                        "AI Studio Runtime must be optional and must not execute providers or vector infrastructure."
                    ),
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
        "models_providers_section_present": checks["models_providers_section_present"],
        "prompts_section_present": checks["prompts_section_present"],
        "guardrails_section_present": checks["guardrails_section_present"],
        "workflows_section_present": checks["workflows_section_present"],
        "assistants_section_present": checks["assistants_section_present"],
        "knowledge_sources_section_present": checks["knowledge_sources_section_present"],
        "runtime_executions_section_present": checks["runtime_executions_section_present"],
        "policy_readiness_section_present": checks["policy_readiness_section_present"],
        "audit_diagnostics_section_present": checks["audit_diagnostics_section_present"],
        "diagnostics_present": checks["diagnostics_present"],
        "postgresql_source_of_truth": checks["postgresql_source_of_truth"],
        "ai_required": checks["ai_required"],
        "llm_used": checks["llm_used"],
        "qdrant_used": checks["qdrant_used"],
        "external_provider_calls": checks["external_provider_calls"],
        "warnings": warnings,
        "errors": errors,
    }
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
