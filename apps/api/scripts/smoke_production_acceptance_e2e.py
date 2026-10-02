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

API_BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000/api").rstrip("/")
ACTOR_REFERENCE = os.getenv("SMOKE_ACTOR_REFERENCE", "reference-platform-operator")
PRINCIPAL_TYPE = os.getenv("SMOKE_PRINCIPAL_TYPE", "reference_principal")
IDEMPOTENCY_KEY = os.getenv(
    "SMOKE_PRODUCTION_ACCEPTANCE_IDEMPOTENCY_KEY",
    f"smoke-production-acceptance-{int(time.time())}",
)
TIMEOUT_SECONDS = float(os.getenv("SMOKE_TIMEOUT_SECONDS", "30"))


def _headers() -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "X-Authorization-Scope": "platform",
        "X-Principal-Type": PRINCIPAL_TYPE,
        "X-Actor-Reference": ACTOR_REFERENCE,
    }


def _request_json(method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    data = json.dumps(payload or {}).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        f"{API_BASE_URL}{path}",
        data=data,
        headers=_headers(),
        method=method,
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        body = response.read().decode("utf-8")
        return json.loads(body) if body else {}


def _safe_call(method: str, path: str, payload: dict[str, Any] | None = None) -> tuple[bool, dict[str, Any]]:
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
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    created, run = _safe_call(
        "POST",
        "/platform/production-acceptance/runs",
        {
            "scope": "platform",
            "idempotency_key": IDEMPOTENCY_KEY,
            "requested_by": ACTOR_REFERENCE,
        },
    )
    if not created:
        errors.append({"step": "create_run", "details": run})
    run_id = run.get("run_id") if created else None
    replay_ok, replay = _safe_call(
        "POST",
        "/platform/production-acceptance/runs",
        {
            "scope": "platform",
            "idempotency_key": IDEMPOTENCY_KEY,
            "requested_by": ACTOR_REFERENCE,
        },
    )
    if not replay_ok or replay.get("run_id") != run_id or replay.get("reused") is not True:
        errors.append({"step": "idempotency_replay", "details": replay})
    read_ok, read_payload = (False, {})
    if run_id:
        read_ok, read_payload = _safe_call("GET", f"/platform/production-acceptance/runs/{run_id}")
        if not read_ok:
            errors.append({"step": "read_run", "details": read_payload})
    latest_ok, latest = _safe_call("GET", "/platform/production-acceptance/latest?scope=platform")
    if not latest_ok:
        errors.append({"step": "latest", "details": latest})
    readiness_ok, readiness = _safe_call("GET", "/platform/production-acceptance/workspace?scope=platform")
    if not readiness_ok:
        errors.append({"step": "readiness", "details": readiness})
    preflight_ok, preflight = _safe_call("GET", "/platform/configuration/preflight?profile=production")
    if not preflight_ok:
        errors.append({"step": "preflight", "details": preflight})
    observability_ok, observability = _safe_call("GET", "/platform/observability/readiness")
    if not observability_ok:
        errors.append({"step": "observability", "details": observability})

    latest_result = latest.get("result") if isinstance(latest.get("result"), dict) else {}
    gate_results = run.get("gate_results") if isinstance(run.get("gate_results"), list) else []
    observability_gate_codes = {
        item.get("gate_code")
        for item in gate_results
        if str(item.get("gate_code") or "").startswith("observability_")
    }
    evidence_contracts = run.get("evidence_contracts", [])
    passed = (
        created
        and read_ok
        and latest_ok
        and readiness_ok
        and preflight_ok
        and observability_ok
        and bool(run_id)
        and replay_ok
        and replay.get("run_id") == run_id
        and replay.get("reused") is True
        and run.get("status") in {"passed", "failed", "blocked", "expired", "stale", "interrupted"}
        and readiness.get("release_candidate_eligible") in {True, False}
        and readiness.get("production_ready") in {True, False}
        and preflight.get("secrets_exposed") is False
        and latest_result.get("run_id") == run_id
        and len(evidence_contracts) == 7
        and all(public_readiness_contract_valid(item) for item in evidence_contracts)
        and observability_gate_codes == {
            "observability_evidence_available",
            "observability_health_verified",
            "observability_signal_coverage",
            "observability_component_readiness",
            "observability_freshness_valid",
        }
    )
    if run.get("production_ready") is True:
        warnings.append(
            {"code": "production_ready_true", "message": "Production ready is true; verify all gates have evidence."}
        )
    output = {
        "passed": passed and not errors,
        "run_id": run_id,
        "run_status": run.get("status"),
        "idempotency_replay": replay_ok and replay.get("run_id") == run_id and replay.get("reused") is True,
        "production_ready": run.get("production_ready"),
        "release_candidate_eligible": readiness.get("release_candidate_eligible"),
        "latest_found": latest.get("found"),
        "preflight_status": preflight.get("status"),
        "observability_status": observability.get("status"),
        "observability_gate_statuses": {
            item.get("gate_code"): item.get("status")
            for item in gate_results
            if item.get("gate_code") in observability_gate_codes
        },
        "postgresql_source_of_truth": readiness.get("postgresql_source_of_truth"),
        "llm_used": readiness.get("llm_used"),
        "qdrant_used": readiness.get("qdrant_used"),
        "warnings": warnings,
        "errors": errors,
    }
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0 if output["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
