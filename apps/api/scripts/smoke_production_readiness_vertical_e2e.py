#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any

from readiness_contract_smoke import public_readiness_contract_valid

ROOT_URL = os.getenv("API_ROOT_URL", "http://127.0.0.1:8000").rstrip("/")
API_URL = f"{ROOT_URL}/api"
ACTOR = os.getenv("SMOKE_ACTOR_REFERENCE", "reference-platform-operator")
CORRELATION_ID = os.getenv("SMOKE_CORRELATION_ID", f"production-readiness-smoke-{int(time.time())}")
TIMEOUT_SECONDS = float(os.getenv("SMOKE_TIMEOUT_SECONDS", "45"))


def _request(method: str, url: str, payload: dict[str, Any] | None = None) -> tuple[dict[str, Any], str | None]:
    body = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={
            "Content-Type": "application/json",
            "X-Authorization-Scope": "platform",
            "X-Principal-Type": "reference_principal",
            "X-Actor-Reference": ACTOR,
            "X-Correlation-ID": CORRELATION_ID,
        },
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        data = response.read().decode()
        return (json.loads(data) if data else {}), response.headers.get("X-Correlation-ID")


def _call(method: str, url: str, payload: dict[str, Any] | None = None) -> tuple[bool, dict[str, Any], str | None]:
    try:
        result, correlation = _request(method, url, payload)
        return True, result, correlation
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        try:
            detail: Any = json.loads(raw)
        except json.JSONDecodeError:
            detail = raw
        return False, {"status": exc.code, "detail": detail}, exc.headers.get("X-Correlation-ID")
    except Exception as exc:  # pragma: no cover - smoke diagnostics
        return False, {"error": str(exc)}, None


def main() -> int:
    errors: list[dict[str, Any]] = []
    observations: dict[str, Any] = {}
    calls = (
        ("health", "GET", f"{ROOT_URL}/health", None),
        ("ready", "GET", f"{ROOT_URL}/health/ready", None),
        ("preflight", "GET", f"{API_URL}/platform/configuration/preflight?profile=production", None),
        ("observability", "GET", f"{API_URL}/platform/observability/readiness", None),
        ("capacity", "GET", f"{API_URL}/platform/capacity/readiness", None),
        ("production_readiness", "GET", f"{API_URL}/platform/production-readiness/runtime", None),
    )
    for name, method, url, payload in calls:
        ok, result, response_correlation = _call(method, url, payload)
        observations[name] = result
        if not ok:
            errors.append({"step": name, "details": result})
        if response_correlation != CORRELATION_ID:
            errors.append({"step": name, "details": "correlation_header_not_propagated"})

    created, run, run_correlation = _call(
        "POST",
        f"{API_URL}/platform/production-acceptance/runs",
        {
            "scope": "platform",
            "idempotency_key": f"{CORRELATION_ID}-acceptance",
            "requested_by": ACTOR,
        },
    )
    if not created:
        errors.append({"step": "production_acceptance", "details": run})
    if run_correlation != CORRELATION_ID or run.get("correlation_id") != CORRELATION_ID:
        errors.append({"step": "production_acceptance", "details": "correlation_not_persisted"})
    readiness_ok, production_readiness, readiness_correlation = _call(
        "GET",
        f"{API_URL}/platform/production-readiness/runtime",
    )
    observations["production_readiness"] = production_readiness
    if not readiness_ok or readiness_correlation != CORRELATION_ID:
        errors.append({"step": "production_readiness_after_acceptance", "details": production_readiness})

    trace_ok, trace, _ = _call(
        "GET",
        f"{API_URL}/platform/operations/correlations/{CORRELATION_ID}",
    )
    if not trace_ok or trace.get("found") is not True:
        errors.append({"step": "correlation_trace", "details": trace})

    gate_results = run.get("gate_results") if isinstance(run.get("gate_results"), list) else []
    domains = {item.get("domain") for item in gate_results}
    acceptance_contract_valid = (
        domains == {"functional", "operational", "security", "recovery", "deployment", "capacity", "portal"}
        and all(isinstance(item.get("duration_ms"), int) for item in gate_results)
        and all(isinstance(item.get("components_evaluated"), list) for item in gate_results)
        and all(item.get("evidence_origin") for item in gate_results)
    )
    preflight = observations.get("preflight") or {}
    observability = observations.get("observability") or {}
    capacity = observations.get("capacity") or {}
    production_readiness = observations.get("production_readiness") or {}
    evidence_contracts = production_readiness.get("evidence_contracts") or []
    passed = (
        not errors
        and acceptance_contract_valid
        and preflight.get("secrets_exposed") is False
        and observability.get("postgresql_source_of_truth") is True
        and len(observability.get("gate_results") or []) == 5
        and len(evidence_contracts) == 7
        and all(public_readiness_contract_valid(item) for item in evidence_contracts)
        and production_readiness.get("workspace_summary", {}).get("acceptance_run_id") == run.get("run_id")
        and capacity.get("postgresql_source_of_truth") is True
    )
    output = {
        "passed": passed,
        "correlation_id": CORRELATION_ID,
        "production_acceptance_status": run.get("status"),
        "production_ready": run.get("production_ready"),
        "preflight_status": preflight.get("status"),
        "observability_status": observability.get("status"),
        "capacity_status": capacity.get("status"),
        "trace_record_count": trace.get("record_count") if trace_ok else 0,
        "acceptance_contract_valid": acceptance_contract_valid,
        "errors": errors,
    }
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
