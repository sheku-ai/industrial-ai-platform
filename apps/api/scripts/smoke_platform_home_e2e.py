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
    payload = http_get_json("/platform/dashboard/runtime")
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    if payload.get("_http_error"):
        errors.append({"code": "platform_dashboard_runtime_unavailable", "details": payload})
        result = {
            "passed": False,
            "api_base_url": API_BASE_URL,
            "dashboard_endpoint_reachable": False,
            "warnings": warnings,
            "errors": errors,
        }
        print(json.dumps(result, indent=2, sort_keys=True, default=str))
        return 1

    platform_summary = _mapping(payload, "platform_summary")
    readiness = _mapping(payload, "readiness_summary")
    operational = _mapping(payload, "operational_summary")
    diagnostics = _mapping(payload, "alerts_and_diagnostics")
    navigation = _list(payload, "navigation")
    actions = _list(payload, "recommended_next_actions")

    required_health_cards = (
        "administration_ready",
        "operations_ready",
        "documents_ready",
        "knowledge_ready",
        "search_ready",
        "assistant_ready",
        "chat_ready",
        "feedback_ready",
        "audit_ready",
    )
    required_metrics = (
        "registered_documents",
        "processed_documents",
        "knowledge_documents",
        "knowledge_chunks",
        "indexed_documents",
        "search_requests",
        "conversations",
        "assistant_executions",
        "feedback_count",
        "audit_count",
    )
    required_alerts = (
        "blocking_issues",
        "warnings",
        "pending_capabilities",
        "unavailable_domains",
        "degraded_domains",
    )

    checks = {
        "dashboard_endpoint_reachable": True,
        "navigation_rendered": bool(navigation),
        "health_cards_present": all(key in readiness for key in required_health_cards),
        "operational_metrics_present": all(key in operational for key in required_metrics),
        "recommended_actions_present": bool(actions),
        "platform_summary_present": bool(platform_summary),
        "runtime_summary_present": all(
            key in payload
            for key in (
                "postgresql_source_of_truth",
                "llm_used",
                "embeddings_used",
                "qdrant_used",
            )
        ),
        "alerts_present": all(key in diagnostics for key in required_alerts),
        "postgresql_source_of_truth": payload.get("postgresql_source_of_truth") is True,
        "llm_used": payload.get("llm_used") is True,
        "embeddings_used": payload.get("embeddings_used") is True,
        "qdrant_used": payload.get("qdrant_used") is True,
    }

    if not checks["navigation_rendered"]:
        errors.append({"code": "navigation_model_missing"})
    if not checks["health_cards_present"]:
        missing = sorted(key for key in required_health_cards if key not in readiness)
        errors.append({"code": "health_cards_missing", "missing": missing})
    if not checks["operational_metrics_present"]:
        missing = sorted(key for key in required_metrics if key not in operational)
        errors.append({"code": "operational_metrics_missing", "missing": missing})
    if not checks["recommended_actions_present"]:
        errors.append({"code": "recommended_actions_missing"})
    if not checks["platform_summary_present"]:
        errors.append({"code": "platform_summary_missing"})
    if not checks["runtime_summary_present"]:
        errors.append({"code": "runtime_summary_missing"})
    if not checks["alerts_present"]:
        missing = sorted(key for key in required_alerts if key not in diagnostics)
        errors.append({"code": "alerts_missing", "missing": missing})
    if not checks["postgresql_source_of_truth"]:
        errors.append({"code": "postgresql_source_of_truth_not_confirmed"})
    for flag in ("llm_used", "embeddings_used", "qdrant_used"):
        if checks[flag]:
            errors.append(
                {
                    "code": flag,
                    "message": "Platform Home must be driven by PostgreSQL runtime data without AI/vector execution.",
                }
            )

    warnings.extend(diagnostics.get("warnings") or [])
    result = {
        "passed": not errors,
        "api_base_url": API_BASE_URL,
        "dashboard_endpoint_reachable": checks["dashboard_endpoint_reachable"],
        "navigation_rendered": checks["navigation_rendered"],
        "health_cards_present": checks["health_cards_present"],
        "operational_metrics_present": checks["operational_metrics_present"],
        "recommended_actions_present": checks["recommended_actions_present"],
        "platform_summary_present": checks["platform_summary_present"],
        "runtime_summary_present": checks["runtime_summary_present"],
        "alerts_present": checks["alerts_present"],
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
