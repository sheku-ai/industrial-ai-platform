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


def _list(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = payload.get(key)
    return value if isinstance(value, list) else []


def main() -> int:
    payload = http_get_json("/platform/product/integration/runtime")
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    if payload.get("_http_error"):
        errors.append({"code": "product_integration_runtime_unavailable", "details": payload})
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
    overall = _mapping(payload, "overall")
    rc_gate = _mapping(payload, "rc_gate")
    domain_readiness = _mapping(payload, "domain_readiness")
    required_domains = _list(domain_readiness, "required_domains")
    optional_domains = _list(domain_readiness, "optional_domains")
    documents = _mapping(payload, "documents")
    connector_optional = next(
        (domain for domain in optional_domains if domain.get("domain") == "connectors"),
        {},
    )
    ai_provider_optional = next(
        (domain for domain in optional_domains if domain.get("domain") == "ai_providers"),
        {},
    )
    blocking_domains = [
        domain
        for domain in required_domains
        if domain.get("blocking") or domain.get("status") == "BLOCKED" or domain.get("ready") is not True
    ]
    checks = {
        "endpoint_reachable": True,
        "platform_summary_present": bool(_mapping(payload, "platform")),
        "workspace_validation_present": bool(_mapping(payload, "workspace_validation")),
        "runtime_validation_present": bool(_mapping(payload, "runtime_validation")),
        "reference_tenant_present": bool(_mapping(payload, "reference_tenant")),
        "score_present": bool(_mapping(payload, "product_score")),
        "readiness_matrix_present": bool(_mapping(payload, "readiness_matrix")),
        "recommendations_present": "recommendations" in _mapping(payload, "overall"),
        "product_baseline_ready": overall.get("product_baseline_ready") is True,
        "integration_ready": overall.get("integration_ready") is True,
        "production_candidate": overall.get("production_candidate") is True,
        "rc_gate_present": bool(rc_gate),
        "rc_gate_production_candidate": rc_gate.get("production_candidate") is True,
        "required_domains_ready": rc_gate.get("required_domains_ready") is True,
        "optional_domains_non_blocking": rc_gate.get("optional_domains_non_blocking") is True,
        "side_effect_free": rc_gate.get("side_effect_free") is True,
        "external_calls_free": rc_gate.get("external_calls_free") is True,
        "ai_execution_free": rc_gate.get("ai_execution_free") is True,
        "document_chunking_ready": documents.get("chunking_ready") is True,
        "connector_optional_not_configured_non_blocking": (
            connector_optional.get("status") in {"OPTIONAL_NOT_CONFIGURED", "READY", "SKIPPED"}
            and connector_optional.get("blocking") is not True
        ),
        "ai_provider_optional_not_configured_non_blocking": (
            ai_provider_optional.get("status") in {"OPTIONAL_NOT_CONFIGURED", "READY", "SKIPPED"}
            and ai_provider_optional.get("blocking") is not True
        ),
        "postgresql_source_of_truth": payload.get("postgresql_source_of_truth") is True,
        "side_effects_performed": payload.get("side_effects_performed") is True,
        "external_calls_performed": payload.get("external_calls_performed") is True,
        "llm_used": payload.get("llm_used") is True,
        "qdrant_used": payload.get("qdrant_used") is True,
    }
    required = (
        ("platform_summary_present", "platform_summary_missing"),
        ("workspace_validation_present", "workspace_validation_missing"),
        ("runtime_validation_present", "runtime_validation_missing"),
        ("reference_tenant_present", "reference_tenant_missing"),
        ("score_present", "product_score_missing"),
        ("readiness_matrix_present", "readiness_matrix_missing"),
        ("recommendations_present", "recommendations_missing"),
        ("product_baseline_ready", "product_baseline_not_ready"),
        ("integration_ready", "integration_not_ready"),
        ("production_candidate", "production_candidate_false"),
        ("rc_gate_present", "rc_gate_missing"),
        ("rc_gate_production_candidate", "rc_gate_production_candidate_false"),
        ("required_domains_ready", "required_domains_not_ready"),
        ("optional_domains_non_blocking", "optional_domains_blocking"),
        ("side_effect_free", "side_effect_free_false"),
        ("external_calls_free", "external_calls_free_false"),
        ("ai_execution_free", "ai_execution_free_false"),
        ("document_chunking_ready", "document_chunking_not_ready"),
        ("connector_optional_not_configured_non_blocking", "connector_optional_blocks_baseline"),
        ("ai_provider_optional_not_configured_non_blocking", "ai_provider_optional_blocks_baseline"),
    )
    for key, code in required:
        if not checks[key]:
            errors.append({"code": code})
    if not checks["postgresql_source_of_truth"]:
        errors.append({"code": "postgresql_source_of_truth_not_confirmed"})
    for flag in ("side_effects_performed", "external_calls_performed", "llm_used", "qdrant_used"):
        if checks[flag]:
            errors.append(
                {
                    "code": flag,
                    "message": (
                        "Product Integration Runtime must be read-only and must not execute external infrastructure."
                    ),
                }
            )

    warnings.extend(diagnostics.get("warnings") or [])
    result = {
        "passed": not errors,
        "api_base_url": API_BASE_URL,
        "endpoint_reachable": checks["endpoint_reachable"],
        "runtime_status": payload.get("runtime_status"),
        "platform_summary_present": checks["platform_summary_present"],
        "workspace_validation_present": checks["workspace_validation_present"],
        "runtime_validation_present": checks["runtime_validation_present"],
        "reference_tenant_present": checks["reference_tenant_present"],
        "score_present": checks["score_present"],
        "readiness_matrix_present": checks["readiness_matrix_present"],
        "recommendations_present": checks["recommendations_present"],
        "product_baseline_ready": checks["product_baseline_ready"],
        "integration_ready": checks["integration_ready"],
        "production_candidate": checks["production_candidate"],
        "rc_gate_present": checks["rc_gate_present"],
        "rc_gate_production_candidate": checks["rc_gate_production_candidate"],
        "required_domains_ready": checks["required_domains_ready"],
        "optional_domains_non_blocking": checks["optional_domains_non_blocking"],
        "side_effect_free": checks["side_effect_free"],
        "external_calls_free": checks["external_calls_free"],
        "ai_execution_free": checks["ai_execution_free"],
        "document_chunking_ready": checks["document_chunking_ready"],
        "connector_optional_not_configured_non_blocking": checks["connector_optional_not_configured_non_blocking"],
        "ai_provider_optional_not_configured_non_blocking": checks["ai_provider_optional_not_configured_non_blocking"],
        "blocking_domains": blocking_domains,
        "postgresql_source_of_truth": checks["postgresql_source_of_truth"],
        "side_effects_performed": checks["side_effects_performed"],
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
