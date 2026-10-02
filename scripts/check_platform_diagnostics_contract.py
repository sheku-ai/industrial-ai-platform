#!/usr/bin/env python3
"""Fast structural contract for scripts/platform_diagnostics.py."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "platform_diagnostics.py"


def run_diagnostics() -> dict:
    completed = subprocess.run(
        [sys.executable, str(SCRIPT)],
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
            f"expected JSON stdout rc={completed.returncode} stdout={completed.stdout!r} stderr={completed.stderr!r}"
        ) from exc

    if completed.returncode != 0:
        raise AssertionError(f"diagnostics failed rc={completed.returncode} payload={payload}")
    return payload


def require_keys(payload: dict, keys: set[str], context: str) -> None:
    missing = sorted(keys - set(payload))
    if missing:
        raise AssertionError(f"{context} missing keys: {missing}")


def main() -> int:
    payload = run_diagnostics()
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
        "diagnostics",
    )

    if payload.get("plan") != "platform_diagnostics":
        raise AssertionError("diagnostics must return plan=platform_diagnostics")
    if payload["overall_status"] not in {"ready", "degraded", "critical"}:
        raise AssertionError("overall_status must be ready, degraded or critical")
    if not isinstance(payload["degraded_capabilities"], list):
        raise AssertionError("degraded_capabilities must be a list")

    require_keys(payload["critical_services"], {"alembic", "object_storage", "postgresql", "secret_store"}, "critical_services")
    require_keys(payload["optional_services"], {"ai_provider", "vector_store"}, "optional_services")
    require_keys(payload["runtime_profiles"], {"ai_services", "core", "document_management"}, "runtime_profiles")

    for group_name in ("critical_services", "optional_services", "runtime_profiles"):
        for name, service in payload[group_name].items():
            if not isinstance(service.get("ready"), bool):
                raise AssertionError(f"{group_name}.{name}.ready must be boolean")

    if payload.get("destructive_action_executed") is not False:
        raise AssertionError("diagnostics must not execute destructive actions")
    if payload.get("migration_executed") is not False:
        raise AssertionError("diagnostics must not run migrations")
    if payload.get("downgrade_executed") is not False:
        raise AssertionError("diagnostics must not run downgrades")

    print(json.dumps({"passed": True, "checked": ["platform-diagnostics"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
