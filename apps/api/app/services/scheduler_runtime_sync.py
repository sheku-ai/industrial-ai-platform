from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.control_plane import SchedulerRun
from app.models.runtime import RuntimeExecution

TERMINAL_RUNTIME_STATUSES = ("succeeded", "failed", "cancelled", "dead_lettered")


@dataclass(frozen=True)
class SchedulerRuntimeSyncResult:
    scanned: int
    succeeded: int
    failed: int
    cancelled: int
    run_ids: tuple[UUID, ...]


class SchedulerRuntimeSyncService:
    def __init__(self, session: Session) -> None:
        self.session = session

    @staticmethod
    def map_status(runtime_status: str) -> str:
        if runtime_status == "succeeded":
            return "succeeded"
        if runtime_status == "cancelled":
            return "cancelled"
        if runtime_status in ("failed", "dead_lettered"):
            return "failed"
        raise ValueError(f"runtime status is not terminal: {runtime_status}")

    def synchronize(
        self,
        organization_id: UUID,
        *,
        limit: int = 100,
        synchronized_at: datetime | None = None,
    ) -> SchedulerRuntimeSyncResult:
        now = synchronized_at or datetime.now(UTC)
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)

        rows = self.session.execute(
            select(SchedulerRun, RuntimeExecution)
            .join(
                RuntimeExecution,
                (RuntimeExecution.id == SchedulerRun.runtime_execution_id)
                & (RuntimeExecution.organization_id == SchedulerRun.organization_id),
            )
            .where(
                SchedulerRun.organization_id == organization_id,
                SchedulerRun.status == "dispatched",
                RuntimeExecution.status.in_(TERMINAL_RUNTIME_STATUSES),
            )
            .order_by(RuntimeExecution.finished_at, SchedulerRun.id)
            .with_for_update(of=SchedulerRun, skip_locked=True)
            .limit(limit)
        ).all()

        succeeded = 0
        failed = 0
        cancelled = 0
        run_ids: list[UUID] = []

        for run, execution in rows:
            target = self.map_status(execution.status)
            run.status = target
            run.finished_at = execution.finished_at or now
            run.outcome = {
                **dict(run.outcome or {}),
                "runtime_execution_id": str(execution.id),
                "runtime_status": execution.status,
                "runtime_metrics": dict(execution.metrics or {}),
            }

            if target == "succeeded":
                run.error_code = None
                run.error_message = None
                succeeded += 1
            elif target == "cancelled":
                run.error_code = None
                run.error_message = None
                cancelled += 1
            else:
                run.error_code = execution.error_code or "runtime_execution_failed"
                run.error_message = execution.error_message or f"runtime execution ended as {execution.status}"
                failed += 1

            run_ids.append(run.id)

        self.session.commit()
        return SchedulerRuntimeSyncResult(
            scanned=len(rows),
            succeeded=succeeded,
            failed=failed,
            cancelled=cancelled,
            run_ids=tuple(run_ids),
        )
