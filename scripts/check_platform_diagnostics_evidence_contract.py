#!/usr/bin/env python3
"""Fast structural contract for diagnostics evidence snapshots."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "platform_diagnostics.py"
SECRET_KEY_PATTERNS = ("SECRET", "TOKEN", "PASSWORD", "API_KEY", "ACCESS_KEY")


def run_command(*args: str) -> dict:
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), *args],
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
        raise AssertionError(f"command failed rc={completed.returncode} payload={payload}")
    return payload


def require_keys(payload: dict, keys: set[str], context: str) -> None:
    missing = sorted(keys - set(payload))
    if missing:
        raise AssertionError(f"{context} missing keys: {missing}")


def assert_no_secret_values(payload: Any, path: str = "") -> None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            key_path = f"{path}.{key}" if path else str(key)
            key_upper = str(key).upper()
            if isinstance(value, str) and any(pattern in key_upper for pattern in SECRET_KEY_PATTERNS):
                if value and value != "<redacted>":
                    raise AssertionError(f"secret-like field is not redacted: {key_path}")
            assert_no_secret_values(value, key_path)
    elif isinstance(payload, list):
        for index, item in enumerate(payload):
            assert_no_secret_values(item, f"{path}[{index}]")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="platform-diagnostics-evidence-") as tmpdir:
        result = run_command("--write-evidence", "--output", tmpdir)
        require_keys(
            result,
            {
                "destructive_action_executed",
                "downgrade_executed",
                "evidence_path",
                "migration_executed",
                "plan",
                "timestamp_utc",
            },
            "evidence_write_result",
        )
        if result["plan"] != "platform_diagnostics_evidence_written":
            raise AssertionError("evidence write result must return plan=platform_diagnostics_evidence_written")
        if result["destructive_action_executed"] is not False:
            raise AssertionError("evidence generation must not execute destructive actions")
        if result["migration_executed"] is not False:
            raise AssertionError("evidence generation must not run migrations")
        if result["downgrade_executed"] is not False:
            raise AssertionError("evidence generation must not run downgrades")

        evidence_path = Path(result["evidence_path"])
        if not evidence_path.exists():
            raise AssertionError(f"evidence file was not created: {evidence_path}")
        if evidence_path.parent != Path(tmpdir):
            raise AssertionError("evidence output directory was not honored")
        if not evidence_path.name.startswith("diagnostics_") or evidence_path.suffix != ".json":
            raise AssertionError("evidence file name must be diagnostics_<timestamp>.json")

        payload = json.loads(evidence_path.read_text(encoding="utf-8"))
        require_keys(
            payload,
            {
                "catalog",
                "critical_services",
                "degraded_capabilities",
                "diagnostics",
                "environment_summary",
                "evidence_schema_version",
                "generated_by",
                "issues",
                "lifecycle",
                "optional_services",
                "platform",
                "plan",
                "remediation",
                "runtime_profiles",
                "summary",
                "timestamp_utc",
            },
            "evidence_payload",
        )
        if payload["plan"] != "platform_diagnostics_evidence":
            raise AssertionError("evidence payload must return plan=platform_diagnostics_evidence")
        if payload["timestamp_utc"] != result["timestamp_utc"]:
            raise AssertionError("evidence payload timestamp must match write result")
        if payload["diagnostics"].get("plan") != "platform_diagnostics":
            raise AssertionError("evidence diagnostics section must contain full diagnostics")
        if payload["summary"].get("plan") != "platform_diagnostics_summary":
            raise AssertionError("evidence summary section must contain diagnostics summary")
        if payload["issues"].get("plan") != "platform_diagnostics_issues":
            raise AssertionError("evidence issues section must contain diagnostics issues")
        if payload["remediation"].get("plan") != "platform_diagnostics_remediation":
            raise AssertionError("evidence remediation section must contain diagnostics remediation")
        if payload["catalog"].get("plan") != "platform_diagnostics_catalog":
            raise AssertionError("evidence catalog section must contain diagnostics catalog")
        if payload.get("destructive_action_executed") is not False:
            raise AssertionError("evidence payload must not report destructive actions")
        if payload.get("migration_executed") is not False:
            raise AssertionError("evidence payload must not report migrations")
        if payload.get("downgrade_executed") is not False:
            raise AssertionError("evidence payload must not report downgrades")
        assert_no_secret_values(payload)

    print(json.dumps({"passed": True, "checked": ["platform-diagnostics-evidence"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())