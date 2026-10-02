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
    payload = http_get_json("/assistants/workspace/runtime")
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    if payload.get("_http_error"):
        errors.append({"code": "assistant_workspace_runtime_unavailable", "details": payload})
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
        "assistant_definitions_present": _list_present(payload, "assistant_definitions"),
        "conversations_section_present": _list_present(payload, "conversations"),
        "assistant_explorer_present": bool(_mapping(payload, "assistant_explorer")),
        "conversation_explorer_present": bool(_mapping(payload, "conversation_explorer")),
        "conversation_timeline_present": bool(_mapping(payload, "conversation_timeline")),
        "retrieval_explorer_present": bool(_mapping(payload, "retrieval_explorer")),
        "citation_explorer_present": bool(_mapping(payload, "citation_explorer")),
        "runtime_execution_present": bool(_mapping(payload, "runtime_execution")),
        "feedback_present": bool(_mapping(payload, "feedback")),
        "audit_present": bool(_mapping(payload, "audit")),
        "runtime_trace_present": bool(_mapping(payload, "runtime_trace")),
        "runtime_executions_section_present": bool(_mapping(payload, "runtime_executions")),
        "retrieval_citations_section_present": bool(_mapping(payload, "retrieval_and_citations")),
        "feedback_audit_section_present": bool(_mapping(payload, "feedback_and_audit")),
        "diagnostics_present": bool(diagnostics),
        "postgresql_source_of_truth": payload.get("postgresql_source_of_truth") is True,
        "llm_used": payload.get("llm_used") is True,
        "qdrant_used": payload.get("qdrant_used") is True,
    }
    for key, code in (
        ("runtime_status_present", "runtime_status_missing"),
        ("workspace_summary_present", "workspace_summary_missing"),
        ("assistant_definitions_present", "assistant_definitions_missing"),
        ("conversations_section_present", "conversations_section_missing"),
        ("assistant_explorer_present", "assistant_explorer_missing"),
        ("conversation_explorer_present", "conversation_explorer_missing"),
        ("conversation_timeline_present", "conversation_timeline_missing"),
        ("retrieval_explorer_present", "retrieval_explorer_missing"),
        ("citation_explorer_present", "citation_explorer_missing"),
        ("runtime_execution_present", "runtime_execution_missing"),
        ("feedback_present", "feedback_missing"),
        ("audit_present", "audit_missing"),
        ("runtime_trace_present", "runtime_trace_missing"),
        ("runtime_executions_section_present", "runtime_executions_section_missing"),
        ("retrieval_citations_section_present", "retrieval_citations_section_missing"),
        ("feedback_audit_section_present", "feedback_audit_section_missing"),
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
                    "message": "Assistant Workspace Runtime must not execute AI or vector infrastructure.",
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
        "assistant_definitions_present": checks["assistant_definitions_present"],
        "conversations_section_present": checks["conversations_section_present"],
        "assistant_explorer_present": checks["assistant_explorer_present"],
        "conversation_explorer_present": checks["conversation_explorer_present"],
        "conversation_timeline_present": checks["conversation_timeline_present"],
        "retrieval_explorer_present": checks["retrieval_explorer_present"],
        "citation_explorer_present": checks["citation_explorer_present"],
        "runtime_execution_present": checks["runtime_execution_present"],
        "feedback_present": checks["feedback_present"],
        "audit_present": checks["audit_present"],
        "runtime_trace_present": checks["runtime_trace_present"],
        "runtime_executions_section_present": checks["runtime_executions_section_present"],
        "retrieval_citations_section_present": checks["retrieval_citations_section_present"],
        "feedback_audit_section_present": checks["feedback_audit_section_present"],
        "diagnostics_present": checks["diagnostics_present"],
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
