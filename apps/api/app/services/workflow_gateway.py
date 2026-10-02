"""Workflow Runtime gateway."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.repositories.workflow import WorkflowRepository
from app.services.workflow_contracts import WorkflowHealthResult
from app.services.workflow_session import (
    build_workflow_definition_request,
    build_workflow_session,
    serialize_workflow_session,
)


def build_workflow_gateway(
    db: Session,
    *,
    workflow_name: str | None,
    workflow_key: str | None = None,
    workflow_version: str | None = None,
    workflow_type: str | None = None,
    description: str | None = None,
    steps: list[dict[str, Any]] | None = None,
    requested_by: str | None = None,
    runtime_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    request = build_workflow_definition_request(
        workflow_name=workflow_name,
        workflow_key=workflow_key,
        workflow_version=workflow_version,
        workflow_type=workflow_type,
        description=description,
        steps=steps,
        requested_by=requested_by,
        runtime_metadata=runtime_metadata,
    )
    session = serialize_workflow_session(build_workflow_session(request))
    ready = bool(session.get("workflow_session_ready")) and not session.get("blocking_issues")
    return {
        "workflow_gateway_schema_version": "1",
        "workflow_gateway_ready": ready,
        "gateway_status": "ready" if ready else "blocked",
        "workflow_session": session,
        "source_of_truth": "postgresql",
        "workflow_runtime_prepared": ready,
        "workflow_execution_planned": ready,
        "workflow_executed": False,
        "external_action_called": False,
        "ai_used": False,
        "llm_used": False,
        "assistant_used": False,
        "autonomous_execution": False,
        "postgresql_source_of_truth": True,
        "blocking_issues": session.get("blocking_issues") or [],
        "warnings": session.get("warnings") or [],
        "next_available_actions": [
            {
                "action": "create_workflow_run",
                "available": ready,
                "status": "ready" if ready else "blocked",
                "reason": None if ready else "workflow_gateway_blocked",
            }
        ],
    }


def build_workflow_health(db: Session) -> dict[str, Any]:
    workflows = WorkflowRepository(db).list_workflows(limit=500)
    return {
        **WorkflowHealthResult().as_dict(),
        "workflow_count": len(workflows),
    }
