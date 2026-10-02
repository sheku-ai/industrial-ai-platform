#!/usr/bin/env python3
"""Fast contract for the operational diagnostics issues API endpoint."""

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


def run_cli_issues() -> dict:
    completed = subprocess.run(
        [sys.executable, str(CLI), "--issues"],
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
            f"expected CLI issues JSON rc={completed.returncode} stdout={completed.stdout!r} stderr={completed.stderr!r}"
        ) from exc
    if completed.returncode != 0:
        raise AssertionError(f"CLI diagnostics issues failed rc={completed.returncode} payload={payload}")
    return payload


def main() -> int:
    app = FastAPI()
    app.include_router(diagnostics_router, prefix="/api")
    client = TestClient(app)

    response = client.get("/api/platform/diagnostics/issues")
    if response.status_code != 200:
        raise AssertionError(f"expected HTTP 200, got {response.status_code}: {response.text}")

    payload = response.json()
    if payload != run_cli_issues():
        raise AssertionError("issues endpoint payload must match scripts/platform_diagnostics.py --issues output")
    if payload.get("plan") != "platform_diagnostics_issues":
        raise AssertionError("issues endpoint must return plan=platform_diagnostics_issues")
    if payload.get("issue_count") != len(payload.get("issues", [])):
        raise AssertionError("issue_count must match issues length")
    for issue in payload.get("issues", []):
        if issue.get("severity") not in {"critical", "degraded"}:
            raise AssertionError("issue severity must be critical or degraded")
    if payload.get("destructive_action_executed") is not False:
        raise AssertionError("issues endpoint must not execute destructive actions")
    if payload.get("migration_executed") is not False:
        raise AssertionError("issues endpoint must not run migrations")
    if payload.get("downgrade_executed") is not False:
        raise AssertionError("issues endpoint must not run downgrades")

    print(json.dumps({"passed": True, "checked": ["platform-diagnostics-issues"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
