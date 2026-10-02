#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from typing import Any

from readiness_contract_smoke import public_readiness_contract_valid

API_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000/api").rstrip("/")
ACTOR = os.getenv("SMOKE_ACTOR_REFERENCE", "reference-platform-operator")
RUN_CODE = os.getenv("SMOKE_PORTAL_ACCEPTANCE_RUN", f"portal-acceptance-{int(time.time())}")
TIMEOUT = float(os.getenv("SMOKE_TIMEOUT_SECONDS", "30"))
VALIDATION_TYPES = (
    "principal_routes",
    "portal_build",
    "portal_contract",
    "negative_states",
    "permission_states",
    "cross_organization_states",
)


def _call(
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    *,
    actor: str | None = ACTOR,
    principal_type: str = "reference_principal",
) -> tuple[bool, Any]:
    headers = {
        "Content-Type": "application/json",
        "X-Authorization-Scope": "platform",
        "X-Principal-Type": principal_type,
        "X-Correlation-ID": RUN_CODE,
    }
    if actor is not None:
        headers["X-Actor-Reference"] = actor
    request = urllib.request.Request(
        f"{API_URL}{path}",
        data=json.dumps(payload).encode() if payload is not None else None,
        method=method,
        headers=headers,
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            raw = response.read().decode()
            return True, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        try:
            detail = json.loads(raw)
        except json.JSONDecodeError:
            detail = raw
        return False, {"status": exc.code, "detail": detail}
    except Exception as exc:
        return False, {"error": str(exc)}


def main() -> int:
    now = datetime.now(UTC).replace(microsecond=0)
    errors: list[dict[str, Any]] = []
    evidence_ids: list[str] = []
    first_payload: dict[str, Any] | None = None
    first_evidence_id: str | None = None
    for validation_type in VALIDATION_TYPES:
        payload = {
            "scope": "platform",
            "validation_run_code": RUN_CODE,
            "validation_type": validation_type,
            "status": "passed",
            "source": "controlled_external_portal_validation",
            "source_reference": f"artifact:{RUN_CODE}:{validation_type}",
            "evidence_payload": {
                "validation_type": validation_type,
                "controlled_external_validation": True,
                "browser_execution_performed_by_api": False,
            },
            "started_at": (now - timedelta(minutes=1)).isoformat(),
            "completed_at": now.isoformat(),
            "observed_at": now.isoformat(),
            "expires_at": (now + timedelta(days=7)).isoformat(),
            "created_by": ACTOR,
        }
        ok, evidence = _call(
            "POST",
            "/platform/portal-acceptance/evidence",
            payload,
        )
        if ok:
            evidence_ids.append(evidence.get("id"))
            if first_payload is None:
                first_payload = payload
                first_evidence_id = evidence.get("id")
        else:
            errors.append({"step": validation_type, "detail": evidence})

    replay_ok, replay = (
        _call("POST", "/platform/portal-acceptance/evidence", first_payload) if first_payload else (False, {})
    )
    replay_passed = replay_ok and replay.get("id") == first_evidence_id
    if not replay_passed:
        errors.append({"step": "idempotency_replay", "detail": replay})

    conflict_payload = dict(first_payload or {})
    conflict_payload["status"] = "failed"
    conflict_ok, conflict = _call("POST", "/platform/portal-acceptance/evidence", conflict_payload)
    duplicate_conflict_passed = not conflict_ok and conflict.get("status") == 409
    if not duplicate_conflict_passed:
        errors.append({"step": "duplicate_conflict", "detail": conflict})

    expired_run_code = f"{RUN_CODE}-expired"
    expired_observed_at = now - timedelta(days=2)
    for validation_type in VALIDATION_TYPES:
        expired_ok, expired_evidence = _call(
            "POST",
            "/platform/portal-acceptance/evidence",
            {
                "scope": "platform",
                "validation_run_code": expired_run_code,
                "validation_type": validation_type,
                "status": "passed",
                "source": "controlled_expired_portal_validation",
                "source_reference": f"artifact:{expired_run_code}:{validation_type}",
                "evidence_payload": {"validation_type": validation_type, "expired_scenario": True},
                "started_at": (expired_observed_at - timedelta(minutes=1)).isoformat(),
                "completed_at": expired_observed_at.isoformat(),
                "observed_at": expired_observed_at.isoformat(),
                "expires_at": (now - timedelta(days=1)).isoformat(),
                "created_by": ACTOR,
            },
        )
        if not expired_ok:
            errors.append({"step": f"expired_{validation_type}", "detail": expired_evidence})
    expired_ok, expired_readiness = _call(
        "GET",
        f"/platform/portal-acceptance/readiness?validation_run_code={expired_run_code}",
    )
    expired_passed = expired_ok and expired_readiness.get("status") == "expired"
    if not expired_passed:
        errors.append({"step": "expired_readiness", "detail": expired_readiness})

    missing_ok, missing_readiness = _call(
        "GET",
        f"/platform/portal-acceptance/readiness?validation_run_code={RUN_CODE}-missing",
    )
    missing_passed = missing_ok and missing_readiness.get("status") == "not_evaluated"
    if not missing_passed:
        errors.append({"step": "missing_evidence", "detail": missing_readiness})

    unauthorized_ok, unauthorized = _call(
        "GET",
        "/platform/portal-acceptance/readiness",
        actor="runtime-hardening-no-permissions",
        principal_type="runtime_hardening_unauthorized",
    )
    permission_passed = not unauthorized_ok and unauthorized.get("status") == 403
    if not permission_passed:
        errors.append({"step": "permission_denied", "detail": unauthorized})

    unauthenticated_ok, unauthenticated = _call("GET", "/platform/portal-acceptance/readiness", actor=None)
    authentication_passed = not unauthenticated_ok and unauthenticated.get("status") == 401
    if not authentication_passed:
        errors.append({"step": "authentication_required", "detail": unauthenticated})
    readiness_ok, readiness = _call(
        "GET",
        f"/platform/portal-acceptance/readiness?validation_run_code={RUN_CODE}",
    )
    latest_ok, latest = _call("GET", "/platform/portal-acceptance/latest")
    gate_statuses = {item.get("gate_code"): item.get("status") for item in readiness.get("gate_results", [])}
    passed = (
        not errors
        and readiness_ok
        and public_readiness_contract_valid(readiness.get("evidence_contract"), domain="portal")
        and latest_ok
        and readiness.get("status") == "passed"
        and len(gate_statuses) == 6
        and all(status == "passed" for status in gate_statuses.values())
        and latest.get("validation_run_code") == RUN_CODE
        and readiness.get("postgresql_source_of_truth") is True
        and readiness.get("browser_execution_performed") is False
        and replay_passed
        and duplicate_conflict_passed
        and expired_passed
        and permission_passed
        and authentication_passed
        and missing_passed
    )
    print(
        json.dumps(
            {
                "passed": passed,
                "validation_run_code": RUN_CODE,
                "evidence_ids": evidence_ids,
                "readiness_status": readiness.get("status"),
                "gate_statuses": gate_statuses,
                "idempotency_replay": replay_passed,
                "duplicate_conflict": duplicate_conflict_passed,
                "expired_evidence": expired_passed,
                "permission_denied": permission_passed,
                "authentication_required": authentication_passed,
                "missing_evidence": missing_passed,
                "errors": errors,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
