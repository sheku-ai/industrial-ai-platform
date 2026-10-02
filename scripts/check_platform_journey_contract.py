#!/usr/bin/env python3
"""Fast structural contract for the platform product journey."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "platform_journey.py"


REQUIRED_JOURNEY_KEYS = {
    "ai_services_blocking",
    "blocking_issue_count",
    "degraded_capabilities",
    "destructive_action_executed",
    "downgrade_executed",
    "evidence",
    "journey_complete",
    "journey_schema_version",
    "journey_status",
    "migration_executed",
    "operator_next_actions",
    "plan",
    "platform",
    "runtime_profiles",
    "safe_to_run_without_ai",
    "steps",
    "timestamp_utc",
}

REQUIRED_STEP_KEYS = {
    "blocking",
    "description",
    "evidence_keys",
    "name",
    "next_step",
    "optional_for",
    "required_for",
    "sequence",
    "status",
}

EXPECTED_STEP_ORDER = [
    "platform_identity",
    "lifecycle_readiness",
    "core_runtime",
    "document_management_runtime",
    "optional_ai_services",
    "diagnostics_evidence",
    "operator_handoff",
]


def run_command(*args: str) -> dict[str, Any]:
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


def require_keys(payload: dict[str, Any], keys: set[str], context: str) -> None:
    missing = sorted(keys - set(payload))
    if missing:
        raise AssertionError(f"{context} missing keys: {missing}")


def assert_journey_contract(payload: dict[str, Any]) -> None:
    require_keys(payload, REQUIRED_JOURNEY_KEYS, "journey_payload")
    if payload["plan"] != "platform_product_journey":
        raise AssertionError("journey payload must return plan=platform_product_journey")
    if payload["journey_schema_version"] != "1":
        raise AssertionError("journey schema version must be 1")
    if payload["ai_services_blocking"] is not False:
        raise AssertionError("AI services must remain non-blocking")
    if payload["destructive_action_executed"] is not False:
        raise AssertionError("journey must not execute destructive actions")
    if payload["migration_executed"] is not False:
        raise AssertionError("journey must not execute migrations")
    if payload["downgrade_executed"] is not False:
        raise AssertionError("journey must not execute downgrades")
    if payload["journey_status"] not in {"complete", "complete_with_optional_degradation", "blocked"}:
        raise AssertionError("journey status is outside the allowed contract")
    if not isinstance(payload["steps"], list) or len(payload["steps"]) != len(EXPECTED_STEP_ORDER):
        raise AssertionError("journey must expose the expected ordered steps")

    step_names = []
    for index, step in enumerate(payload["steps"], start=1):
        require_keys(step, REQUIRED_STEP_KEYS, f"journey_step[{index}]")
        if step["sequence"] != index:
            raise AssertionError("journey step sequence must be contiguous")
        if step["status"] not in {"ready", "degraded", "blocked"}:
            raise AssertionError("journey step status is outside the allowed contract")
        if not isinstance(step["blocking"], bool):
            raise AssertionError("journey step blocking must be boolean")
        if not isinstance(step["evidence_keys"], list) or not step["evidence_keys"]:
            raise AssertionError("journey step must expose evidence keys")
        step_names.append(step["name"])

    if step_names != EXPECTED_STEP_ORDER:
        raise AssertionError(f"unexpected journey step order: {step_names}")

    evidence = payload["evidence"]
    require_keys(evidence, {"catalog", "issues", "remediation", "source", "summary"}, "journey_evidence")
    if evidence["source"] != "live_platform_diagnostics":
        raise AssertionError("journey evidence must be based on live diagnostics")
    if evidence["summary"].get("plan") != "platform_diagnostics_summary":
        raise AssertionError("journey evidence summary must reuse diagnostics summary contract")
    if evidence["issues"].get("plan") != "platform_diagnostics_issues":
        raise AssertionError("journey evidence issues must reuse diagnostics issues contract")
    if evidence["remediation"].get("plan") != "platform_diagnostics_remediation":
        raise AssertionError("journey evidence remediation must reuse diagnostics remediation contract")
    if evidence["catalog"].get("plan") != "platform_diagnostics_catalog":
        raise AssertionError("journey evidence catalog must reuse diagnostics catalog contract")


def main() -> int:
    payload = run_command()
    assert_journey_contract(payload)

    with tempfile.TemporaryDirectory(prefix="platform-journey-evidence-") as tmpdir:
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
            "journey_evidence_write_result",
        )
        if result["plan"] != "platform_product_journey_evidence_written":
            raise AssertionError("journey evidence write result must return plan=platform_product_journey_evidence_written")
        if result["destructive_action_executed"] is not False:
            raise AssertionError("journey evidence generation must not execute destructive actions")
        if result["migration_executed"] is not False:
            raise AssertionError("journey evidence generation must not run migrations")
        if result["downgrade_executed"] is not False:
            raise AssertionError("journey evidence generation must not run downgrades")

        evidence_path = Path(result["evidence_path"])
        if not evidence_path.exists():
            raise AssertionError(f"journey evidence file was not created: {evidence_path}")
        if evidence_path.parent != Path(tmpdir):
            raise AssertionError("journey evidence output directory was not honored")
        if not evidence_path.name.startswith("journey_") or evidence_path.suffix != ".json":
            raise AssertionError("journey evidence file name must be journey_<timestamp>.json")

        evidence_payload = json.loads(evidence_path.read_text(encoding="utf-8"))
        assert_journey_contract(evidence_payload)
        if evidence_payload["timestamp_utc"] != result["timestamp_utc"]:
            raise AssertionError("journey evidence payload timestamp must match write result")

    print(json.dumps({"passed": True, "checked": ["platform-product-journey"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
