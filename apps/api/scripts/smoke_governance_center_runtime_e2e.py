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
    payload = http_get_json("/platform/governance/center/runtime")
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    if payload.get("_http_error"):
        errors.append({"code": "governance_center_runtime_unavailable", "details": payload})
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
        "audit_governance_present": bool(_mapping(payload, "audit_governance")),
        "feedback_governance_present": bool(_mapping(payload, "feedback_governance")),
        "classification_governance_present": bool(_mapping(payload, "classification_governance")),
        "retention_governance_present": bool(_mapping(payload, "retention_governance")),
        "policy_governance_present": bool(_mapping(payload, "policy_governance")),
        "runtime_evidence_present": bool(_mapping(payload, "runtime_evidence")),
        "document_lineage_present": bool(_mapping(payload, "document_lineage")),
        "knowledge_lineage_present": bool(_mapping(payload, "knowledge_lineage")),
        "assistant_traceability_present": bool(_mapping(payload, "assistant_traceability")),
        "compliance_readiness_present": bool(_mapping(payload, "compliance_readiness")),
        "diagnostics_present": bool(diagnostics),
        "postgresql_source_of_truth": payload.get("postgresql_source_of_truth") is True,
        "side_effects_performed": payload.get("side_effects_performed") is True,
        "llm_used": payload.get("llm_used") is True,
        "qdrant_used": payload.get("qdrant_used") is True,
        "external_calls_performed": payload.get("external_calls_performed") is True,
    }

    required_sections = (
        ("runtime_status_present", "runtime_status_missing"),
        ("workspace_summary_present", "workspace_summary_missing"),
        ("audit_governance_present", "audit_governance_missing"),
        ("feedback_governance_present", "feedback_governance_missing"),
        ("classification_governance_present", "classification_governance_missing"),
        ("retention_governance_present", "retention_governance_missing"),
        ("policy_governance_present", "policy_governance_missing"),
        ("runtime_evidence_present", "runtime_evidence_missing"),
        ("document_lineage_present", "document_lineage_missing"),
        ("knowledge_lineage_present", "knowledge_lineage_missing"),
        ("assistant_traceability_present", "assistant_traceability_missing"),
        ("compliance_readiness_present", "compliance_readiness_missing"),
        ("diagnostics_present", "diagnostics_missing"),
    )
    for key, code in required_sections:
        if not checks[key]:
            errors.append({"code": code})
    if not checks["postgresql_source_of_truth"]:
        errors.append({"code": "postgresql_source_of_truth_not_confirmed"})
    for flag in ("side_effects_performed", "llm_used", "qdrant_used", "external_calls_performed"):
        if checks[flag]:
            errors.append(
                {
                    "code": flag,
                    "message": "Governance Center Runtime must be read-only and PostgreSQL-backed.",
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
        "audit_governance_present": checks["audit_governance_present"],
        "feedback_governance_present": checks["feedback_governance_present"],
        "classification_governance_present": checks["classification_governance_present"],
        "retention_governance_present": checks["retention_governance_present"],
        "policy_governance_present": checks["policy_governance_present"],
        "runtime_evidence_present": checks["runtime_evidence_present"],
        "document_lineage_present": checks["document_lineage_present"],
        "knowledge_lineage_present": checks["knowledge_lineage_present"],
        "assistant_traceability_present": checks["assistant_traceability_present"],
        "compliance_readiness_present": checks["compliance_readiness_present"],
        "diagnostics_present": checks["diagnostics_present"],
        "postgresql_source_of_truth": checks["postgresql_source_of_truth"],
        "side_effects_performed": checks["side_effects_performed"],
        "llm_used": checks["llm_used"],
        "qdrant_used": checks["qdrant_used"],
        "external_calls_performed": checks["external_calls_performed"],
        "warnings": warnings,
        "errors": errors,
    }
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
