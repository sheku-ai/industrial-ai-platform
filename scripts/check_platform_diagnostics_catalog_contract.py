#!/usr/bin/env python3
"""Fast contract for the operational diagnostics catalog API endpoint."""

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


def run_cli_catalog() -> dict:
    completed = subprocess.run(
        [sys.executable, str(CLI), "--catalog"],
        cwd=str(ROOT),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    payload = json.loads(completed.stdout)
    if completed.returncode != 0:
        raise AssertionError(f"CLI diagnostics catalog failed rc={completed.returncode} payload={payload}")
    return payload


def main() -> int:
    app = FastAPI()
    app.include_router(diagnostics_router, prefix="/api")
    client = TestClient(app)

    response = client.get("/api/platform/diagnostics/catalog")
    if response.status_code != 200:
        raise AssertionError(f"expected HTTP 200, got {response.status_code}: {response.text}")

    payload = response.json()
    if payload != run_cli_catalog():
        raise AssertionError("catalog endpoint payload must match scripts/platform_diagnostics.py --catalog output")
    if payload.get("plan") != "platform_diagnostics_catalog":
        raise AssertionError("catalog endpoint must return plan=platform_diagnostics_catalog")
    for key in ("critical_services", "optional_services", "runtime_profiles", "degraded_capabilities"):
        if key not in payload:
            raise AssertionError(f"catalog missing {key}")
    if payload.get("destructive_action_executed") is not False:
        raise AssertionError("catalog endpoint must not execute destructive actions")
    if payload.get("migration_executed") is not False:
        raise AssertionError("catalog endpoint must not run migrations")
    if payload.get("downgrade_executed") is not False:
        raise AssertionError("catalog endpoint must not run downgrades")

    print(json.dumps({"passed": True, "checked": ["platform-diagnostics-catalog"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
