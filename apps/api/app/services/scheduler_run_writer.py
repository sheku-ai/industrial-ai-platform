from __future__ import annotations

from datetime import UTC
from uuid import UUID

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.control_plane import OperationalJob, OperationalSchedule, SchedulerRun
from app.services.scheduler_policy import as_utc


class SchedulerRunWriter:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_scheduled_run(
        self,
        *,
        organization_id: UUID,
        schedule: OperationalSchedule,
        job: OperationalJob,
        scheduled_for,
        requested_by: str | None,
    ) -> UUID | None:
        logical_run_key = (
            f"schedule:{schedule.id}:v{schedule.schedule_version}:{as_utc(scheduled_for).astimezone(UTC).isoformat()}"
        )
        return self.session.scalar(
            pg_insert(SchedulerRun)
            .values(
                organization_id=organization_id,
                operational_job_id=job.id,
                schedule_id=schedule.id,
                schedule_version=schedule.schedule_version,
                trigger_type="schedule",
                logical_run_key=logical_run_key,
                scheduled_for=scheduled_for,
                status="pending",
                parameters_snapshot=dict(job.parameters or {}),
                requested_by=requested_by,
                outcome={"misfire_policy": job.misfire_policy},
            )
            .on_conflict_do_nothing(constraint="uq_control_plane_scheduler_runs_logical_key")
            .returning(SchedulerRun.id)
        )
