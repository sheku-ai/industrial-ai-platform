#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from typing import Any

from readiness_contract_smoke import public_readiness_contract_valid

API_BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000/api").rstrip("/")
ACTOR = os.getenv("SMOKE_ACTOR_REFERENCE", "reference-platform-operator")
PRINCIPAL_TYPE = os.getenv("SMOKE_PRINCIPAL_TYPE", "reference_principal")
RUN_KEY = os.getenv("SMOKE_CAPACITY_RUN_KEY", f"capacity-smoke-{int(time.time())}")
TIMEOUT = float(os.getenv("SMOKE_TIMEOUT_SECONDS", "30"))
METRICS = ("concurrent_requests", "ingestion", "search", "assistant", "queue", "worker", "storage", "database")


def _call(method: str, path: str, payload: dict[str, Any] | None = None) -> tuple[bool, Any]:
    request = urllib.request.Request(
        f"{API_BASE_URL}{path}",
        data=json.dumps(payload).encode("utf-8") if payload is not None else None,
        method=method,
        headers={
            "Content-Type": "application/json",
            "X-Authorization-Scope": "platform",
            "X-Actor-Reference": ACTOR,
            "X-Principal-Type": PRINCIPAL_TYPE,
            "X-Correlation-ID": RUN_KEY,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            body = response.read().decode("utf-8")
            return True, json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        try:
            details = json.loads(body)
        except json.JSONDecodeError:
            details = body
        return False, {"status": exc.code, "details": details}
    except Exception as exc:
        return False, {"error": str(exc)}


def main() -> int:
    errors: list[dict[str, Any]] = []
    vector = {metric: 100 for metric in METRICS}
    ok, profile = _call(
        "POST",
        "/platform/capacity/profiles",
        {
            "scope": "platform",
            "profile_code": RUN_KEY,
            "name": "Governed Capacity Smoke Profile",
            "version": "1",
            "status": "active",
            "configured_capacity": vector,
            "target_capacity": vector,
            "evidence_max_age_hours": 24,
            "created_by": ACTOR,
        },
    )
    if not ok:
        errors.append({"step": "create_profile", "details": profile})
    ok, execution = _call(
        "POST",
        "/platform/capacity/load-tests",
        {
            "scope": "platform",
            "profile_id": profile.get("id"),
            "execution_name": "Governed Capacity Smoke Load Evidence",
            "scenario": "controlled_external_load_evidence",
            "concurrent_requests": 100,
            "duration_seconds": 60,
            "requests_planned": 800,
            "idempotency_key": f"{RUN_KEY}:load",
            "requested_by": ACTOR,
            "execution_metadata": {"external_execution": True, "generated_load": False},
        },
    ) if not errors else (False, {})
    if not ok:
        errors.append({"step": "register_load_test", "details": execution})
    observed_at = datetime.now(UTC).isoformat()
    result_ids: list[str] = []
    if not errors:
        for metric in METRICS:
            result_ok, result = _call(
                "POST",
                f"/platform/capacity/load-tests/{execution['id']}/results",
                {
                    "metric_code": metric,
                    "component": metric,
                    "observed_value": 100,
                    "target_value": 100,
                    "unit": "capacity_units",
                    "sample_count": 100,
                    "percentile_values": {},
                    "details": {"evidence_source": "controlled_smoke_evidence"},
                    "observed_at": observed_at,
                },
            )
            if result_ok:
                result_ids.append(result.get("id"))
            else:
                errors.append({"step": f"register_{metric}_result", "details": result})
    complete_ok, completed = _call(
        "POST",
        f"/platform/capacity/load-tests/{execution.get('id')}/complete",
        {"status": "completed", "requests_completed": 800, "requests_failed": 0},
    ) if not errors else (False, {})
    if not complete_ok:
        errors.append({"step": "complete_load_test", "details": completed})
    evaluated_ok, evaluation = _call(
        "POST",
        "/platform/capacity/evaluations",
        {
            "scope": "platform",
            "profile_id": profile.get("id"),
            "load_test_execution_id": execution.get("id"),
            "idempotency_key": f"{RUN_KEY}:evaluation",
            "requested_by": ACTOR,
        },
    ) if not errors else (False, {})
    if not evaluated_ok:
        errors.append({"step": "evaluate_capacity", "details": evaluation})
    evidence_ok, evidence = _call(
        "POST",
        f"/platform/capacity/evaluations/{evaluation.get('id')}/evidence",
        {
            "evidence_code": "smoke_execution_manifest",
            "evidence_type": "external_execution_manifest",
            "source_runtime": "smoke_capacity_readiness_e2e",
            "source_reference": RUN_KEY,
            "evidence_payload": {"result_ids": result_ids, "external_execution": True},
            "observed_at": observed_at,
        },
    ) if not errors else (False, {})
    if not evidence_ok:
        errors.append({"step": "register_evidence", "details": evidence})
    readiness_ok, readiness = _call("GET", "/platform/capacity/readiness?scope=platform")
    latest_ok, latest = _call("GET", "/platform/capacity/latest")
    history_ok, history = _call("GET", "/platform/capacity/history")
    gate_status = {item.get("gate_code"): item.get("status") for item in readiness.get("gate_results", [])}
    expected_gates = {
        "capacity_profile_defined",
        "load_test_completed",
        "capacity_validated",
        "capacity_bottlenecks_resolved",
        "production_capacity_ready",
    }
    passed = (
        not errors
        and readiness_ok
        and public_readiness_contract_valid(readiness.get("evidence_contract"), domain="capacity")
        and latest_ok
        and history_ok
        and readiness.get("status") == "passed"
        and readiness.get("postgresql_source_of_truth") is True
        and readiness.get("llm_used") is False
        and readiness.get("qdrant_used") is False
        and set(gate_status) == expected_gates
        and all(status == "passed" for status in gate_status.values())
        and latest.get("found") is True
        and len(history) >= len(METRICS)
    )
    output = {
        "passed": passed,
        "profile_id": profile.get("id"),
        "load_test_execution_id": execution.get("id"),
        "evaluation_id": evaluation.get("id"),
        "evidence_id": evidence.get("id"),
        "result_ids": result_ids,
        "readiness_status": readiness.get("status"),
        "gate_status": gate_status,
        "blocker_count": readiness.get("blocker_count"),
        "recommendation_count": readiness.get("recommendation_count"),
        "history_count": len(history) if isinstance(history, list) else 0,
        "postgresql_source_of_truth": readiness.get("postgresql_source_of_truth"),
        "llm_used": readiness.get("llm_used"),
        "qdrant_used": readiness.get("qdrant_used"),
        "errors": errors,
    }
    print(json.dumps(output, indent=2, sort_keys=True, default=str))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
