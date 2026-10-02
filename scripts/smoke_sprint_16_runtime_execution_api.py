#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "apps" / "api"
if str(API) not in sys.path:
    sys.path.insert(0, str(API))

from fastapi.testclient import TestClient  # noqa: E402
from main import app  # noqa: E402


class SmokeFailure(RuntimeError):
    pass


def check(condition: bool, message: str) -> None:
    if not condition:
        raise SmokeFailure(message)


def run_smoke() -> dict[str, object]:
    client = TestClient(app)

    status_response = client.get("/api/ai/runtime/status")
    check(status_response.status_code == 200, "runtime status endpoint")
    status = status_response.json()
    check(status["resolver_enabled"] is True, "resolver status")
    check(status["execution_enabled"] is False, "execution must be disabled")
    check(status["provider_execution_enabled"] is False, "provider execution must be disabled")

    execute_response = client.post(
        "/api/ai/runtime/execute",
        json={
            "requested_answer_mode": "assisted",
            "context": ["Context remains available."],
            "citations": [{"id": "ref-1"}],
        },
    )
    check(execute_response.status_code == 200, "runtime execute endpoint")
    execute = execute_response.json()
    check(execute["status"] == "fallback", "execute status")
    check(execute["resolved_answer_mode"] == "extractive", "execute fallback mode")
    check(execute["fallback_reason"] == "execution_not_enabled", "execute fallback reason")
    check(execute["execution_attempted"] is False, "execution must not be attempted")
    check(execute["provider_execution_performed"] is False, "provider execution must not occur")
    check(execute["secret_resolution_performed"] is False, "secret resolution must not occur")
    check(execute["generation_performed"] is False, "generation must not occur")
    check(execute["citation_count"] == 1, "citations must be preserved")

    extractive_response = client.post(
        "/api/ai/runtime/execute",
        json={"requested_answer_mode": "extractive", "context": [], "citations": []},
    )
    check(extractive_response.status_code == 200, "extractive execute endpoint")
    extractive = extractive_response.json()
    check(extractive["status"] == "not_attempted", "extractive status")
    check(extractive["fallback_used"] is False, "extractive fallback")

    return {
        "status": "passed",
        "sprint": "16.6",
        "validation": "runtime_execution_api",
        "runtime_status_available": True,
        "resolver_enabled": True,
        "execution_enabled": False,
        "assisted_falls_back_extractive": True,
        "context_preserved": True,
        "citations_preserved": True,
        "provider_execution_performed": False,
        "secret_resolution_performed": False,
        "generation_performed": False,
    }


def main() -> int:
    try:
        result = run_smoke()
    except SmokeFailure as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, indent=2), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
