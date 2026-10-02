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

API_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000/api").rstrip("/")
ACTOR = os.getenv("SMOKE_ACTOR_REFERENCE", "reference-platform-operator")
RUN_KEY = os.getenv("SMOKE_PRODUCTION_INTEGRATION_KEY", f"production-integration-{int(time.time())}")
TIMEOUT = float(os.getenv("SMOKE_TIMEOUT_SECONDS", "45"))


def _call(method: str, path: str, payload: dict[str, Any] | None = None) -> tuple[bool, Any]:
    request = urllib.request.Request(
        f"{API_URL}{path}",
        data=json.dumps(payload).encode() if payload is not None else None,
        method=method,
        headers={
            "Content-Type": "application/json",
            "X-Authorization-Scope": "platform",
            "X-Principal-Type": "reference_principal",
            "X-Actor-Reference": ACTOR,
            "X-Correlation-ID": RUN_KEY,
        },
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
    recovery_ok, recovery = _call("GET", "/platform/recovery/readiness?scope=platform")
    capacity_ok, capacity = _call("GET", "/platform/capacity/readiness?scope=platform")
    portal_ok, portal = _call("GET", "/platform/portal-acceptance/readiness")
    run_ok, result = _call(
        "POST",
        "/platform/production-acceptance/runs",
        {
            "scope": "platform",
            "idempotency_key": RUN_KEY,
            "requested_by": ACTOR,
        },
    )
    summaries = {
        domain: result.get(f"{domain}_acceptance", {})
        for domain in ("functional", "operational", "security", "recovery", "deployment", "capacity", "portal")
    }
    consistent = (
        summaries["recovery"].get("status") == recovery.get("status")
        and summaries["capacity"].get("status") == capacity.get("status")
        and summaries["portal"].get("status") == portal.get("status")
    )
    preflight = result.get("configuration_preflight") or {}
    evidence_contracts = {
        item.get("domain"): item for item in result.get("evidence_contracts", [])
    }
    passed = (
        recovery_ok
        and capacity_ok
        and portal_ok
        and run_ok
        and consistent
        and len(evidence_contracts) == 7
        and all(public_readiness_contract_valid(contract) for contract in evidence_contracts.values())
        and result.get("contract_version") == "production_acceptance.v5"
    )
    print(
        json.dumps(
            {
                "passed": passed,
                "consistent": consistent,
                "domain_statuses": {key: value.get("status") for key, value in summaries.items()},
                "specialized_statuses": {
                    "recovery": recovery.get("status"),
                    "capacity": capacity.get("status"),
                    "portal": portal.get("status"),
                },
                "preflight": preflight.get("status"),
                "evidence_contracts": sorted(evidence_contracts),
                "production_ready": result.get("production_ready"),
                "blockers": result.get("blockers", []),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
