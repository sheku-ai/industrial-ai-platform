from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies.runtime_context import RuntimeRequestContext, get_runtime_context
from app.db.session import get_db
from app.models.control_plane import OperationalJob, OperationalSchedule, SchedulerRun
from app.schemas.scheduler_jobs import OperationalJobCreate, OperationalJobRead, OperationalJobUpdate
from app.schemas.scheduler_schedules import (
    OperationalScheduleCreate,
    OperationalScheduleRead,
    OperationalScheduleUpdate,
    SchedulerEvaluationRequest,
    SchedulerEvaluationResponse,
    SchedulerRunRead,
)
from app.services.scheduler_evaluation import SchedulerConfigurationError, SchedulerEvaluationService

router = APIRouter(prefix="/control-plane/scheduler", tags=["control-plane-scheduler"])


def _require(context: RuntimeRequestContext, action: str) -> None:
    if not context.has_permission("control_plane.scheduler", action):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"scheduler {action} permission is required",
        )


def _job_or_404(db: Session, organization_id: UUID, job_id: UUID) -> OperationalJob:
    job = db.scalar(
        select(OperationalJob).where(
            OperationalJob.organization_id == organization_id,
            OperationalJob.id == job_id,
        )
    )
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="operational job not found")
    return job


def _schedule_or_404(db: Session, organization_id: UUID, schedule_id: UUID) -> OperationalSchedule:
    schedule = db.scalar(
        select(OperationalSchedule).where(
            OperationalSchedule.organization_id == organization_id,
            OperationalSchedule.id == schedule_id,
        )
    )
    if schedule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="operational schedule not found")
    return schedule


@router.get("/jobs", response_model=list[OperationalJobRead])
def list_jobs(
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> list[OperationalJob]:
    _require(context, "read")
    return list(
        db.scalars(
            select(OperationalJob)
            .where(OperationalJob.organization_id == context.organization_id)
            .order_by(OperationalJob.code)
        )
    )


@router.post("/jobs", response_model=OperationalJobRead, status_code=status.HTTP_201_CREATED)
def create_job(
    payload: OperationalJobCreate,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> OperationalJob:
    _require(context, "administer")
    job = OperationalJob(
        organization_id=context.organization_id,
        created_by=context.actor_reference,
        updated_by=context.actor_reference,
        **payload.model_dump(),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


@router.patch("/jobs/{job_id}", response_model=OperationalJobRead)
def update_job(
    job_id: UUID,
    payload: OperationalJobUpdate,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> OperationalJob:
    _require(context, "administer")
    job = _job_or_404(db, context.organization_id, job_id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(job, key, value)
    job.updated_by = context.actor_reference
    db.commit()
    db.refresh(job)
    return job


@router.get("/schedules", response_model=list[OperationalScheduleRead])
def list_schedules(
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> list[OperationalSchedule]:
    _require(context, "read")
    return list(
        db.scalars(
            select(OperationalSchedule)
            .where(OperationalSchedule.organization_id == context.organization_id)
            .order_by(OperationalSchedule.created_at)
        )
    )


@router.post("/schedules", response_model=OperationalScheduleRead, status_code=status.HTTP_201_CREATED)
def create_schedule(
    payload: OperationalScheduleCreate,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> OperationalSchedule:
    _require(context, "administer")
    _job_or_404(db, context.organization_id, payload.operational_job_id)
    schedule = OperationalSchedule(
        organization_id=context.organization_id,
        created_by=context.actor_reference,
        updated_by=context.actor_reference,
        **payload.model_dump(),
    )
    try:
        SchedulerEvaluationService(db).initialize_schedule(schedule)
    except SchedulerConfigurationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    db.add(schedule)
    db.commit()
    db.refresh(schedule)
    return schedule


@router.patch("/schedules/{schedule_id}", response_model=OperationalScheduleRead)
def update_schedule(
    schedule_id: UUID,
    payload: OperationalScheduleUpdate,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> OperationalSchedule:
    _require(context, "administer")
    schedule = _schedule_or_404(db, context.organization_id, schedule_id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(schedule, key, value)
    schedule.schedule_version += 1
    schedule.updated_by = context.actor_reference
    try:
        SchedulerEvaluationService(db).initialize_schedule(schedule)
    except SchedulerConfigurationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    db.commit()
    db.refresh(schedule)
    return schedule


@router.get("/runs", response_model=list[SchedulerRunRead])
def list_runs(
    limit: int = 100,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> list[SchedulerRun]:
    _require(context, "read")
    bounded_limit = max(1, min(limit, 500))
    return list(
        db.scalars(
            select(SchedulerRun)
            .where(SchedulerRun.organization_id == context.organization_id)
            .order_by(SchedulerRun.created_at.desc())
            .limit(bounded_limit)
        )
    )


@router.post("/evaluate", response_model=SchedulerEvaluationResponse)
def evaluate_schedules(
    payload: SchedulerEvaluationRequest,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> SchedulerEvaluationResponse:
    _require(context, "administer")
    evaluated_at = payload.evaluated_at or datetime.now(UTC)
    result = SchedulerEvaluationService(db).evaluate_due(
        context.organization_id,
        limit=payload.limit,
        evaluated_at=evaluated_at,
        requested_by=context.actor_reference,
    )
    return SchedulerEvaluationResponse(
        evaluated_at=result.evaluated_at,
        scanned=result.scanned,
        due=result.due,
        created=result.created,
        skipped=result.skipped,
        next_runs_updated=result.next_runs_updated,
        run_ids=list(result.run_ids),
    )
