from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import CroniterBadCronError, croniter
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.control_plane import OperationalJob, OperationalSchedule
from app.services.scheduler_policy import as_utc, plan_due_occurrences
from app.services.scheduler_run_writer import SchedulerRunWriter


class SchedulerConfigurationError(ValueError):
    pass


@dataclass(frozen=True)
class SchedulerEvaluationResult:
    evaluated_at: datetime
    scanned: int
    due: int
    created: int
    skipped: int
    next_runs_updated: int
    run_ids: tuple[UUID, ...]


class SchedulerEvaluationService:
    def __init__(self, session: Session) -> None:
        self.session = session

    @staticmethod
    def next_occurrence(expression: str, timezone_name: str, after: datetime) -> datetime:
        try:
            zone = ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError as exc:
            raise SchedulerConfigurationError(f"unknown timezone: {timezone_name}") from exc
        local_after = as_utc(after).astimezone(zone)
        try:
            next_local = croniter(expression, local_after).get_next(datetime)
        except (CroniterBadCronError, ValueError) as exc:
            raise SchedulerConfigurationError(f"invalid cron expression: {expression}") from exc
        if next_local.tzinfo is None:
            next_local = next_local.replace(tzinfo=zone)
        return next_local.astimezone(UTC)

    def _next_for_schedule(self, schedule: OperationalSchedule, after: datetime) -> datetime | None:
        occurrence = self.next_occurrence(schedule.schedule_expression, schedule.timezone, after)
        if schedule.end_at is not None and occurrence > as_utc(schedule.end_at):
            return None
        return occurrence

    def initialize_schedule(self, schedule: OperationalSchedule, *, now: datetime | None = None) -> None:
        evaluated_at = as_utc(now or datetime.now(UTC))
        if schedule.end_at is not None and evaluated_at > as_utc(schedule.end_at):
            schedule.next_run_at = None
        else:
            baseline = evaluated_at
            if schedule.start_at is not None and baseline < as_utc(schedule.start_at):
                baseline = as_utc(schedule.start_at)
            schedule.next_run_at = self._next_for_schedule(schedule, baseline)
        schedule.last_evaluated_at = evaluated_at

    def evaluate_due(
        self,
        organization_id: UUID,
        *,
        limit: int = 100,
        evaluated_at: datetime | None = None,
        requested_by: str | None = None,
    ) -> SchedulerEvaluationResult:
        now = as_utc(evaluated_at or datetime.now(UTC))
        bounded_limit = max(1, min(limit, 500))
        rows = self.session.execute(
            select(OperationalSchedule, OperationalJob)
            .join(
                OperationalJob,
                (OperationalJob.id == OperationalSchedule.operational_job_id)
                & (OperationalJob.organization_id == OperationalSchedule.organization_id),
            )
            .where(
                OperationalSchedule.organization_id == organization_id,
                OperationalSchedule.enabled.is_(True),
                OperationalJob.enabled.is_(True),
                OperationalSchedule.next_run_at.is_not(None),
                OperationalSchedule.next_run_at <= now,
            )
            .order_by(OperationalSchedule.next_run_at, OperationalSchedule.id)
            .with_for_update(skip_locked=True)
            .limit(bounded_limit)
        ).all()

        created = 0
        skipped = 0
        updated = 0
        run_ids: list[UUID] = []
        writer = SchedulerRunWriter(self.session)

        for schedule, job in rows:
            if schedule.next_run_at is None:
                skipped += 1
                continue
            try:
                plan = plan_due_occurrences(
                    policy=job.misfire_policy,
                    scheduled_for=schedule.next_run_at,
                    evaluated_at=now,
                    start_at=schedule.start_at,
                    end_at=schedule.end_at,
                    limit=max(1, bounded_limit - created),
                    next_occurrence=lambda cursor, current_schedule=schedule: self._next_for_schedule(
                        current_schedule, cursor
                    ),
                )
            except ValueError as exc:
                raise SchedulerConfigurationError(str(exc)) from exc

            if not plan.occurrences:
                skipped += 1

            for occurrence in plan.occurrences:
                if created >= bounded_limit:
                    break
                run_id = writer.create_scheduled_run(
                    organization_id=organization_id,
                    schedule=schedule,
                    job=job,
                    scheduled_for=occurrence,
                    requested_by=requested_by,
                )
                if run_id is None:
                    skipped += 1
                else:
                    created += 1
                    run_ids.append(run_id)

            schedule.last_evaluated_at = now
            schedule.next_run_at = plan.next_run_at
            updated += 1

        self.session.commit()
        return SchedulerEvaluationResult(
            evaluated_at=now,
            scanned=len(rows),
            due=len(rows),
            created=created,
            skipped=skipped,
            next_runs_updated=updated,
            run_ids=tuple(run_ids),
        )
