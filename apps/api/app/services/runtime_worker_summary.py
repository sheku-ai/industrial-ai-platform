from __future__ import annotations

from datetime import UTC, datetime

from app.models.runtime_worker import RuntimeWorker
from app.schemas.runtime_worker_summary import RuntimeWorkerSummaryRead
from app.services.runtime_worker_health import RuntimeWorkerHealthService


def build_runtime_worker_summary(
    workers: list[RuntimeWorker],
    *,
    health_service: RuntimeWorkerHealthService,
) -> RuntimeWorkerSummaryRead:
    readiness = [health_service.evaluate(worker) for worker in workers]
    active = [item for item in readiness if item.desired_state == "active"]
    accepting = sum(1 for item in readiness if item.accepting_work)
    stale = sum(1 for item in readiness if item.heartbeat_stale)
    failed = sum(1 for item in readiness if item.observed_state == "failed")
    offline = sum(1 for item in readiness if item.observed_state == "offline")
    degraded = sum(1 for item in readiness if item.heartbeat_stale or item.observed_state in {"failed", "offline"})
    return RuntimeWorkerSummaryRead(
        calculated_at=datetime.now(UTC),
        total_workers=len(workers),
        active_desired=sum(1 for item in readiness if item.desired_state == "active"),
        paused_desired=sum(1 for item in readiness if item.desired_state == "paused"),
        draining_desired=sum(1 for item in readiness if item.desired_state == "draining"),
        disabled_desired=sum(1 for item in readiness if item.desired_state == "disabled"),
        ready_workers=sum(1 for item in readiness if item.ready),
        accepting_work=accepting,
        stale_workers=stale,
        failed_workers=failed,
        offline_workers=offline,
        busy_workers=sum(1 for item in readiness if item.observed_state == "busy"),
        degraded_workers=degraded,
        available_capacity_ratio=round(accepting / len(active), 4) if active else 0.0,
    )
