"""Metadata-only Workflow Runtime foundation."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.models.workflow_runtime import WorkflowDefinition, WorkflowRun, WorkflowStep
from app.repositories.workflow import WorkflowRepository
from app.services.workflow_contracts import WorkflowExecutionPlan, WorkflowRuntimeResult
from app.services.workflow_gateway import build_workflow_gateway, build_workflow_health
from app.services.workflow_session import build_workflow_definition_request, build_workflow_session


def workflow_to_dict(record: WorkflowDefinition, *, steps: list[WorkflowStep] | None = None) -> dict[str, Any]:
    return {
        "workflow_id": str(record.workflow_id),
        "workflow_name": record.workflow_name,
        "workflow_key": record.workflow_key,
        "workflow_status": record.workflow_status,
        "workflow_version": record.workflow_version,
        "workflow_type": record.workflow_type,
        "description": record.description,
        "runtime_metadata": record.runtime_metadata or {},
        "steps": [workflow_step_to_dict(step) for step in steps] if steps is not None else [],
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
    }


def workflow_step_to_dict(record: WorkflowStep) -> dict[str, Any]:
    return {
        "workflow_step_id": str(record.workflow_step_id),
        "workflow_id": str(record.workflow_id),
        "step_key": record.step_key,
        "step_name": record.step_name,
        "step_order": record.step_order,
        "step_type": record.step_type,
        "step_status": record.step_status,
        "runtime_domain": record.runtime_domain,
        "runtime_action": record.runtime_action,
        "runtime_metadata": record.runtime_metadata or {},
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
    }


def workflow_run_to_dict(record: WorkflowRun) -> dict[str, Any]:
    return {
        "workflow_run_id": str(record.workflow_run_id),
        "workflow_id": str(record.workflow_id),
        "run_status": record.run_status,
        "execution_state": record.execution_state,
        "requested_by": record.requested_by,
        "started_at": record.started_at.isoformat() if record.started_at else None,
        "completed_at": record.completed_at.isoformat() if record.completed_at else None,
        "failed_at": record.failed_at.isoformat() if record.failed_at else None,
        "failure_reason": record.failure_reason,
        "runtime_metadata": record.runtime_metadata or {},
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
    }


def _execution_plan(
    session_payload: dict[str, Any], workflow_id: str | None, workflow_run_id: str | None
) -> WorkflowExecutionPlan:
    request_payload = session_payload.get("request") if isinstance(session_payload.get("request"), dict) else {}
    request = build_workflow_definition_request(
        workflow_name=request_payload.get("workflow_name"),
        workflow_key=request_payload.get("workflow_key"),
        workflow_version=request_payload.get("workflow_version"),
        workflow_type=request_payload.get("workflow_type"),
        description=request_payload.get("description"),
        steps=request_payload.get("steps") if isinstance(request_payload.get("steps"), list) else [],
        requested_by=request_payload.get("requested_by"),
        runtime_metadata=request_payload.get("runtime_metadata")
        if isinstance(request_payload.get("runtime_metadata"), dict)
        else {},
    )
    return WorkflowExecutionPlan(
        session=build_workflow_session(request),
        workflow_id=workflow_id,
        workflow_run_id=workflow_run_id,
    )


def build_workflow_runtime(
    db: Session,
    *,
    workflow_name: str,
    workflow_key: str | None = None,
    workflow_version: str | None = None,
    workflow_type: str | None = None,
    description: str | None = None,
    steps: list[dict[str, Any]] | None = None,
    requested_by: str | None = None,
    runtime_metadata: dict[str, Any] | None = None,
    persist_snapshot: bool = True,
) -> dict[str, Any]:
    gateway = build_workflow_gateway(
        db,
        workflow_name=workflow_name,
        workflow_key=workflow_key,
        workflow_version=workflow_version,
        workflow_type=workflow_type,
        description=description,
        steps=steps,
        requested_by=requested_by,
        runtime_metadata=runtime_metadata,
    )
    if gateway.get("blocking_issues"):
        return {
            "workflow_runtime_schema_version": "1",
            "workflow_runtime_prepared": False,
            "workflow_gateway": gateway,
            "workflow_definition_created": False,
            "workflow_steps_created": False,
            "workflow_run_created": False,
            "workflow_execution_planned": False,
            "workflow_executed": False,
            "external_action_called": False,
            "ai_used": False,
            "llm_used": False,
            "assistant_used": False,
            "autonomous_execution": False,
            "postgresql_source_of_truth": True,
            "runtime_persistence": {"runtime_persistence": False, "persistence_completed": False},
            "blocking_issues": gateway.get("blocking_issues") or [],
            "warnings": gateway.get("warnings") or [],
        }
    repository = WorkflowRepository(db)
    session = gateway.get("workflow_session") if isinstance(gateway.get("workflow_session"), dict) else {}
    request = session.get("request") if isinstance(session.get("request"), dict) else {}
    workflow, workflow_created = repository.create_workflow(
        workflow_name=str(request.get("workflow_name")),
        workflow_key=str(request.get("workflow_key")),
        workflow_status="prepared",
        workflow_version=str(request.get("workflow_version") or "1.0"),
        workflow_type=str(request.get("workflow_type") or "platform_runtime"),
        description=request.get("description"),
        runtime_metadata={
            **(session.get("runtime_metadata") if isinstance(session.get("runtime_metadata"), dict) else {}),
            "workflow_executed": False,
            "external_action_called": False,
            "ai_used": False,
            "llm_used": False,
            "assistant_used": False,
            "autonomous_execution": False,
        },
    )
    step_records: list[WorkflowStep] = []
    created_steps = 0
    for item in request.get("steps") if isinstance(request.get("steps"), list) else []:
        step, created = repository.create_workflow_step(
            workflow_id=workflow.workflow_id,
            step_key=str(item.get("step_key")),
            step_name=str(item.get("step_name")),
            step_order=int(item.get("step_order") or 0),
            step_type=str(item.get("step_type")),
            step_status=str(item.get("step_status") or "prepared"),
            runtime_domain=str(item.get("runtime_domain")),
            runtime_action=str(item.get("runtime_action")),
            runtime_metadata=item.get("runtime_metadata") if isinstance(item.get("runtime_metadata"), dict) else {},
        )
        step_records.append(step)
        created_steps += 1 if created else 0
    workflow_run = repository.create_workflow_run(
        workflow_id=workflow.workflow_id,
        run_status="planned",
        execution_state="metadata_only",
        requested_by=request.get("requested_by"),
        runtime_metadata={
            "workflow_execution_planned": True,
            "workflow_executed": False,
            "external_action_called": False,
            "ai_used": False,
            "llm_used": False,
            "assistant_used": False,
            "autonomous_execution": False,
            "postgresql_source_of_truth": True,
        },
    )
    db.commit()
    workflow_payload = workflow_to_dict(workflow, steps=step_records)
    workflow_run_payload = workflow_run_to_dict(workflow_run)
    plan = _execution_plan(session, str(workflow.workflow_id), str(workflow_run.workflow_run_id))
    result = WorkflowRuntimeResult(
        execution_plan=plan,
        workflow_status=workflow.workflow_status,
        run_status=workflow_run.run_status,
        workflow_definition_created=True,
        workflow_steps_created=bool(step_records),
        workflow_run_created=True,
        step_count=len(step_records),
    )
    payload = {
        "workflow_runtime_schema_version": "1",
        "workflow_runtime_prepared": True,
        "workflow_gateway": gateway,
        "workflow": workflow_payload,
        "workflow_steps": [workflow_step_to_dict(step) for step in step_records],
        "workflow_run": workflow_run_payload,
        "workflow_execution_plan": plan.as_dict(),
        "workflow_runtime_result": result.as_dict(),
        "workflow_id": str(workflow.workflow_id),
        "workflow_run_id": str(workflow_run.workflow_run_id),
        "workflow_status": workflow.workflow_status,
        "run_status": workflow_run.run_status,
        "step_count": len(step_records),
        "workflow_definition_created": True,
        "workflow_definition_inserted": workflow_created,
        "workflow_steps_created": bool(step_records),
        "workflow_run_created": True,
        "workflow_execution_planned": True,
        "workflow_executed": False,
        "external_action_called": False,
        "ai_used": False,
        "llm_used": False,
        "assistant_used": False,
        "autonomous_execution": False,
        "postgresql_source_of_truth": True,
        "blocking_issues": [],
        "warnings": gateway.get("warnings") or [],
    }
    if persist_snapshot:
        from app.services.runtime_persistence_runtime import persist_runtime_outputs

        payload["runtime_persistence"] = persist_runtime_outputs(
            db,
            execution_id=f"workflow-runtime:{workflow_run.workflow_run_id}",
            artifact_id=None,
            runtime_outputs={"workflow_runtime": payload},
        )
        payload["runtime_persistence"] = {
            **payload["runtime_persistence"],
            "runtime_persistence": bool(payload["runtime_persistence"].get("persistence_completed")),
        }
    return payload


def build_workflow_run_runtime(
    db: Session,
    *,
    workflow_id: str,
    requested_by: str | None = None,
    runtime_metadata: dict[str, Any] | None = None,
    persist_snapshot: bool = True,
) -> dict[str, Any] | None:
    try:
        workflow_uuid = uuid.UUID(str(workflow_id))
    except (TypeError, ValueError):
        return None
    repository = WorkflowRepository(db)
    workflow = repository.get_workflow(workflow_uuid)
    if workflow is None:
        return None
    steps = repository.list_workflow_steps(workflow.workflow_id)
    workflow_run = repository.create_workflow_run(
        workflow_id=workflow.workflow_id,
        run_status="planned",
        execution_state="metadata_only",
        requested_by=requested_by,
        runtime_metadata={
            **dict(runtime_metadata or {}),
            "workflow_execution_planned": True,
            "workflow_executed": False,
            "external_action_called": False,
            "ai_used": False,
            "llm_used": False,
            "assistant_used": False,
            "autonomous_execution": False,
            "postgresql_source_of_truth": True,
        },
    )
    db.commit()
    payload = {
        "workflow_runtime_schema_version": "1",
        "workflow_runtime_prepared": True,
        "workflow": workflow_to_dict(workflow, steps=steps),
        "workflow_run": workflow_run_to_dict(workflow_run),
        "workflow_id": str(workflow.workflow_id),
        "workflow_run_id": str(workflow_run.workflow_run_id),
        "workflow_status": workflow.workflow_status,
        "run_status": workflow_run.run_status,
        "step_count": len(steps),
        "workflow_definition_created": False,
        "workflow_steps_created": bool(steps),
        "workflow_run_created": True,
        "workflow_execution_planned": True,
        "workflow_executed": False,
        "external_action_called": False,
        "ai_used": False,
        "llm_used": False,
        "assistant_used": False,
        "autonomous_execution": False,
        "postgresql_source_of_truth": True,
    }
    if persist_snapshot:
        from app.services.runtime_persistence_runtime import persist_runtime_outputs

        payload["runtime_persistence"] = persist_runtime_outputs(
            db,
            execution_id=f"workflow-runtime:{workflow_run.workflow_run_id}",
            artifact_id=None,
            runtime_outputs={"workflow_runtime": payload},
        )
        payload["runtime_persistence"] = {
            **payload["runtime_persistence"],
            "runtime_persistence": bool(payload["runtime_persistence"].get("persistence_completed")),
        }
    return payload


def read_workflow(db: Session, workflow_id: str) -> dict[str, Any] | None:
    try:
        workflow_uuid = uuid.UUID(str(workflow_id))
    except (TypeError, ValueError):
        return None
    repository = WorkflowRepository(db)
    workflow = repository.get_workflow(workflow_uuid)
    if workflow is None:
        return None
    return workflow_to_dict(workflow, steps=repository.list_workflow_steps(workflow.workflow_id))


def list_workflows_runtime(db: Session, *, workflow_status: str | None = None, limit: int = 100) -> dict[str, Any]:
    repository = WorkflowRepository(db)
    workflows = repository.list_workflows(workflow_status=workflow_status, limit=limit)
    return {
        "workflow_list_schema_version": "1",
        "workflow_count": len(workflows),
        "workflows": [
            workflow_to_dict(workflow, steps=repository.list_workflow_steps(workflow.workflow_id))
            for workflow in workflows
        ],
        "postgresql_source_of_truth": True,
    }


def read_workflow_run(db: Session, workflow_run_id: str) -> dict[str, Any] | None:
    try:
        run_uuid = uuid.UUID(str(workflow_run_id))
    except (TypeError, ValueError):
        return None
    record = WorkflowRepository(db).get_workflow_run(run_uuid)
    return workflow_run_to_dict(record) if record is not None else None


__all__ = [
    "build_workflow_health",
    "build_workflow_run_runtime",
    "build_workflow_runtime",
    "list_workflows_runtime",
    "read_workflow",
    "read_workflow_run",
]
