from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies.runtime_context import RuntimeRequestContext, get_runtime_context
from app.db.session import SessionLocal, get_db
from app.models.audit import AuditEvent, AuditHistory
from app.models.runtime_worker import RuntimeWorker
from app.schemas.runtime_worker_events import RuntimeWorkerEventRead, RuntimeWorkerHistoryRead
from app.schemas.runtime_worker_summary import RuntimeWorkerSummaryRead
from app.schemas.runtime_workers import (
    RuntimeWorkerDesiredStateUpdate,
    RuntimeWorkerPersistentRead,
    RuntimeWorkerRead,
)
from app.security.resource_scope import ResourceScope, ResourceScopeType
from app.services.runtime_worker_control import RuntimeWorkerControl, RuntimeWorkerControlError
from app.services.runtime_worker_health import RuntimeWorkerHealthService
from app.services.runtime_worker_summary import build_runtime_worker_summary

router = APIRouter(prefix="/control-plane/workers", tags=["control-plane-workers"])
WORKER_RESOURCE_SCOPE = ResourceScope.platform()


def _require_platform_scope(context: RuntimeRequestContext) -> None:
    if not context.is_scope(ResourceScopeType.PLATFORM):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="platform authorization scope is required",
        )


def _require(context: RuntimeRequestContext, action: str) -> None:
    _require_platform_scope(context)
    if not context.has_permission("control_plane.workers", action):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"worker {action} permission is required",
        )


def _stale_after_seconds() -> int:
    return max(int(os.getenv("WORKER_HEARTBEAT_STALE_SECONDS", "30")), 1)


def _health_service() -> RuntimeWorkerHealthService:
    if SessionLocal is None:
        raise HTTPException(status_code=503, detail="database is not configured")
    return RuntimeWorkerHealthService(
        SessionLocal,
        stale_after_seconds=_stale_after_seconds(),
    )


def _read_worker(worker: RuntimeWorker) -> RuntimeWorkerRead:
    stale_after = _stale_after_seconds()
    readiness = _health_service().evaluate(worker)
    persisted = RuntimeWorkerPersistentRead.model_validate(worker)
    return RuntimeWorkerRead(
        **persisted.model_dump(),
        resource_scope=WORKER_RESOURCE_SCOPE.scope_type.value,
        organization_id=WORKER_RESOURCE_SCOPE.organization_id,
        heartbeat_stale=readiness.heartbeat_stale,
        heartbeat_stale_after_seconds=stale_after,
        accepting_work=readiness.accepting_work,
        ready=readiness.ready,
    )


def _get_worker(db: Session, worker_key: str) -> RuntimeWorker:
    worker = db.scalar(select(RuntimeWorker).where(RuntimeWorker.worker_key == worker_key))
    if worker is None:
        raise HTTPException(status_code=404, detail="worker not found")
    return worker


@router.get("", response_model=list[RuntimeWorkerRead])
def list_workers(
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> list[RuntimeWorkerRead]:
    _require(context, "read")
    workers = list(
        db.scalars(
            select(RuntimeWorker).order_by(
                RuntimeWorker.worker_type.asc(),
                RuntimeWorker.worker_key.asc(),
            )
        ).all()
    )
    return [_read_worker(worker) for worker in workers]


@router.get("/summary", response_model=RuntimeWorkerSummaryRead)
def get_worker_summary(
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> RuntimeWorkerSummaryRead:
    _require(context, "read")
    workers = list(db.scalars(select(RuntimeWorker)).all())
    return build_runtime_worker_summary(
        workers,
        health_service=_health_service(),
    )


@router.get("/{worker_key}", response_model=RuntimeWorkerRead)
def get_worker(
    worker_key: str,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> RuntimeWorkerRead:
    _require(context, "read")
    return _read_worker(_get_worker(db, worker_key))


@router.get("/{worker_key}/events", response_model=list[RuntimeWorkerEventRead])
def list_worker_events(
    worker_key: str,
    limit: int = Query(default=50, ge=1, le=200),
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> list[AuditEvent]:
    _require(context, "read")
    worker = _get_worker(db, worker_key)
    return list(
        db.scalars(
            select(AuditEvent)
            .where(
                AuditEvent.resource_type == "runtime.worker",
                AuditEvent.resource_id == str(worker.id),
                AuditEvent.organization_id.is_(None),
            )
            .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
            .limit(limit)
        ).all()
    )


@router.get("/{worker_key}/history", response_model=list[RuntimeWorkerHistoryRead])
def list_worker_history(
    worker_key: str,
    limit: int = Query(default=50, ge=1, le=200),
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> list[AuditHistory]:
    _require(context, "read")
    worker = _get_worker(db, worker_key)
    return list(
        db.scalars(
            select(AuditHistory)
            .where(
                AuditHistory.entity_type == "runtime.worker",
                AuditHistory.entity_id == str(worker.id),
                AuditHistory.organization_id.is_(None),
            )
            .order_by(AuditHistory.created_at.desc(), AuditHistory.id.desc())
            .limit(limit)
        ).all()
    )


@router.put("/{worker_key}/desired-state", response_model=RuntimeWorkerRead)
def update_worker_desired_state(
    worker_key: str,
    payload: RuntimeWorkerDesiredStateUpdate,
    context: RuntimeRequestContext = Depends(get_runtime_context),
) -> RuntimeWorkerRead:
    _require(context, "administer")
    if SessionLocal is None:
        raise HTTPException(status_code=503, detail="database is not configured")
    try:
        worker = RuntimeWorkerControl(SessionLocal).set_desired_state(
            worker_key=worker_key,
            desired_state=payload.desired_state,
            organization_id=WORKER_RESOURCE_SCOPE.organization_id,
            actor_id=context.actor_reference,
        )
        return _read_worker(worker)
    except RuntimeWorkerControlError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
