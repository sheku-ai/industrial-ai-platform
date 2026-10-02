from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
import uuid
from datetime import UTC, datetime, timedelta

from readiness_contract_smoke import public_readiness_contract_valid

API_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000/api").rstrip("/")
TIMEOUT = float(os.getenv("SMOKE_TIMEOUT_SECONDS", "30"))
HEADERS = {
    "Content-Type": "application/json",
    "X-Authorization-Scope": "platform",
    "X-Principal-Type": os.getenv("PLATFORM_PRINCIPAL_TYPE", "reference_principal"),
    "X-Actor-Reference": os.getenv("PLATFORM_ACTOR_REFERENCE", "reference-platform-operator"),
    "X-Correlation-ID": f"observability-smoke-{uuid.uuid4()}",
}


def request(method: str, path: str, payload: dict | None = None):
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(f"{API_URL}{path}", data=body, headers=HEADERS, method=method)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8"))
        except Exception:
            detail = {"error": str(exc)}
        return exc.code, detail


def main() -> int:
    now = datetime.now(UTC)
    run = uuid.uuid4().hex
    errors: list[dict] = []

    def post(path: str, payload: dict):
        code, result = request("POST", path, payload)
        if code not in {200, 201}:
            errors.append({"step": path, "status": code, "detail": result})
            return {}
        return result

    profile = post(
        "/platform/observability/profiles",
        {
            "scope": "platform",
            "profile_code": f"observability-smoke-{run}",
            "name": "Observability smoke profile",
            "version": "1",
            "status": "active",
            "evidence_max_age_seconds": 3600,
            "heartbeat_max_age_seconds": 600,
            "minimum_availability_percentage": 99,
            "minimum_signal_coverage_percentage": 100,
        },
    )
    domain = (
        post(
            "/platform/observability/domains",
            {
                "scope": "platform",
                "profile_id": profile.get("id"),
                "domain_code": "platform-runtime",
                "name": "Platform Runtime",
                "version": "1",
                "required_component_codes": ["api"],
            },
        )
        if profile
        else {}
    )
    component = (
        post(
            "/platform/observability/components",
            {
                "scope": "platform",
                "health_domain_id": domain.get("id"),
                "component_code": "api",
                "name": "Platform API",
                "component_type": "application_runtime",
                "version": "1",
                "required": True,
                "required_signal_codes": ["health", "availability"],
            },
        )
        if domain
        else {}
    )
    if component:
        expires = (now + timedelta(hours=1)).isoformat()
        post(
            "/platform/observability/dependencies",
            {
                "component_id": component["id"],
                "dependency_code": "postgresql",
                "name": "PostgreSQL",
                "dependency_type": "database",
                "version": "1",
                "status": "active",
                "critical": True,
                "origin": "smoke",
                "source": "smoke_observability_runtime_e2e",
                "observed_at": now.isoformat(),
                "expires_at": expires,
            },
        )
        for signal_code in ("health", "availability"):
            post(
                "/platform/observability/signals",
                {
                    "component_id": component["id"],
                    "signal_code": signal_code,
                    "signal_type": "health",
                    "status": "healthy",
                    "severity": "info",
                    "value": 1,
                    "unit": "state",
                    "origin": "smoke",
                    "source": "smoke_observability_runtime_e2e",
                    "evidence_payload": {"verified": True},
                    "idempotency_key": f"{run}-{signal_code}",
                    "observed_at": now.isoformat(),
                    "expires_at": expires,
                },
            )
        post(
            "/platform/observability/heartbeats",
            {
                "component_id": component["id"],
                "status": "healthy",
                "origin": "smoke",
                "source": "smoke_observability_runtime_e2e",
                "sequence": 1,
                "idempotency_key": f"{run}-heartbeat",
                "observed_at": now.isoformat(),
                "expires_at": expires,
            },
        )
        post(
            "/platform/observability/availability",
            {
                "component_id": component["id"],
                "status": "healthy",
                "window_start": (now - timedelta(minutes=10)).isoformat(),
                "window_end": now.isoformat(),
                "available_seconds": 600,
                "unavailable_seconds": 0,
                "origin": "smoke",
                "source": "smoke_observability_runtime_e2e",
                "idempotency_key": f"{run}-availability",
            },
        )
    evaluation = (
        post(
            "/platform/observability/evaluations",
            {
                "scope": "platform",
                "profile_id": profile.get("id"),
                "idempotency_key": f"{run}-evaluation",
            },
        )
        if profile
        else {}
    )
    readiness_code, readiness = request("GET", "/platform/observability/readiness")
    latest_code, latest = request("GET", "/platform/observability/latest")
    passed = bool(
        not errors
        and evaluation
        and readiness_code == 200
        and public_readiness_contract_valid(readiness.get("evidence_contract"), domain="observability")
        and readiness.get("status") == "passed"
        and readiness.get("acceptance_status") == "passed"
        and len(readiness.get("gate_results") or []) == 5
        and all(item.get("status") == "passed" for item in readiness.get("gate_results") or [])
        and latest_code == 200
        and latest.get("found") is True
        and readiness.get("postgresql_source_of_truth") is True
        and readiness.get("llm_used") is False
        and readiness.get("qdrant_used") is False
    )
    result = {
        "passed": passed,
        "profile_id": profile.get("id"),
        "component_id": component.get("id"),
        "evaluation_id": evaluation.get("id"),
        "readiness_status": readiness.get("status") if isinstance(readiness, dict) else None,
        "acceptance_status": readiness.get("acceptance_status") if isinstance(readiness, dict) else None,
        "gate_statuses": {item.get("gate_code"): item.get("status") for item in readiness.get("gate_results", [])}
        if isinstance(readiness, dict)
        else {},
        "errors": errors,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
