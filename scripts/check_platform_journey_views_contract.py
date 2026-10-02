#!/usr/bin/env python3
"""Fast structural contract for platform journey lightweight views."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "apps" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.services.platform_journey_views import (  # noqa: E402
    build_platform_journey_actions_from_journey,
    build_platform_journey_steps_from_journey,
    build_platform_journey_summary_from_journey,
)


def sample_journey() -> dict[str, Any]:
    actions = [
        {
            "issue_code": "capability_degraded:rag",
            "severity": "degraded",
            "action": "restore_optional_capability:rag",
            "safe_to_automate": False,
            "destructive": False,
            "verification_command": "python scripts/platform_diagnostics.py --summary",
        }
    ]
    return {
        "plan": "platform_product_journey",
        "journey_schema_version": "1",
        "timestamp_utc": "20260626T000000Z",
        "platform": {"name": "Industrial AI Platform", "version": "v1.3.1", "release_stage": "PRE-PRODUCTION"},
        "journey_status": "complete_with_optional_degradation",
        "journey_complete": True,
        "safe_to_run_without_ai": True,
        "ai_services_blocking": False,
        "blocking_issue_count": 0,
        "degraded_capabilities": ["rag", "ai_assistants", "vector_search"],
        "runtime_profiles": {
            "core": {"ready": True, "blocking": True},
            "document_management": {"ready": True, "blocking": True},
            "ai_services": {"ready": False, "blocking": False},
        },
        "steps": [
            {"sequence": 1, "name": "platform_identity", "status": "ready", "blocking": True, "description": "", "evidence_keys": ["platform"], "required_for": ["core"], "optional_for": [], "next_step": "lifecycle_readiness"},
            {"sequence": 2, "name": "lifecycle_readiness", "status": "ready", "blocking": True, "description": "", "evidence_keys": ["migrations"], "required_for": ["core"], "optional_for": [], "next_step": "core_runtime"},
            {"sequence": 3, "name": "core_runtime", "status": "ready", "blocking": True, "description": "", "evidence_keys": ["runtime_profiles.core"], "required_for": ["document_management"], "optional_for": [], "next_step": "document_management_runtime"},
            {"sequence": 4, "name": "document_management_runtime", "status": "ready", "blocking": True, "description": "", "evidence_keys": ["runtime_profiles.document_management"], "required_for": ["document_management"], "optional_for": [], "next_step": "optional_ai_services"},
            {"sequence": 5, "name": "optional_ai_services", "status": "degraded", "blocking": False, "description": "", "evidence_keys": ["runtime_profiles.ai_services"], "required_for": [], "optional_for": ["rag"], "next_step": "diagnostics_evidence"},
            {"sequence": 6, "name": "diagnostics_evidence", "status": "ready", "blocking": False, "description": "", "evidence_keys": ["summary"], "required_for": [], "optional_for": [], "next_step": "operator_handoff"},
            {"sequence": 7, "name": "operator_handoff", "status": "ready", "blocking": False, "description": "", "evidence_keys": ["issues"], "required_for": [], "optional_for": [], "next_step": None},
        ],
        "operator_next_actions": actions,
        "destructive_action_executed": False,
        "migration_executed": False,
        "downgrade_executed": False,
    }


def require_keys(payload: dict[str, Any], keys: set[str], context: str) -> None:
    missing = sorted(keys - set(payload))
    if missing:
        raise AssertionError(f"{context} missing keys: {missing}")


def main() -> int:
    journey = sample_journey()

    summary = build_platform_journey_summary_from_journey(journey)
    require_keys(
        summary,
        {
            "ai_services_blocking",
            "blocking_issue_count",
            "degraded_capabilities",
            "destructive_action_executed",
            "downgrade_executed",
            "journey_complete",
            "journey_status",
            "migration_executed",
            "operator_next_action_count",
            "plan",
            "platform",
            "safe_to_run_without_ai",
            "step_count",
        },
        "journey_summary_view",
    )
    if summary["plan"] != "platform_product_journey_summary":
        raise AssertionError("unexpected summary view plan")
    if summary["safe_to_run_without_ai"] is not True:
        raise AssertionError("summary view must preserve no-AI readiness")
    if summary["ai_services_blocking"] is not False:
        raise AssertionError("summary view must preserve AI non-blocking contract")
    if summary["step_count"] != 7:
        raise AssertionError("summary view must expose journey step count")

    steps = build_platform_journey_steps_from_journey(journey)
    require_keys(
        steps,
        {"destructive_action_executed", "downgrade_executed", "journey_complete", "journey_status", "migration_executed", "plan", "steps"},
        "journey_steps_view",
    )
    if steps["plan"] != "platform_product_journey_steps":
        raise AssertionError("unexpected steps view plan")
    if [step["sequence"] for step in steps["steps"]] != list(range(1, 8)):
        raise AssertionError("steps view must preserve ordered sequence")

    actions = build_platform_journey_actions_from_journey(journey)
    require_keys(
        actions,
        {"action_count", "actions", "blocking_issue_count", "destructive_action_executed", "downgrade_executed", "journey_status", "migration_executed", "plan"},
        "journey_actions_view",
    )
    if actions["plan"] != "platform_product_journey_actions":
        raise AssertionError("unexpected actions view plan")
    if actions["action_count"] != len(actions["actions"]):
        raise AssertionError("actions view must expose deterministic action count")
    if any(action.get("destructive") for action in actions["actions"]):
        raise AssertionError("actions view must not expose destructive remediation")

    for payload in (summary, steps, actions):
        if payload.get("destructive_action_executed") is not False:
            raise AssertionError("view must not report destructive actions")
        if payload.get("migration_executed") is not False:
            raise AssertionError("view must not report migrations")
        if payload.get("downgrade_executed") is not False:
            raise AssertionError("view must not report downgrades")

    print(json.dumps({"passed": True, "checked": ["platform-journey-views"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
