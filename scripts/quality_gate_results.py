from __future__ import annotations

from collections.abc import Mapping
from typing import Any

REQUIRED_STAGE_BLOCKING = {
    "backend_tests": True,
    "security_tests": True,
    "migrations": True,
    "ruff": True,
    "ruff_expanded": False,
    "ruff_format": True,
    "ruff_format_expanded": False,
    "mypy": True,
    "mypy_expanded": False,
    "bandit": True,
    "bandit_expanded": False,
    "typescript": True,
    "eslint": True,
    "portal_build": True,
    "contracts": True,
    "portal_editorial_audit": False,
    "npm_audit_production": True,
    "npm_audit_all": False,
    "python_audit": False,
    "production_images": True,
    "cleanup_status": True,
}


class QualityGateResultError(ValueError):
    pass


def aggregate_results(stages: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    missing = [name for name in REQUIRED_STAGE_BLOCKING if name not in stages]
    if missing:
        return {
            "overall_status": "failed",
            "overall_exit_code": 1,
            "blocking_failures": missing,
            "missing_stages": missing,
        }

    blocking_failures: list[str] = []
    for name, expected_blocking in REQUIRED_STAGE_BLOCKING.items():
        stage = stages[name]
        actual_blocking = stage.get("blocking")
        if actual_blocking is not expected_blocking:
            raise QualityGateResultError(
                f"stage {name} blocking flag mismatch: expected {expected_blocking}, got {actual_blocking}"
            )
        if expected_blocking and (stage.get("status") != "passed" or int(stage.get("exit_code", 1)) != 0):
            blocking_failures.append(name)

    passed = not blocking_failures
    return {
        "overall_status": "passed" if passed else "failed",
        "overall_exit_code": 0 if passed else 1,
        "blocking_failures": blocking_failures,
        "missing_stages": [],
    }
