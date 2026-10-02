from datetime import UTC, datetime, timedelta

from sqlalchemy import DateTime, Integer, and_, cast, func, select, text
from sqlalchemy.orm import Session

from app.models.control_plane import OperationalSchedule
from app.models.runtime_worker import RuntimeWorker
from app.schemas.platform_health import PlatformHealthResponse
from app.services.runtime_worker_contracts import SCHEDULER_WORKER_TYPE


def build_worker_health_statement(stale_before: datetime):
    scheduler_worker = RuntimeWorker.worker_type == SCHEDULER_WORKER_TYPE
    active_state = RuntimeWorker.observed_state.in_(("ready", "busy"))
    active_desired = RuntimeWorker.desired_state == "active"
    last_cycle_started_at = cast(
        RuntimeWorker.metrics["last_cycle_started_at"].astext,
        DateTime(timezone=True),
    )
    last_cycle_completed_at = cast(
        RuntimeWorker.metrics["last_cycle_completed_at"].astext,
        DateTime(timezone=True),
    )
    cycles_completed = cast(
        RuntimeWorker.metrics["cycles_completed"].astext,
        Integer,
    )
    return select(
        func.count().filter(
            and_(
                scheduler_worker,
                active_desired,
                active_state,
                RuntimeWorker.heartbeat_at >= stale_before,
            )
        ),
        func.count().filter(
            and_(
                scheduler_worker,
                active_desired,
                active_state,
                RuntimeWorker.heartbeat_at < stale_before,
            )
        ),
        func.count().filter(
            and_(
                scheduler_worker,
                RuntimeWorker.observed_state == "failed",
                RuntimeWorker.heartbeat_at >= stale_before,
            )
        ),
        func.max(RuntimeWorker.heartbeat_at).filter(scheduler_worker),
        func.max(last_cycle_started_at).filter(scheduler_worker),
        func.max(last_cycle_completed_at).filter(scheduler_worker),
        func.max(cycles_completed).filter(scheduler_worker),
    )


def build_worker_count_statement(stale_before: datetime):
    statement = build_worker_health_statement(stale_before)
    return select(*list(statement.selected_columns)[:2])


def evaluate_platform_health(
    session: Session | None,
    *,
    worker_stale_seconds: int = 30,
    cycle_stale_seconds: int | None = None,
) -> PlatformHealthResponse:
    now = datetime.now(UTC)
    cycle_stale_seconds = cycle_stale_seconds or max(worker_stale_seconds * 4, 60)

    if session is None:
        return PlatformHealthResponse(
            status="critical",
            checked_at=now,
            database="unavailable",
            scheduler="unavailable",
            enabled_schedules=0,
            active_workers=0,
            stale_workers=0,
            detail="database session is unavailable",
        )

    try:
        session.execute(text("SELECT 1"))
        enabled_schedules = int(
            session.scalar(
                select(func.count()).select_from(OperationalSchedule).where(OperationalSchedule.enabled.is_(True))
            )
            or 0
        )
        stale_before = now - timedelta(seconds=worker_stale_seconds)
        worker_health = session.execute(build_worker_health_statement(stale_before)).one()
    except Exception:
        session.rollback()
        return PlatformHealthResponse(
            status="critical",
            checked_at=now,
            database="unavailable",
            scheduler="unavailable",
            enabled_schedules=0,
            active_workers=0,
            stale_workers=0,
            detail="database readiness check failed",
        )

    active_workers = int(worker_health[0] or 0)
    stale_workers = int(worker_health[1] or 0)
    degraded_workers = int(worker_health[2] or 0)
    latest_heartbeat_at = worker_health[3]
    latest_cycle_started_at = worker_health[4]
    latest_cycle_completed_at = worker_health[5]
    scheduler_cycles_completed = int(worker_health[6] or 0)

    heartbeat_current = bool(latest_heartbeat_at and latest_heartbeat_at >= stale_before)
    cycle_fresh_before = now - timedelta(seconds=cycle_stale_seconds)
    loop_progressing = bool(
        latest_cycle_completed_at and latest_cycle_completed_at >= cycle_fresh_before and scheduler_cycles_completed > 0
    )
    execution_capable = heartbeat_current and loop_progressing and degraded_workers == 0

    if enabled_schedules == 0:
        scheduler = "not_required"
        status = "healthy"
        detail = None
    elif active_workers == 0 and degraded_workers == 0:
        scheduler = "degraded"
        status = "degraded"
        detail = "enabled schedules exist without a current scheduler heartbeat"
    elif degraded_workers > 0:
        scheduler = "degraded"
        status = "degraded"
        detail = "scheduler worker reports a degraded state"
    elif not loop_progressing:
        scheduler = "degraded"
        status = "degraded"
        detail = "scheduler heartbeat is current but the scheduling loop is not progressing"
    else:
        scheduler = "healthy"
        status = "healthy"
        detail = None

    return PlatformHealthResponse(
        status=status,
        checked_at=now,
        database="healthy",
        scheduler=scheduler,
        enabled_schedules=enabled_schedules,
        active_workers=active_workers,
        stale_workers=stale_workers,
        degraded_workers=degraded_workers,
        latest_heartbeat_at=latest_heartbeat_at,
        latest_cycle_started_at=latest_cycle_started_at,
        latest_cycle_completed_at=latest_cycle_completed_at,
        scheduler_cycles_completed=scheduler_cycles_completed,
        scheduler_heartbeat_current=heartbeat_current,
        scheduler_loop_progressing=loop_progressing,
        scheduler_execution_capable=execution_capable,
        detail=detail,
    )
