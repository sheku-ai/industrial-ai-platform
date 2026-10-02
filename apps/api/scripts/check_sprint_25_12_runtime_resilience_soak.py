from __future__ import annotations

import json
import os
import subprocess
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_EVIDENCE_PATH = Path(
    os.getenv(
        "SPRINT_25_12_SOAK_EVIDENCE_PATH",
        "/app/runtime/evidence/resource-optimization/sprint-25.12-runtime-soak.json",
    )
)
CHECKS = (
    ("capacity_backpressure", "check_runtime_capacity_backpressure_contract.py"),
    ("duplicate_work_cache", "check_duplicate_work_cache_contract.py"),
    ("circuit_breaker", "check_runtime_circuit_breaker_contract.py"),
    ("organization_quota", "check_runtime_organization_quota_contract.py"),
    ("workload_policy", "check_runtime_workload_policy_contract.py"),
    ("daemon_queue_wiring", "check_runtime_daemon_queue_wiring_contract.py"),
)


def _iterations() -> int:
    raw = os.getenv("SPRINT_25_12_SOAK_ITERATIONS", "5")
    try:
        value = int(raw)
    except ValueError as exc:
        raise SystemExit("SPRINT_25_12_SOAK_ITERATIONS must be an integer") from exc
    if value < 1 or value > 50:
        raise SystemExit("SPRINT_25_12_SOAK_ITERATIONS must be between 1 and 50")
    return value


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


def _run_check(iteration: int, name: str, script_name: str) -> dict[str, Any]:
    script_path = SCRIPT_DIR / script_name
    started_at = perf_counter()
    if not script_path.is_file():
        return {
            "iteration": iteration,
            "name": name,
            "script": script_name,
            "passed": False,
            "exit_code": None,
            "duration_ms": 0,
            "error": "script_not_found",
            "result": None,
        }
    completed = subprocess.run(
        [sys.executable, str(script_path)],
        cwd=str(SCRIPT_DIR.parent),
        env={**os.environ, "PYTHONPATH": os.environ.get("PYTHONPATH", "/app")},
        capture_output=True,
        text=True,
        check=False,
    )
    duration_ms = max(0, round((perf_counter() - started_at) * 1000))
    parsed = _extract_json(completed.stdout)
    passed = completed.returncode == 0 and isinstance(parsed, dict) and parsed.get("passed") is True
    return {
        "iteration": iteration,
        "name": name,
        "script": script_name,
        "passed": passed,
        "exit_code": completed.returncode,
        "duration_ms": duration_ms,
        "error": None if passed else "check_failed",
        "result": parsed,
        "stdout": completed.stdout.strip() if not passed else None,
        "stderr": completed.stderr.strip() if completed.stderr.strip() else None,
    }


def main() -> int:
    started_at = perf_counter()
    iteration_count = _iterations()
    results = [
        _run_check(iteration, name, script_name)
        for iteration in range(1, iteration_count + 1)
        for name, script_name in CHECKS
    ]
    failures = [result for result in results if not result["passed"]]
    durations_by_check: dict[str, list[int]] = {}
    for result in results:
        durations_by_check.setdefault(result["name"], []).append(result["duration_ms"])
    summary = {
        name: {
            "runs": len(durations),
            "min_duration_ms": min(durations),
            "max_duration_ms": max(durations),
            "average_duration_ms": round(sum(durations) / len(durations), 2),
            "failure_count": sum(1 for result in failures if result["name"] == name),
        }
        for name, durations in durations_by_check.items()
    }
    failure_counts = Counter(result["name"] for result in failures)
    passed = not failures
    evidence = {
        "schema": "industrial-ai-platform/runtime-soak-evidence/v1",
        "sprint": "25.12",
        "scope": "runtime-resource-optimization-and-resilience",
        "generated_at": datetime.now(UTC).isoformat(),
        "passed": passed,
        "iteration_count": iteration_count,
        "check_count_per_iteration": len(CHECKS),
        "total_run_count": len(results),
        "passed_run_count": sum(1 for result in results if result["passed"]),
        "failed_run_count": len(failures),
        "failure_counts_by_check": dict(sorted(failure_counts.items())),
        "duration_ms": max(0, round((perf_counter() - started_at) * 1000)),
        "summary_by_check": summary,
        "runs": results,
    }
    try:
        DEFAULT_EVIDENCE_PATH.parent.mkdir(parents=True, exist_ok=True)
        DEFAULT_EVIDENCE_PATH.write_text(
            json.dumps(evidence, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        evidence["evidence_path"] = str(DEFAULT_EVIDENCE_PATH)
    except OSError as error:
        evidence["evidence_path"] = None
        evidence["evidence_write_error"] = f"{type(error).__name__}: {error}"
        evidence["passed"] = False
        passed = False
    print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
