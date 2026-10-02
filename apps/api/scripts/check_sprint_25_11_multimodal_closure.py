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
DEFAULT_EVIDENCE_PATH = Path(
    os.getenv(
        "SPRINT_25_11_EVIDENCE_PATH",
        "/app/runtime/evidence/multimodal-hardening/sprint-25.11-closure.json",
    )
)

CHECKS = (
    (
        "dependency_injection",
        "check_visual_chunk_dependency_injection_contract.py",
    ),
    (
        "postgres_concurrency_and_upsert",
        "check_visual_chunk_concurrency_e2e.py",
    ),
    (
        "multimodal_observability",
        "check_multimodal_observability_contract.py",
    ),
    (
        "processing_revision_selection",
        "check_processing_revision_selection_e2e.py",
    ),
    (
        "multimodal_full_chain",
        "check_worker_multimodal_full_chain_contract_e2e.py",
    ),
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


def _run_check(name: str, script_name: str) -> dict[str, Any]:
    script_path = SCRIPT_DIR / script_name
    started_at = perf_counter()
    if not script_path.is_file():
        return {
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
    results = [_run_check(name, script_name) for name, script_name in CHECKS]
    failed_checks = [result["name"] for result in results if not result["passed"]]
    passed = not failed_checks
    evidence = {
        "schema": "industrial-ai-platform/sprint-closure-evidence/v1",
        "sprint": "25.11",
        "scope": "multimodal-production-hardening",
        "generated_at": datetime.now(UTC).isoformat(),
        "passed": passed,
        "check_count": len(results),
        "passed_check_count": sum(1 for result in results if result["passed"]),
        "failed_check_count": len(failed_checks),
        "failed_checks": failed_checks,
        "duration_ms": max(0, round((perf_counter() - started_at) * 1000)),
        "checks": results,
    }

    evidence_path = DEFAULT_EVIDENCE_PATH
    try:
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        evidence_path.write_text(
            json.dumps(evidence, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        evidence["evidence_path"] = str(evidence_path)
    except OSError as error:
        evidence["evidence_path"] = None
        evidence["evidence_write_error"] = f"{type(error).__name__}: {error}"
        passed = False
        evidence["passed"] = False

    print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
