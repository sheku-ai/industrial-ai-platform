from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.control_plane import OperationalJob, SchedulerRun


@dataclass(frozen=True)
class ManualTriggerResult:
    run: SchedulerRun
    created: bool


class SchedulerManualTriggerService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def trigger(
        self,
        organization_id: UUID,
        job_id: UUID,
        *,
        idempotency_key: str,
        requested_by: str | None,
        correlation_id: str | None = None,
        parameters_override: dict | None = None,
        requested_at: datetime | None = None,
    ) -> ManualTriggerResult:
        now = requested_at or datetime.now(UTC)
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)

        job = self.session.scalar(
            select(OperationalJob).where(
                OperationalJob.organization_id == organization_id,
                OperationalJob.id == job_id,
            )
        )
        if job is None:
            raise LookupError("operational job not found")
        if not job.enabled:
            raise ValueError("operational job is disabled")

        parameters = dict(job.parameters or {})
        parameters.update(parameters_override or {})
        logical_run_key = f"manual:{job.id}:{idempotency_key}"

        run_id = self.session.scalar(
            pg_insert(SchedulerRun)
            .values(
                organization_id=organization_id,
                operational_job_id=job.id,
                schedule_id=None,
                schedule_version=None,
                trigger_type="manual",
                logical_run_key=logical_run_key,
                scheduled_for=None,
                requested_at=now,
                status="pending",
                parameters_snapshot=parameters,
                requested_by=requested_by,
                correlation_id=correlation_id,
                outcome={"idempotency_key": idempotency_key},
            )
            .on_conflict_do_nothing(constraint="uq_control_plane_scheduler_runs_logical_key")
            .returning(SchedulerRun.id)
        )
        created = run_id is not None

        if run_id is None:
            run = self.session.scalar(
                select(SchedulerRun).where(
                    SchedulerRun.organization_id == organization_id,
                    SchedulerRun.logical_run_key == logical_run_key,
                )
            )
            if run is None:
                self.session.rollback()
                raise RuntimeError("manual scheduler run could not be created or resolved")
        else:
            run = self.session.get(SchedulerRun, run_id)
            if run is None:
                self.session.rollback()
                raise RuntimeError("manual scheduler run could not be loaded")

        self.session.commit()
        self.session.refresh(run)
        return ManualTriggerResult(run=run, created=created)
