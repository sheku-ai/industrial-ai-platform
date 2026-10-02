#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any

from readiness_contract_smoke import public_readiness_contract_valid

API_BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000/api").rstrip("/")
ACTOR_REFERENCE = os.getenv("SMOKE_ACTOR_REFERENCE", "reference-platform-operator")
PRINCIPAL_TYPE = os.getenv("SMOKE_PRINCIPAL_TYPE", "reference_principal")
TIMEOUT_SECONDS = float(os.getenv("SMOKE_TIMEOUT_SECONDS", "30"))


def _headers() -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "X-Authorization-Scope": "platform",
        "X-Principal-Type": PRINCIPAL_TYPE,
        "X-Actor-Reference": ACTOR_REFERENCE,
    }


def _request_json(method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(f"{API_BASE_URL}{path}", data=data, headers=_headers(), method=method)
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        body = response.read().decode("utf-8")
        return json.loads(body) if body else {}


def _call(method: str, path: str, payload: dict[str, Any] | None = None) -> tuple[bool, Any]:
    try:
        return True, _request_json(method, path, payload)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        try:
            details: Any = json.loads(body)
        except json.JSONDecodeError:
            details = body
        return False, {"status": exc.code, "error": details}
    except Exception as exc:  # pragma: no cover - smoke diagnostics
        return False, {"error": str(exc)}


def main() -> int:
    suffix = str(int(time.time()))
    errors: list[dict[str, Any]] = []
    ok, policies = _call("GET", "/platform/security/policies?scope=platform")
    if not ok:
        errors.append({"step": "list_policies", "details": policies})
        policies = []
    active_policy = next(
        (
            item
            for item in policies
            if isinstance(item, dict)
            and item.get("scope") == "platform"
            and item.get("organization_id") is None
            and item.get("status") == "active"
        ),
        None,
    )
    if active_policy is not None:
        policy = active_policy
        ok = True
    else:
        ok, policy = _call(
            "POST",
            "/platform/security/policies",
            {
                "scope": "platform",
                "policy_code": f"smoke-security-policy-{suffix}",
                "name": "Smoke Security Policy",
                "status": "active",
                "authentication_required": True,
                "authorization_required": True,
                "debug_allowed": False,
                "cors_profile": "restricted",
                "provider_execution_policy": "explicit",
                "placeholder_detection_enabled": True,
                "required_secrets": [],
                "required_configuration": [],
                "created_by": ACTOR_REFERENCE,
            },
        )
        if not ok:
            errors.append({"step": "policy", "details": policy})
    ok, evaluate = _call(
        "POST",
        "/platform/security/evaluate",
        {
            "scope": "platform",
            "idempotency_key": f"smoke-security-evaluation-{suffix}",
            "requested_by": ACTOR_REFERENCE,
        },
    )
    if not ok:
        errors.append({"step": "evaluate", "details": evaluate})
    ok, readiness = _call("GET", "/platform/security/readiness?scope=platform")
    if not ok:
        errors.append({"step": "readiness", "details": readiness})
    ok, findings = _call("GET", "/platform/security/findings?scope=platform")
    if not ok:
        errors.append({"step": "findings", "details": findings})
    ok, evidence = _call("GET", "/platform/security/evidence/latest?scope=platform")
    if not ok:
        errors.append({"step": "evidence", "details": evidence})
    ok, configuration = _call("GET", "/platform/security/configuration?scope=platform")
    if not ok:
        errors.append({"step": "configuration", "details": configuration})
    ok, production = _call(
        "POST",
        "/platform/production-acceptance/runs",
        {
            "scope": "platform",
            "idempotency_key": f"smoke-security-production-{suffix}",
            "requested_by": ACTOR_REFERENCE,
        },
    )
    if not ok:
        errors.append({"step": "production_acceptance", "details": production})
    gates = {item.get("gate_code"): item for item in readiness.get("gates", [])} if isinstance(readiness, dict) else {}
    security_acceptance = production.get("security_acceptance", {}) if isinstance(production, dict) else {}
    required_gates = {
        "production_authentication_required",
        "production_configuration_fail_closed",
        "secret_placeholders_absent",
        "cross_organization_access_blocked",
        "audit_runtime_available",
        "debug_disabled",
        "cors_restricted",
        "provider_execution_explicit",
    }
    passed = (
        not errors
        and readiness.get("postgresql_source_of_truth") is True
        and public_readiness_contract_valid(readiness.get("evidence_contract"), domain="security")
        and readiness.get("secrets_exposed") is False
        and readiness.get("llm_used") is False
        and readiness.get("qdrant_used") is False
        and required_gates.issubset(set(gates))
        and isinstance(findings, list)
        and isinstance(evidence, list)
        and isinstance(configuration, dict)
        and security_acceptance.get("status") in {"passed", "blocked", "failed"}
    )
    output = {
        "passed": passed,
        "policy_id": policy.get("id") if isinstance(policy, dict) else None,
        "readiness_status": readiness.get("status") if isinstance(readiness, dict) else None,
        "security_ready": readiness.get("security_ready") if isinstance(readiness, dict) else None,
        "security_acceptance": security_acceptance.get("status"),
        "findings_count": len(findings) if isinstance(findings, list) else None,
        "evidence_count": len(evidence) if isinstance(evidence, list) else None,
        "postgresql_source_of_truth": readiness.get("postgresql_source_of_truth")
        if isinstance(readiness, dict)
        else None,
        "secrets_exposed": readiness.get("secrets_exposed") if isinstance(readiness, dict) else None,
        "llm_used": readiness.get("llm_used") if isinstance(readiness, dict) else None,
        "qdrant_used": readiness.get("qdrant_used") if isinstance(readiness, dict) else None,
        "errors": errors,
    }
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0 if output["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
