from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.control_plane import OperationalJob, SchedulerRun
from app.models.runtime import RuntimeExecution

ACTIVE_RUNTIME_STATUSES = ("pending", "scheduled", "leased", "running")
REPLACEABLE_RUNTIME_STATUSES = ("pending", "scheduled")


@dataclass(frozen=True)
class SchedulerDispatchResult:
    scanned: int
    dispatched: int
    skipped: int
    cancelled_pending: int
    runtime_execution_ids: tuple[UUID, ...]


class SchedulerDispatchService:
    def __init__(self, session: Session) -> None:
        self.session = session

    @staticmethod
    def concurrency_allows_dispatch(
        *,
        policy: str,
        active_count: int,
        max_concurrent_runs: int,
    ) -> bool:
        if policy == "forbid_overlap":
            return active_count == 0
        if policy in ("allow_bounded", "replace_pending"):
            return active_count < max_concurrent_runs
        raise ValueError(f"unsupported concurrency policy: {policy}")

    def _lock_job(self, organization_id: UUID, job_id: UUID) -> None:
        lock_key = f"scheduler-dispatch:{organization_id}:{job_id}"
        self.session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"),
            {"lock_key": lock_key},
        )

    def dispatch_pending(
        self,
        organization_id: UUID,
        *,
        limit: int = 100,
        dispatched_at: datetime | None = None,
        dispatched_by: str | None = None,
    ) -> SchedulerDispatchResult:
        now = dispatched_at or datetime.now(UTC)
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)

        rows = self.session.execute(
            select(SchedulerRun, OperationalJob)
            .join(
                OperationalJob,
                (OperationalJob.id == SchedulerRun.operational_job_id)
                & (OperationalJob.organization_id == SchedulerRun.organization_id),
            )
            .where(
                SchedulerRun.organization_id == organization_id,
                SchedulerRun.status == "pending",
                OperationalJob.enabled.is_(True),
            )
            .order_by(SchedulerRun.requested_at, SchedulerRun.id)
            .with_for_update(skip_locked=True)
            .limit(limit)
        ).all()

        dispatched = 0
        skipped = 0
        cancelled_pending = 0
        runtime_execution_ids: list[UUID] = []

        for run, job in rows:
            self._lock_job(organization_id, job.id)

            active_count = (
                self.session.scalar(
                    select(func.count())
                    .select_from(RuntimeExecution)
                    .where(
                        RuntimeExecution.organization_id == organization_id,
                        RuntimeExecution.subject_type == "operational_job",
                        RuntimeExecution.subject_id == job.id,
                        RuntimeExecution.status.in_(ACTIVE_RUNTIME_STATUSES),
                    )
                )
                or 0
            )

            if job.concurrency_policy == "replace_pending":
                replacement = self.session.execute(
                    update(RuntimeExecution)
                    .where(
                        RuntimeExecution.organization_id == organization_id,
                        RuntimeExecution.subject_type == "operational_job",
                        RuntimeExecution.subject_id == job.id,
                        RuntimeExecution.status.in_(REPLACEABLE_RUNTIME_STATUSES),
                    )
                    .values(
                        status="cancelled",
                        cancel_requested_at=now,
                        finished_at=now,
                        error_code=None,
                        error_message=None,
                        updated_by=dispatched_by,
                    )
                )
                cancelled_pending += int(replacement.rowcount or 0)
                active_count = (
                    self.session.scalar(
                        select(func.count())
                        .select_from(RuntimeExecution)
                        .where(
                            RuntimeExecution.organization_id == organization_id,
                            RuntimeExecution.subject_type == "operational_job",
                            RuntimeExecution.subject_id == job.id,
                            RuntimeExecution.status.in_(("leased", "running")),
                        )
                    )
                    or 0
                )

            allowed = self.concurrency_allows_dispatch(
                policy=job.concurrency_policy,
                active_count=int(active_count),
                max_concurrent_runs=job.max_concurrent_runs,
            )
            if not allowed:
                run.status = "skipped"
                run.finished_at = now
                run.outcome = {
                    "reason": "concurrency_limit",
                    "policy": job.concurrency_policy,
                    "active_count": int(active_count),
                    "max_concurrent_runs": job.max_concurrent_runs,
                }
                skipped += 1
                continue

            idempotency_key = f"scheduler-run:{run.id}"
            runtime_id = self.session.scalar(
                pg_insert(RuntimeExecution)
                .values(
                    organization_id=organization_id,
                    execution_type=job.operation_type,
                    subject_type="operational_job",
                    subject_id=job.id,
                    requested_by=run.requested_by or dispatched_by,
                    correlation_id=run.correlation_id,
                    idempotency_key=idempotency_key,
                    priority=100,
                    status="pending",
                    requested_at=now,
                    available_at=now,
                    input_payload=dict(run.parameters_snapshot or {}),
                    policy_snapshot={
                        "concurrency_policy": job.concurrency_policy,
                        "misfire_policy": job.misfire_policy,
                        "max_concurrent_runs": job.max_concurrent_runs,
                        "max_runtime_seconds": job.max_runtime_seconds,
                        "scheduler_run_id": str(run.id),
                    },
                    metrics={},
                    created_by=dispatched_by,
                    updated_by=dispatched_by,
                )
                .on_conflict_do_nothing(
                    index_elements=[
                        RuntimeExecution.organization_id,
                        RuntimeExecution.execution_type,
                        RuntimeExecution.idempotency_key,
                    ],
                    index_where=RuntimeExecution.idempotency_key.is_not(None),
                )
                .returning(RuntimeExecution.id)
            )
            if runtime_id is None:
                runtime_id = self.session.scalar(
                    select(RuntimeExecution.id).where(
                        RuntimeExecution.organization_id == organization_id,
                        RuntimeExecution.execution_type == job.operation_type,
                        RuntimeExecution.idempotency_key == idempotency_key,
                    )
                )

            if runtime_id is None:
                run.status = "failed"
                run.finished_at = now
                run.error_code = "runtime_dispatch_failed"
                run.error_message = "runtime execution could not be created or resolved"
                skipped += 1
                continue

            run.runtime_execution_id = runtime_id
            run.status = "dispatched"
            run.started_at = now
            run.outcome = {
                "runtime_execution_id": str(runtime_id),
                "dispatched_by": dispatched_by,
            }
            runtime_execution_ids.append(runtime_id)
            dispatched += 1

        self.session.commit()
        return SchedulerDispatchResult(
            scanned=len(rows),
            dispatched=dispatched,
            skipped=skipped,
            cancelled_pending=cancelled_pending,
            runtime_execution_ids=tuple(runtime_execution_ids),
        )
