from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.workflows import (
    WorkflowCreateRequest,
    WorkflowCreateResponse,
    WorkflowHealthResponse,
    WorkflowRunCreateRequest,
    WorkflowRunResponse,
)
from app.services.workflow_runtime import (
    build_workflow_health,
    build_workflow_run_runtime,
    build_workflow_runtime,
    list_workflows_runtime,
    read_workflow,
    read_workflow_run,
)

router = APIRouter(prefix="/workflows", tags=["workflows"])


@router.post("", response_model=WorkflowCreateResponse)
def create_workflow(payload: WorkflowCreateRequest, db: Session = Depends(get_db)):
    return build_workflow_runtime(
        db,
        workflow_name=payload.workflow_name,
        workflow_key=payload.workflow_key,
        workflow_version=payload.workflow_version,
        workflow_type=payload.workflow_type,
        description=payload.description,
        steps=[step.model_dump() for step in payload.steps],
        requested_by=payload.requested_by,
        runtime_metadata=payload.runtime_metadata,
    )


@router.get("")
def list_workflows(
    workflow_status: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    return list_workflows_runtime(db, workflow_status=workflow_status, limit=limit)


@router.get("/health", response_model=WorkflowHealthResponse)
def get_workflow_health(db: Session = Depends(get_db)):
    return build_workflow_health(db)


@router.get("/runs/{workflow_run_id}", response_model=WorkflowRunResponse)
def get_workflow_run(workflow_run_id: str, db: Session = Depends(get_db)):
    result = read_workflow_run(db, workflow_run_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="workflow run not found")
    return result


@router.get("/{workflow_id}", response_model=WorkflowCreateResponse)
def get_workflow(workflow_id: str, db: Session = Depends(get_db)):
    result = read_workflow(db, workflow_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="workflow not found")
    return result


@router.post("/{workflow_id}/runs", response_model=WorkflowRunResponse)
def create_workflow_run(workflow_id: str, payload: WorkflowRunCreateRequest, db: Session = Depends(get_db)):
    result = build_workflow_run_runtime(
        db,
        workflow_id=workflow_id,
        requested_by=payload.requested_by,
        runtime_metadata=payload.runtime_metadata,
    )
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="workflow not found")
    return result
