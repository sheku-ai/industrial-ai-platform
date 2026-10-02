#!/usr/bin/env python3
"""Fast contract for the operational diagnostics API endpoint."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "apps" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.api.routes.platform_diagnostics import router as diagnostics_router  # noqa: E402


CLI = ROOT / "scripts" / "platform_diagnostics.py"


def require_keys(payload: dict, keys: set[str], context: str) -> None:
    missing = sorted(keys - set(payload))
    if missing:
        raise AssertionError(f"{context} missing keys: {missing}")


def run_cli_diagnostics() -> dict:
    completed = subprocess.run(
        [sys.executable, str(CLI)],
        cwd=str(ROOT),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    try:
        payload = json.loads(completed.stdout)
    except Exception as exc:  # pragma: no cover - diagnostic failure path
        raise AssertionError(
            f"expected CLI JSON stdout rc={completed.returncode} stdout={completed.stdout!r} stderr={completed.stderr!r}"
        ) from exc
    if completed.returncode != 0:
        raise AssertionError(f"CLI diagnostics failed rc={completed.returncode} payload={payload}")
    return payload


def main() -> int:
    app = FastAPI()
    app.include_router(diagnostics_router, prefix="/api")
    client = TestClient(app)

    response = client.get("/api/platform/diagnostics")
    if response.status_code != 200:
        raise AssertionError(f"expected HTTP 200, got {response.status_code}: {response.text}")

    payload = response.json()
    expected = run_cli_diagnostics()
    if payload != expected:
        raise AssertionError("endpoint payload must match scripts/platform_diagnostics.py output")

    require_keys(
        payload,
        {
            "critical_services",
            "degraded_capabilities",
            "enabled_feature_flags",
            "lifecycle_readiness",
            "migrations",
            "optional_services",
            "overall_status",
            "platform",
            "runtime_profiles",
        },
        "diagnostics endpoint",
    )

    if payload.get("plan") != "platform_diagnostics":
        raise AssertionError("diagnostics endpoint must return plan=platform_diagnostics")
    if payload["overall_status"] not in {"ready", "degraded", "critical"}:
        raise AssertionError("overall_status must be ready, degraded or critical")
    if payload.get("destructive_action_executed") is not False:
        raise AssertionError("diagnostics endpoint must not execute destructive actions")
    if payload.get("migration_executed") is not False:
        raise AssertionError("diagnostics endpoint must not run migrations")
    if payload.get("downgrade_executed") is not False:
        raise AssertionError("diagnostics endpoint must not run downgrades")

    print(json.dumps({"passed": True, "checked": ["platform-diagnostics-api"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
