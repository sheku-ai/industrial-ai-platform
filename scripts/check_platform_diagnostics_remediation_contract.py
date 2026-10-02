#!/usr/bin/env python3
"""Fast contract for the operational diagnostics remediation API endpoint."""

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


def run_cli_remediation() -> dict:
    completed = subprocess.run(
        [sys.executable, str(CLI), "--remediation"],
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
            f"expected CLI remediation JSON rc={completed.returncode} stdout={completed.stdout!r} stderr={completed.stderr!r}"
        ) from exc
    if completed.returncode != 0:
        raise AssertionError(f"CLI diagnostics remediation failed rc={completed.returncode} payload={payload}")
    return payload


def main() -> int:
    app = FastAPI()
    app.include_router(diagnostics_router, prefix="/api")
    client = TestClient(app)

    response = client.get("/api/platform/diagnostics/remediation")
    if response.status_code != 200:
        raise AssertionError(f"expected HTTP 200, got {response.status_code}: {response.text}")

    payload = response.json()
    if payload != run_cli_remediation():
        raise AssertionError("remediation endpoint payload must match scripts/platform_diagnostics.py --remediation output")
    if payload.get("plan") != "platform_diagnostics_remediation":
        raise AssertionError("remediation endpoint must return plan=platform_diagnostics_remediation")
    if payload.get("remediation_count") != len(payload.get("remediation", [])):
        raise AssertionError("remediation_count must match remediation length")
    for item in payload.get("remediation", []):
        if item.get("safe_to_automate") is not False:
            raise AssertionError("remediation actions must require operator control")
        if item.get("destructive") is not False:
            raise AssertionError("remediation endpoint must not emit destructive actions")
    if payload.get("destructive_action_executed") is not False:
        raise AssertionError("remediation endpoint must not execute destructive actions")
    if payload.get("migration_executed") is not False:
        raise AssertionError("remediation endpoint must not run migrations")
    if payload.get("downgrade_executed") is not False:
        raise AssertionError("remediation endpoint must not run downgrades")

    print(json.dumps({"passed": True, "checked": ["platform-diagnostics-remediation"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
