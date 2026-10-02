#!/usr/bin/env python3
"""Manual smoke contract for metadata-only Workflow Runtime foundation."""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "apps" / "api"
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

from app.db.session import SessionLocal  # noqa: E402
from app.services.runtime_persistence_runtime import read_runtime_persistence  # noqa: E402
from app.services.workflow_runtime import build_workflow_runtime  # noqa: E402


def _expect(condition: bool, failures: list[str], message: str) -> bool:
    if condition:
        return True
    failures.append(message)
    return False


def main() -> int:
    failures: list[str] = []
    if SessionLocal is None:
        payload = {"passed": False, "failures": ["database url is not configured"]}
        print(json.dumps(payload, sort_keys=True))
        return 1

    workflow_key = f"workflow-runtime-smoke-{uuid.uuid4().hex[:12]}"
    db = SessionLocal()
    try:
        workflow_runtime = build_workflow_runtime(
            db,
            workflow_name="Workflow Runtime Smoke",
            workflow_key=workflow_key,
            workflow_version="1.0",
            workflow_type="platform_runtime",
            description="Metadata-only platform workflow runtime smoke.",
            requested_by="workflow-runtime-e2e-smoke",
            steps=[
                {
                    "step_key": "prepare-knowledge-index",
                    "step_name": "Prepare Knowledge Index Metadata",
                    "step_order": 0,
                    "step_type": "runtime_step",
                    "runtime_domain": "knowledge_index",
                    "runtime_action": "metadata_only",
                },
                {
                    "step_key": "prepare-search-evidence",
                    "step_name": "Prepare Search Runtime Evidence",
                    "step_order": 1,
                    "step_type": "runtime_step",
                    "runtime_domain": "enterprise_search",
                    "runtime_action": "metadata_only",
                },
            ],
        )
        persistence_execution_id = (workflow_runtime.get("runtime_persistence") or {}).get("execution_id")
        readback = read_runtime_persistence(db, execution_id=persistence_execution_id) if persistence_execution_id else {}
    finally:
        db.close()

    observed = {
        "workflow_runtime_prepared": workflow_runtime.get("workflow_runtime_prepared") is True,
        "workflow_definition_created": workflow_runtime.get("workflow_definition_created") is True,
        "workflow_steps_created": workflow_runtime.get("workflow_steps_created") is True,
        "workflow_run_created": workflow_runtime.get("workflow_run_created") is True,
        "workflow_execution_planned": workflow_runtime.get("workflow_execution_planned") is True,
        "workflow_executed": bool(workflow_runtime.get("workflow_executed")),
        "external_action_called": bool(workflow_runtime.get("external_action_called")),
        "ai_used": bool(workflow_runtime.get("ai_used")),
        "llm_used": bool(workflow_runtime.get("llm_used")),
        "assistant_used": bool(workflow_runtime.get("assistant_used")),
        "autonomous_execution": bool(workflow_runtime.get("autonomous_execution")),
        "postgresql_source_of_truth": workflow_runtime.get("postgresql_source_of_truth") is True,
        "runtime_persistence": (workflow_runtime.get("runtime_persistence") or {}).get("persistence_completed") is True
        and readback.get("persistence_status") == "persisted"
        and (readback.get("domains") or {}).get("workflow_runtime", 0) >= 1,
    }
    expectations = {
        "workflow_runtime_prepared": observed["workflow_runtime_prepared"] is True,
        "workflow_definition_created": observed["workflow_definition_created"] is True,
        "workflow_steps_created": observed["workflow_steps_created"] is True,
        "workflow_run_created": observed["workflow_run_created"] is True,
        "workflow_execution_planned": observed["workflow_execution_planned"] is True,
        "workflow_executed": observed["workflow_executed"] is False,
        "external_action_called": observed["external_action_called"] is False,
        "ai_used": observed["ai_used"] is False,
        "llm_used": observed["llm_used"] is False,
        "assistant_used": observed["assistant_used"] is False,
        "autonomous_execution": observed["autonomous_execution"] is False,
        "postgresql_source_of_truth": observed["postgresql_source_of_truth"] is True,
        "runtime_persistence": observed["runtime_persistence"] is True,
    }
    expected_values = {
        "workflow_executed": False,
        "external_action_called": False,
        "ai_used": False,
        "llm_used": False,
        "assistant_used": False,
        "autonomous_execution": False,
    }
    for key, value in expectations.items():
        expected = expected_values.get(key, True)
        _expect(bool(value), failures, f"{key} must be {str(expected).lower()}")
    payload = {**observed, "passed": all(expectations.values()) and not failures, "failures": failures}
    print(json.dumps(payload, sort_keys=True))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
