from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
EVIDENCE_PATH = Path(
    os.getenv(
        "SPRINT_25_12_REGRESSION_EVIDENCE_PATH",
        "/app/runtime/evidence/resource-optimization/sprint-25.12-platform-regression.json",
    )
)
CHECKS = (
    ("api_platform_contract", "check_api_platform_contract.py", {}),
    (
        "runtime_resilience",
        "check_sprint_25_12_runtime_resilience_soak.py",
        {"SPRINT_25_12_SOAK_ITERATIONS": os.getenv("SPRINT_25_12_REGRESSION_SOAK_ITERATIONS", "3")},
    ),
    ("multimodal_platform_chain", "check_sprint_25_11_multimodal_closure.py", {}),
)


def _extract_json(stdout: str) -> dict[str, Any] | None:
    decoder = json.JSONDecoder()
    for index, character in enumerate(stdout):
        if character != "{":
            continue
        try:
            value, end = decoder.raw_decode(stdout[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and not stdout[index + end :].strip():
            return value
    return None


def _run(name: str, script_name: str, extra_env: dict[str, str]) -> dict[str, Any]:
    script_path = SCRIPT_DIR / script_name
    started_at = perf_counter()
    if not script_path.is_file():
        return {
            "name": name,
            "script": script_name,
            "passed": False,
            "duration_ms": 0,
            "error": "script_not_found",
        }
    completed = subprocess.run(
        [sys.executable, str(script_path)],
        cwd=str(SCRIPT_DIR.parent),
        env={
            **os.environ,
            "PYTHONPATH": os.environ.get("PYTHONPATH", "/app"),
            **extra_env,
        },
        capture_output=True,
        text=True,
        check=False,
    )
    duration_ms = max(0, round((perf_counter() - started_at) * 1000))
    parsed = _extract_json(completed.stdout)
    passed = completed.returncode == 0 and isinstance(parsed, dict) and parsed.get("passed") is True
    summary = {
        "name": name,
        "script": script_name,
        "passed": passed,
        "exit_code": completed.returncode,
        "duration_ms": duration_ms,
        "error": None if passed else "check_failed",
    }
    if isinstance(parsed, dict):
        summary["result_summary"] = {
            key: parsed.get(key)
            for key in (
                "passed",
                "check_count",
                "passed_check_count",
                "failed_check_count",
                "iteration_count",
                "total_run_count",
                "passed_run_count",
                "failed_run_count",
                "documented_path_count",
                "evidence_path",
            )
            if key in parsed
        }
    if not passed:
        summary["stdout"] = completed.stdout.strip()
        summary["stderr"] = completed.stderr.strip() or None
    return summary


def main() -> int:
    started_at = perf_counter()
    results = [_run(name, script, env) for name, script, env in CHECKS]
    failed = [result["name"] for result in results if not result["passed"]]
    passed = not failed
    evidence = {
        "schema": "industrial-ai-platform/sprint-closure-evidence/v1",
        "sprint": "25.12",
        "scope": "api-worker-platform-regression",
        "generated_at": datetime.now(UTC).isoformat(),
        "passed": passed,
        "check_count": len(results),
        "passed_check_count": sum(1 for result in results if result["passed"]),
        "failed_check_count": len(failed),
        "failed_checks": failed,
        "duration_ms": max(0, round((perf_counter() - started_at) * 1000)),
        "checks": results,
    }
    try:
        EVIDENCE_PATH.parent.mkdir(parents=True, exist_ok=True)
        EVIDENCE_PATH.write_text(
            json.dumps(evidence, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        evidence["evidence_path"] = str(EVIDENCE_PATH)
    except OSError as error:
        evidence["passed"] = False
        evidence["evidence_path"] = None
        evidence["evidence_write_error"] = f"{type(error).__name__}: {error}"
        passed = False

    print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
