#!/usr/bin/env python3
"""Manual smoke contract for metadata-only Assistant Runtime foundation."""

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
from app.services.assistant_runtime import build_assistant_runtime  # noqa: E402
from app.services.runtime_persistence_runtime import read_runtime_persistence  # noqa: E402


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

    assistant_key = f"assistant-runtime-smoke-{uuid.uuid4().hex[:12]}"
    db = SessionLocal()
    try:
        assistant_runtime = build_assistant_runtime(
            db,
            organization_id=None,
            ownership_scope="global",
            data_origin="validation",
            assistant_name="Assistant Runtime Smoke",
            assistant_key=assistant_key,
            assistant_version="1.0",
            assistant_type="platform_assistant",
            description="Metadata-only assistant runtime smoke.",
            default_search_mode="enterprise_search",
            allowed_runtime_domains=["enterprise_search", "hybrid_search_runtime", "semantic_search_runtime", "workflow_runtime"],
            requested_by="assistant-runtime-e2e-smoke",
            conversation_reference=f"conversation:{assistant_key}",
            requested_query="metadata-only assistant planning",
        )
        persistence_execution_id = (assistant_runtime.get("runtime_persistence") or {}).get("execution_id")
        readback = read_runtime_persistence(db, execution_id=persistence_execution_id) if persistence_execution_id else {}
    finally:
        db.close()

    observed = {
        "assistant_runtime_prepared": assistant_runtime.get("assistant_runtime_prepared") is True,
        "assistant_definition_created": assistant_runtime.get("assistant_definition_created") is True,
        "assistant_session_created": assistant_runtime.get("assistant_session_created") is True,
        "assistant_run_created": assistant_runtime.get("assistant_run_created") is True,
        "assistant_execution_planned": assistant_runtime.get("assistant_execution_planned") is True,
        "assistant_executed": bool(assistant_runtime.get("assistant_executed")),
        "llm_used": bool(assistant_runtime.get("llm_used")),
        "answer_generated": bool(assistant_runtime.get("answer_generated")),
        "tool_called": bool(assistant_runtime.get("tool_called")),
        "workflow_executed": bool(assistant_runtime.get("workflow_executed")),
        "external_action_called": bool(assistant_runtime.get("external_action_called")),
        "autonomous_execution": bool(assistant_runtime.get("autonomous_execution")),
        "enterprise_search_used": bool(assistant_runtime.get("enterprise_search_used")),
        "hybrid_search_used": bool(assistant_runtime.get("hybrid_search_used")),
        "postgresql_source_of_truth": assistant_runtime.get("postgresql_source_of_truth") is True,
        "runtime_persistence": (assistant_runtime.get("runtime_persistence") or {}).get("persistence_completed") is True
        and readback.get("persistence_status") == "persisted"
        and (readback.get("domains") or {}).get("assistant_runtime", 0) >= 1,
    }
    expectations = {
        "assistant_runtime_prepared": observed["assistant_runtime_prepared"] is True,
        "assistant_definition_created": observed["assistant_definition_created"] is True,
        "assistant_session_created": observed["assistant_session_created"] is True,
        "assistant_run_created": observed["assistant_run_created"] is True,
        "assistant_execution_planned": observed["assistant_execution_planned"] is True,
        "assistant_executed": observed["assistant_executed"] is False,
        "llm_used": observed["llm_used"] is False,
        "answer_generated": observed["answer_generated"] is False,
        "tool_called": observed["tool_called"] is False,
        "workflow_executed": observed["workflow_executed"] is False,
        "external_action_called": observed["external_action_called"] is False,
        "autonomous_execution": observed["autonomous_execution"] is False,
        "enterprise_search_used": observed["enterprise_search_used"] is False,
        "hybrid_search_used": observed["hybrid_search_used"] is False,
        "postgresql_source_of_truth": observed["postgresql_source_of_truth"] is True,
        "runtime_persistence": observed["runtime_persistence"] is True,
    }
    expected_values = {
        "assistant_executed": False,
        "llm_used": False,
        "answer_generated": False,
        "tool_called": False,
        "workflow_executed": False,
        "external_action_called": False,
        "autonomous_execution": False,
        "enterprise_search_used": False,
        "hybrid_search_used": False,
    }
    for key, value in expectations.items():
        expected = expected_values.get(key, True)
        _expect(bool(value), failures, f"{key} must be {str(expected).lower()}")
    payload = {**observed, "passed": all(expectations.values()) and not failures, "failures": failures}
    print(json.dumps(payload, sort_keys=True))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
