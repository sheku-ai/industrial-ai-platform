#!/usr/bin/env python3
"""Manual smoke contract for metadata-only Assistant Retrieval Planning Runtime."""

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
from app.services.assistant_retrieval_runtime import build_assistant_retrieval_runtime  # noqa: E402
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

    assistant_key = f"assistant-retrieval-runtime-smoke-{uuid.uuid4().hex[:12]}"
    db = SessionLocal()
    try:
        assistant_runtime = build_assistant_runtime(
            db,
            organization_id=None,
            ownership_scope="global",
            data_origin="validation",
            assistant_name="Assistant Retrieval Runtime Smoke",
            assistant_key=assistant_key,
            assistant_version="1.0",
            assistant_type="platform_assistant",
            description="Metadata-only assistant retrieval planning smoke.",
            default_search_mode="enterprise_search",
            allowed_runtime_domains=["enterprise_search", "hybrid_search_runtime", "semantic_search_runtime", "workflow_runtime"],
            requested_by="assistant-retrieval-runtime-e2e-smoke",
            conversation_reference=f"conversation:{assistant_key}",
            requested_query="metadata-only retrieval planning",
            persist_snapshot=False,
        )
        assistant_id = assistant_runtime.get("assistant_id")
        retrieval_runtime = build_assistant_retrieval_runtime(
            db,
            assistant_id=assistant_id,
            assistant_session_id=assistant_runtime.get("assistant_session_id"),
            requested_query="metadata-only retrieval planning",
            selected_search_mode="enterprise_search",
        )
        persistence_execution_id = (retrieval_runtime.get("runtime_persistence") or {}).get("execution_id") if retrieval_runtime else None
        readback = read_runtime_persistence(db, execution_id=persistence_execution_id) if persistence_execution_id else {}
    finally:
        db.close()

    retrieval_runtime = retrieval_runtime or {}
    observed = {
        "assistant_retrieval_runtime_prepared": retrieval_runtime.get("assistant_retrieval_runtime_prepared") is True,
        "retrieval_plan_created": retrieval_runtime.get("retrieval_plan_created") is True,
        "selected_search_mode": retrieval_runtime.get("selected_search_mode"),
        "enterprise_search_planned": retrieval_runtime.get("enterprise_search_planned") is True,
        "hybrid_search_planned": bool(retrieval_runtime.get("hybrid_search_planned")),
        "semantic_search_planned": bool(retrieval_runtime.get("semantic_search_planned")),
        "retrieval_executed": bool(retrieval_runtime.get("retrieval_executed")),
        "answer_generated": bool(retrieval_runtime.get("answer_generated")),
        "llm_used": bool(retrieval_runtime.get("llm_used")),
        "tool_called": bool(retrieval_runtime.get("tool_called")),
        "workflow_executed": bool(retrieval_runtime.get("workflow_executed")),
        "autonomous_execution": bool(retrieval_runtime.get("autonomous_execution")),
        "postgresql_source_of_truth": retrieval_runtime.get("postgresql_source_of_truth") is True,
        "runtime_persistence": (retrieval_runtime.get("runtime_persistence") or {}).get("persistence_completed") is True
        and readback.get("persistence_status") == "persisted"
        and (readback.get("domains") or {}).get("assistant_retrieval_runtime", 0) >= 1,
    }
    expectations = {
        "assistant_retrieval_runtime_prepared": observed["assistant_retrieval_runtime_prepared"] is True,
        "retrieval_plan_created": observed["retrieval_plan_created"] is True,
        "selected_search_mode": observed["selected_search_mode"] == "enterprise_search",
        "enterprise_search_planned": observed["enterprise_search_planned"] is True,
        "hybrid_search_planned": observed["hybrid_search_planned"] is False,
        "semantic_search_planned": observed["semantic_search_planned"] is False,
        "retrieval_executed": observed["retrieval_executed"] is False,
        "answer_generated": observed["answer_generated"] is False,
        "llm_used": observed["llm_used"] is False,
        "tool_called": observed["tool_called"] is False,
        "workflow_executed": observed["workflow_executed"] is False,
        "autonomous_execution": observed["autonomous_execution"] is False,
        "postgresql_source_of_truth": observed["postgresql_source_of_truth"] is True,
        "runtime_persistence": observed["runtime_persistence"] is True,
    }
    expected_values = {
        "selected_search_mode": "enterprise_search",
        "hybrid_search_planned": False,
        "semantic_search_planned": False,
        "retrieval_executed": False,
        "answer_generated": False,
        "llm_used": False,
        "tool_called": False,
        "workflow_executed": False,
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
