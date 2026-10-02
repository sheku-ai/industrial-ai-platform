#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any

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
    component_specs = [
        (
            "monitor",
            "smoke-operational-runtime",
            "Smoke Operational Runtime",
            ["observability", "diagnostics", "bounded_retry"],
        ),
        (
            "scheduler",
            "smoke-scheduler-runtime",
            "Smoke Scheduler Runtime",
            ["scheduling", "dispatch_visibility"],
        ),
        (
            "worker",
            "smoke-worker-runtime",
            "Smoke Worker Runtime",
            ["worker_inventory", "heartbeat"],
        ),
    ]
    components: dict[str, dict[str, Any]] = {}
    for component_type, component_code, display_name, capabilities in component_specs:
        ok, component = _call(
            "POST",
            "/platform/operations/components",
            {
                "scope": "platform",
                "component_code": component_code,
                "component_type": component_type,
                "instance_id": f"{component_type}-{suffix}",
                "display_name": display_name,
                "status": "running",
                "health_status": "healthy",
                "readiness_status": "ready",
                "capabilities": capabilities,
            },
        )
        if not ok:
            errors.append({"step": f"{component_type}_component", "details": component})
            continue
        if isinstance(component, dict):
            components[component_type] = component
    component_id = components.get("monitor", {}).get("id")
    for component_type, component in components.items():
        observed_component_id = component.get("id")
        if not observed_component_id:
            continue
        ok, observation = _call(
            "POST",
            f"/platform/operations/components/{observed_component_id}/observations",
            {
                "observation_type": "readiness",
                "severity": "info",
                "status": "normal",
                "summary": f"Smoke {component_type} component is ready.",
                "source_runtime": "smoke_operational_readiness",
                "evidence_payload": {"smoke": True, "component_type": component_type},
            },
        )
        if not ok:
            errors.append({"step": f"{component_type}_observation", "details": observation})
    ok, execution = _call(
        "POST",
        "/platform/operations/executions",
        {
            "scope": "platform",
            "component_id": component_id,
            "execution_type": "monitoring_check",
            "execution_reference": f"smoke-{suffix}",
            "idempotency_key": f"smoke-operational-execution-{suffix}",
            "status": "running",
            "max_attempts": 3,
            "input_payload": {"smoke": True, "suffix": suffix},
        },
    )
    if not ok:
        errors.append({"step": "execution", "details": execution})
    execution_id = execution.get("id") if isinstance(execution, dict) else None
    retry_id = None
    if execution_id:
        ok, retry = _call(
            "POST",
            f"/platform/operations/executions/{execution_id}/retries",
            {
                "attempt_number": 1,
                "retry_policy_code": "bounded-smoke",
                "status": "succeeded",
                "delay_seconds": 0,
                "retryable": True,
                "decision_reason": "bounded retry behavior smoke evidence",
                "evidence_payload": {"max_attempts": 3, "backoff_strategy": "fixed"},
            },
        )
        if not ok:
            errors.append({"step": "retry", "details": retry})
        retry_id = retry.get("id") if isinstance(retry, dict) else None
        ok, completed = _call(
            "POST",
            f"/platform/operations/executions/{execution_id}/complete",
            {"result_payload": {"completed": True, "retry_id": retry_id}},
        )
        if not ok:
            errors.append({"step": "complete_execution", "details": completed})
    ok, incident = _call(
        "POST",
        "/platform/operations/incidents",
        {
            "scope": "platform",
            "incident_code": f"smoke-operational-incident-{suffix}",
            "incident_type": "other",
            "severity": "warning",
            "component_id": component_id,
            "operational_execution_id": execution_id,
            "source_entity_type": "smoke",
            "source_entity_id": suffix,
            "summary": "Smoke operational incident for recovery evidence.",
            "details": {"smoke": True},
        },
    )
    if not ok:
        errors.append({"step": "incident", "details": incident})
    incident_id = incident.get("id") if isinstance(incident, dict) else None
    action_id = None
    if incident_id:
        ok, action = _call(
            "POST",
            f"/platform/operations/incidents/{incident_id}/recovery-actions",
            {
                "action_type": "manual_recovery",
                "requested_by": ACTOR_REFERENCE,
                "evidence_payload": {"smoke": True, "controlled_recovery": True},
            },
        )
        if not ok:
            errors.append({"step": "recovery_action", "details": action})
        action_id = action.get("id") if isinstance(action, dict) else None
    if action_id:
        ok, action_complete = _call(
            "POST",
            f"/platform/operations/recovery-actions/{action_id}/complete",
            {"result_payload": {"recovery_action_completed": True}},
        )
        if not ok:
            errors.append({"step": "complete_recovery_action", "details": action_complete})
    if incident_id:
        ok, resolved = _call(
            "POST",
            f"/platform/operations/incidents/{incident_id}/resolve",
            {
                "actor_reference": ACTOR_REFERENCE,
                "resolution_code": "smoke_resolved",
                "resolution_summary": "Smoke incident resolved with persisted recovery evidence.",
                "evidence_payload": {"recovered": True, "action_id": action_id},
            },
        )
        if not ok:
            errors.append({"step": "resolve_incident", "details": resolved})
    ok, readiness = _call("GET", "/platform/operations/readiness?scope=platform")
    if not ok:
        errors.append({"step": "readiness", "details": readiness})
    ok, production = _call(
        "POST",
        "/platform/production-acceptance/runs",
        {
            "scope": "platform",
            "idempotency_key": f"smoke-operational-production-{suffix}",
            "requested_by": ACTOR_REFERENCE,
        },
    )
    if not ok:
        errors.append({"step": "production_acceptance", "details": production})
    gates = {item.get("gate_code"): item for item in readiness.get("gates", [])} if isinstance(readiness, dict) else {}
    operational_acceptance = production.get("operational_acceptance", {}) if isinstance(production, dict) else {}
    passed = (
        not errors
        and readiness.get("postgresql_source_of_truth") is True
        and readiness.get("llm_used") is False
        and readiness.get("qdrant_used") is False
        and gates.get("runtime_observability_available", {}).get("status") == "passed"
        and gates.get("bounded_retry_behavior_available", {}).get("status") == "passed"
        and gates.get("failure_recovery_evidence_available", {}).get("status") == "passed"
        and operational_acceptance.get("status") in {"passed", "blocked", "failed"}
    )
    output = {
        "passed": passed,
        "component_id": component_id,
        "scheduler_component_id": components.get("scheduler", {}).get("id"),
        "worker_component_id": components.get("worker", {}).get("id"),
        "execution_id": execution_id,
        "retry_id": retry_id,
        "incident_id": incident_id,
        "recovery_action_id": action_id,
        "operational_readiness": readiness.get("status") if isinstance(readiness, dict) else None,
        "operational_acceptance": operational_acceptance.get("status"),
        "postgresql_source_of_truth": readiness.get("postgresql_source_of_truth")
        if isinstance(readiness, dict)
        else None,
        "side_effects_performed": readiness.get("side_effects_performed") if isinstance(readiness, dict) else None,
        "external_calls_performed": readiness.get("external_calls_performed") if isinstance(readiness, dict) else None,
        "llm_used": readiness.get("llm_used") if isinstance(readiness, dict) else None,
        "qdrant_used": readiness.get("qdrant_used") if isinstance(readiness, dict) else None,
        "errors": errors,
    }
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0 if output["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
