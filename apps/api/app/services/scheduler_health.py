from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.runtime_worker import RuntimeWorker
from app.services.runtime_worker_contracts import SCHEDULER_WORKER_TYPE


@dataclass(frozen=True)
class SchedulerOperationalHealth:
    healthy: bool
    reason: str
    owner_id: str
    status: str | None
    heartbeat_at: datetime | None
    last_cycle_completed_at: datetime | None
    cycles_completed: int


def evaluate_scheduler_operational_health(
    session: Session,
    *,
    owner_id: str,
    heartbeat_stale_seconds: int,
    cycle_stale_seconds: int,
    checked_at: datetime | None = None,
) -> SchedulerOperationalHealth:
    now = checked_at or datetime.now(UTC)
    worker = session.scalar(
        select(RuntimeWorker).where(
            RuntimeWorker.worker_key == owner_id,
            RuntimeWorker.worker_type == SCHEDULER_WORKER_TYPE,
        )
    )

    if worker is None:
        return SchedulerOperationalHealth(
            healthy=False,
            reason="scheduler worker state is missing",
            owner_id=owner_id,
            status=None,
            heartbeat_at=None,
            last_cycle_completed_at=None,
            cycles_completed=0,
        )

    status = {
        "ready": "running",
        "busy": "running",
        "failed": "degraded",
        "offline": "stopped",
    }.get(worker.observed_state, worker.observed_state)
    last_cycle_completed_at = _metric_datetime(worker.metrics, "last_cycle_completed_at")
    cycles_completed = _metric_int(worker.metrics, "cycles_completed")

    if worker.desired_state != "active" or worker.observed_state not in {"ready", "busy"}:
        return SchedulerOperationalHealth(
            healthy=False,
            reason=f"scheduler worker status is {status}",
            owner_id=owner_id,
            status=status,
            heartbeat_at=worker.heartbeat_at,
            last_cycle_completed_at=last_cycle_completed_at,
            cycles_completed=cycles_completed,
        )

    heartbeat_before = now - timedelta(seconds=heartbeat_stale_seconds)
    if worker.heartbeat_at < heartbeat_before:
        return SchedulerOperationalHealth(
            healthy=False,
            reason="scheduler heartbeat is stale",
            owner_id=owner_id,
            status=status,
            heartbeat_at=worker.heartbeat_at,
            last_cycle_completed_at=last_cycle_completed_at,
            cycles_completed=cycles_completed,
        )

    cycle_before = now - timedelta(seconds=cycle_stale_seconds)
    if last_cycle_completed_at is None or last_cycle_completed_at < cycle_before:
        return SchedulerOperationalHealth(
            healthy=False,
            reason="scheduler loop has not completed a recent cycle",
            owner_id=owner_id,
            status=status,
            heartbeat_at=worker.heartbeat_at,
            last_cycle_completed_at=last_cycle_completed_at,
            cycles_completed=cycles_completed,
        )

    if cycles_completed < 1:
        return SchedulerOperationalHealth(
            healthy=False,
            reason="scheduler has not completed any cycles",
            owner_id=owner_id,
            status=status,
            heartbeat_at=worker.heartbeat_at,
            last_cycle_completed_at=last_cycle_completed_at,
            cycles_completed=0,
        )

    return SchedulerOperationalHealth(
        healthy=True,
        reason="scheduler heartbeat and loop progress are current",
        owner_id=owner_id,
        status=status,
        heartbeat_at=worker.heartbeat_at,
        last_cycle_completed_at=last_cycle_completed_at,
        cycles_completed=cycles_completed,
    )


def _metric_int(metrics: dict[str, object], key: str) -> int:
    try:
        return int(metrics.get(key, 0) or 0)
    except (TypeError, ValueError):
        return 0


def _metric_datetime(metrics: dict[str, object], key: str) -> datetime | None:
    value = metrics.get(key)
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
