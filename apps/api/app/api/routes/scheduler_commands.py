from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.dependencies.runtime_context import RuntimeRequestContext, get_runtime_context
from app.db.session import get_db
from app.models.control_plane import SchedulerRun
from app.schemas.scheduler_schedules import SchedulerRunRead
from app.services.scheduler_manual_trigger import SchedulerManualTriggerService

router = APIRouter(prefix="/control-plane/scheduler", tags=["control-plane-scheduler"])


@router.post("/jobs/{job_id}/runs", response_model=SchedulerRunRead)
def create_scheduler_run(
    job_id: UUID,
    payload: dict[str, Any],
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> SchedulerRun:
    if not context.has_permission("control_plane.scheduler", "administer"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="scheduler administer permission is required",
        )

    idempotency_key = payload.get("idempotency_key")
    if not isinstance(idempotency_key, str) or not idempotency_key.strip():
        raise HTTPException(status_code=422, detail="idempotency_key is required")
    if len(idempotency_key) > 255:
        raise HTTPException(status_code=422, detail="idempotency_key exceeds 255 characters")

    correlation_id = payload.get("correlation_id")
    if correlation_id is not None and not isinstance(correlation_id, str):
        raise HTTPException(status_code=422, detail="correlation_id must be a string")
    if isinstance(correlation_id, str) and len(correlation_id) > 128:
        raise HTTPException(status_code=422, detail="correlation_id exceeds 128 characters")

    parameters_override = payload.get("parameters_override", {})
    if not isinstance(parameters_override, dict):
        raise HTTPException(status_code=422, detail="parameters_override must be an object")

    try:
        result = SchedulerManualTriggerService(db).trigger(
            context.organization_id,
            job_id,
            idempotency_key=idempotency_key.strip(),
            requested_by=context.actor_reference,
            correlation_id=correlation_id,
            parameters_override=parameters_override,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return result.run
