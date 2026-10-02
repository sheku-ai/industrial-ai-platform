from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.dependencies.runtime_context import RuntimeRequestContext, get_runtime_context
from app.db.session import get_db
from app.repositories.runtime import (
    RuntimeArtifactRepository,
    RuntimeAttemptRepository,
    RuntimeEventRepository,
    RuntimeExecutionRepository,
)
from app.schemas.runtime_api import (
    RuntimeArtifactRead,
    RuntimeAttemptRead,
    RuntimeCancelRequest,
    RuntimeEventRead,
    RuntimeExecutionCreate,
    RuntimeExecutionCreateResponse,
    RuntimeExecutionRead,
    RuntimeRetryRequest,
)
from app.services.runtime_lifecycle import (
    InvalidRuntimeTransitionError,
    RuntimeLifecycleService,
    RuntimeNotFoundError,
)

router = APIRouter(prefix="/runtime", tags=["runtime"])


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="runtime execution was not found")


def _transition_error(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.post("/executions", response_model=RuntimeExecutionCreateResponse, status_code=status.HTTP_201_CREATED)
def create_execution(
    payload: RuntimeExecutionCreate,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> RuntimeExecutionCreateResponse:
    execution, created = RuntimeLifecycleService(db).create_or_get(
        organization_id=context.organization_id,
        execution_type=payload.execution_type,
        subject_type=payload.subject_type,
        subject_id=payload.subject_id,
        idempotency_key=payload.idempotency_key,
        requested_by=context.actor_reference,
        correlation_id=payload.correlation_id,
        priority=payload.priority,
        available_at=payload.available_at,
        input_payload=payload.input_payload,
        policy_snapshot=payload.policy_snapshot,
    )
    db.commit()
    return RuntimeExecutionCreateResponse(execution=RuntimeExecutionRead.model_validate(execution), created=created)


@router.get("/executions", response_model=list[RuntimeExecutionRead])
def list_executions(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    status_filter: list[str] | None = Query(default=None, alias="status"),
    execution_type: str | None = Query(default=None),
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> list[RuntimeExecutionRead]:
    items = RuntimeExecutionRepository(db).list(
        context.organization_id,
        statuses=status_filter,
        execution_type=execution_type,
        limit=limit,
        offset=offset,
    )
    return [RuntimeExecutionRead.model_validate(item) for item in items]


@router.get("/executions/{execution_id}", response_model=RuntimeExecutionRead)
def get_execution(
    execution_id: UUID,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> RuntimeExecutionRead:
    execution = RuntimeExecutionRepository(db).get(context.organization_id, execution_id)
    if execution is None:
        raise _not_found()
    return RuntimeExecutionRead.model_validate(execution)


@router.get("/executions/{execution_id}/attempts", response_model=list[RuntimeAttemptRead])
def list_attempts(
    execution_id: UUID,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> list[RuntimeAttemptRead]:
    if RuntimeExecutionRepository(db).get(context.organization_id, execution_id) is None:
        raise _not_found()
    items = RuntimeAttemptRepository(db).list(context.organization_id, execution_id, limit=limit, offset=offset)
    return [RuntimeAttemptRead.model_validate(item) for item in items]


@router.get("/executions/{execution_id}/events", response_model=list[RuntimeEventRead])
def list_events(
    execution_id: UUID,
    after_sequence: int | None = Query(default=None, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> list[RuntimeEventRead]:
    if RuntimeExecutionRepository(db).get(context.organization_id, execution_id) is None:
        raise _not_found()
    items = RuntimeEventRepository(db).list(
        context.organization_id,
        execution_id,
        after_sequence=after_sequence,
        limit=limit,
    )
    return [RuntimeEventRead.model_validate(item) for item in items]


@router.get("/executions/{execution_id}/artifacts", response_model=list[RuntimeArtifactRead])
def list_artifacts(
    execution_id: UUID,
    artifact_type: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> list[RuntimeArtifactRead]:
    if RuntimeExecutionRepository(db).get(context.organization_id, execution_id) is None:
        raise _not_found()
    items = RuntimeArtifactRepository(db).list(
        context.organization_id,
        execution_id,
        artifact_type=artifact_type,
        limit=limit,
        offset=offset,
    )
    return [RuntimeArtifactRead.from_orm_model(item) for item in items]


@router.post("/executions/{execution_id}/cancel", response_model=RuntimeExecutionRead)
def request_cancel(
    execution_id: UUID,
    payload: RuntimeCancelRequest,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> RuntimeExecutionRead:
    try:
        execution = RuntimeLifecycleService(db).request_cancel(
            context.organization_id,
            execution_id,
            actor_reference=context.actor_reference,
        )
    except RuntimeNotFoundError as exc:
        raise _not_found() from exc
    except InvalidRuntimeTransitionError as exc:
        raise _transition_error(exc) from exc
    db.commit()
    return RuntimeExecutionRead.model_validate(execution)


@router.post("/executions/{execution_id}/retry", response_model=RuntimeExecutionRead)
def retry_execution(
    execution_id: UUID,
    payload: RuntimeRetryRequest,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> RuntimeExecutionRead:
    if not context.can_administer:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="runtime administration permission is required"
        )
    try:
        execution = RuntimeLifecycleService(db).retry(
            context.organization_id,
            execution_id,
            available_at=payload.available_at,
            actor_reference=context.actor_reference,
        )
    except RuntimeNotFoundError as exc:
        raise _not_found() from exc
    except InvalidRuntimeTransitionError as exc:
        raise _transition_error(exc) from exc
    db.commit()
    return RuntimeExecutionRead.model_validate(execution)
