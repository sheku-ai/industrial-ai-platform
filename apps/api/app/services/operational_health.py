from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import and_, case, func, select
from sqlalchemy.orm import Session

from app.models.artifact_publication import RuntimeArtifactPublication
from app.models.control_plane import OperationalJob, OperationalSchedule, SchedulerClaim, SchedulerRun
from app.models.runtime import RuntimeExecution, RuntimeExecutionAttempt
from app.schemas.operational_health import (
    ArtifactPublicationHealth,
    HealthFreshness,
    HealthSummary,
    OperationalHealthResponse,
    ReconciliationHealth,
    RuntimeHealth,
    SchedulerHealth,
)


@dataclass(frozen=True)
class OperationalHealthThresholds:
    pending_warning_seconds: int = 900
    stale_data_seconds: int = 300
    failed_run_critical_count: int = 5


class OperationalHealthEvaluator:
    @staticmethod
    def evaluate(
        *,
        scheduler: SchedulerHealth,
        runtime: RuntimeHealth,
        publications: ArtifactPublicationHealth,
        thresholds: OperationalHealthThresholds,
        calculated_at: datetime | None = None,
    ) -> tuple[str, int]:
        now = calculated_at or datetime.now(UTC)
        pending_age_issue = 0
        pending_timestamps = (
            scheduler.oldest_pending_run_at,
            runtime.oldest_non_terminal_execution_at,
            publications.oldest_unverified_publication_at,
        )
        if any(
            timestamp is not None and (now - timestamp).total_seconds() > thresholds.pending_warning_seconds
            for timestamp in pending_timestamps
        ):
            pending_age_issue = 1

        critical_issues = (
            runtime.dead_letter_executions
            + publications.checksum_conflict
            + (1 if scheduler.failed_runs >= thresholds.failed_run_critical_count else 0)
        )
        degraded_issues = (
            scheduler.overdue_schedules
            + scheduler.expired_claims
            + publications.missing
            + runtime.retryable_executions
            + pending_age_issue
        )
        if critical_issues > 0:
            return "critical", critical_issues + degraded_issues
        if degraded_issues > 0:
            return "degraded", degraded_issues
        return "healthy", 0


class OperationalHealthService:
    """Build a read-only organization-scoped health snapshot from PostgreSQL state."""

    def __init__(
        self,
        session: Session,
        *,
        thresholds: OperationalHealthThresholds | None = None,
    ) -> None:
        self.session = session
        self.thresholds = thresholds or OperationalHealthThresholds()

    def get_snapshot(self, organization_id: UUID) -> OperationalHealthResponse:
        now = datetime.now(UTC)
        scheduler = self._scheduler_health(organization_id, now)
        runtime = self._runtime_health(organization_id, now)
        publications = self._publication_health(organization_id)
        reconciliation = self._reconciliation_health(organization_id)
        overall_status, active_issues = OperationalHealthEvaluator.evaluate(
            scheduler=scheduler,
            runtime=runtime,
            publications=publications,
            thresholds=self.thresholds,
            calculated_at=now,
        )
        data_max_timestamp = self._data_max_timestamp(organization_id)
        age_seconds = None
        if data_max_timestamp is not None:
            age_seconds = max(0, int((now - data_max_timestamp).total_seconds()))

        return OperationalHealthResponse(
            summary=HealthSummary(
                organization_id=organization_id,
                overall_status=overall_status,
                active_issues=active_issues,
                calculated_at=now,
            ),
            scheduler=scheduler,
            runtime=runtime,
            artifact_publications=publications,
            reconciliation=reconciliation,
            freshness=HealthFreshness(
                calculated_at=now,
                data_max_timestamp=data_max_timestamp,
                age_seconds=age_seconds,
                is_stale=age_seconds is not None and age_seconds > self.thresholds.stale_data_seconds,
            ),
        )

    def _scheduler_health(self, organization_id: UUID, now: datetime) -> SchedulerHealth:
        jobs = self.session.execute(
            select(
                func.count().filter(OperationalJob.enabled.is_(True)),
                func.count().filter(OperationalJob.enabled.is_(False)),
            ).where(OperationalJob.organization_id == organization_id)
        ).one()
        schedules = self.session.execute(
            select(
                func.count().filter(OperationalSchedule.enabled.is_(True)),
                func.count().filter(
                    and_(
                        OperationalSchedule.enabled.is_(True),
                        OperationalSchedule.next_run_at.is_not(None),
                        OperationalSchedule.next_run_at < now,
                    )
                ),
                func.count().filter(
                    and_(
                        OperationalSchedule.enabled.is_(True),
                        OperationalSchedule.next_run_at.is_(None),
                    )
                ),
            ).where(OperationalSchedule.organization_id == organization_id)
        ).one()
        runs = self.session.execute(
            select(
                func.count().filter(SchedulerRun.status == "pending"),
                func.count().filter(SchedulerRun.status.in_(("claimed", "dispatched"))),
                func.count().filter(SchedulerRun.status == "failed"),
                func.min(case((SchedulerRun.status == "pending", SchedulerRun.requested_at))),
                func.max(case((SchedulerRun.status == "succeeded", SchedulerRun.finished_at))),
                func.max(case((SchedulerRun.status == "failed", SchedulerRun.finished_at))),
            ).where(SchedulerRun.organization_id == organization_id)
        ).one()
        expired_claims = (
            self.session.scalar(
                select(func.count())
                .select_from(SchedulerClaim)
                .where(
                    SchedulerClaim.organization_id == organization_id,
                    SchedulerClaim.expires_at < now,
                )
            )
            or 0
        )

        return SchedulerHealth(
            enabled_jobs=int(jobs[0] or 0),
            disabled_jobs=int(jobs[1] or 0),
            enabled_schedules=int(schedules[0] or 0),
            overdue_schedules=int(schedules[1] or 0),
            schedules_without_next_run=int(schedules[2] or 0),
            pending_runs=int(runs[0] or 0),
            active_runs=int(runs[1] or 0),
            failed_runs=int(runs[2] or 0),
            oldest_pending_run_at=runs[3],
            expired_claims=int(expired_claims),
            latest_success_at=runs[4],
            latest_failure_at=runs[5],
        )

    def _runtime_health(self, organization_id: UUID, now: datetime) -> RuntimeHealth:
        executions = self.session.execute(
            select(
                func.count().filter(RuntimeExecution.status.in_(("pending", "scheduled"))),
                func.count().filter(RuntimeExecution.status.in_(("leased", "running"))),
                func.count().filter(RuntimeExecution.status == "expired"),
                func.count().filter(RuntimeExecution.status == "failed"),
                func.count().filter(RuntimeExecution.status == "dead_lettered"),
                func.count().filter(RuntimeExecution.status == "cancelled"),
                func.min(
                    case(
                        (
                            RuntimeExecution.status.in_(("pending", "scheduled", "leased", "running", "expired")),
                            RuntimeExecution.requested_at,
                        )
                    )
                ),
            ).where(RuntimeExecution.organization_id == organization_id)
        ).one()
        attempts = self.session.execute(
            select(
                func.count().filter(
                    and_(
                        RuntimeExecutionAttempt.status.in_(("leased", "running")),
                        RuntimeExecutionAttempt.lease_expires_at < now,
                    )
                ),
                func.count().filter(
                    and_(
                        RuntimeExecutionAttempt.status.in_(("leased", "running")),
                        RuntimeExecutionAttempt.heartbeat_at.is_not(None),
                        RuntimeExecutionAttempt.heartbeat_at < now,
                        RuntimeExecutionAttempt.lease_expires_at < now,
                    )
                ),
            ).where(RuntimeExecutionAttempt.organization_id == organization_id)
        ).one()
        return RuntimeHealth(
            pending_executions=int(executions[0] or 0),
            running_executions=int(executions[1] or 0),
            retryable_executions=int(executions[2] or 0),
            failed_executions=int(executions[3] or 0),
            dead_letter_executions=int(executions[4] or 0),
            cancelled_executions=int(executions[5] or 0),
            oldest_non_terminal_execution_at=executions[6],
            expired_leases=int(attempts[0] or 0),
            stale_attempts=int(attempts[1] or 0),
        )

    def _publication_health(self, organization_id: UUID) -> ArtifactPublicationHealth:
        row = self.session.execute(
            select(
                func.count().filter(RuntimeArtifactPublication.status == "reserved"),
                func.count().filter(RuntimeArtifactPublication.status == "publishing"),
                func.count().filter(RuntimeArtifactPublication.status == "published"),
                func.count().filter(RuntimeArtifactPublication.status == "verified"),
                func.count().filter(RuntimeArtifactPublication.status == "missing"),
                func.count().filter(RuntimeArtifactPublication.status == "checksum_conflict"),
                func.count().filter(RuntimeArtifactPublication.status == "failed"),
                func.min(
                    case(
                        (
                            RuntimeArtifactPublication.status.in_(
                                ("reserved", "publishing", "published", "missing", "checksum_conflict")
                            ),
                            RuntimeArtifactPublication.created_at,
                        )
                    )
                ),
            ).where(RuntimeArtifactPublication.organization_id == organization_id)
        ).one()
        return ArtifactPublicationHealth(
            reserved=int(row[0] or 0),
            publishing=int(row[1] or 0),
            published=int(row[2] or 0),
            verified=int(row[3] or 0),
            missing=int(row[4] or 0),
            checksum_conflict=int(row[5] or 0),
            failed=int(row[6] or 0),
            oldest_unverified_publication_at=row[7],
        )

    def _reconciliation_health(self, organization_id: UUID) -> ReconciliationHealth:
        latest = (
            select(
                RuntimeArtifactPublication.artifact_id.label("artifact_id"),
                func.max(RuntimeArtifactPublication.publication_number).label("publication_number"),
            )
            .where(RuntimeArtifactPublication.organization_id == organization_id)
            .group_by(RuntimeArtifactPublication.artifact_id)
            .subquery()
        )
        candidates = self.session.execute(
            select(
                func.count(),
                func.min(RuntimeArtifactPublication.created_at),
                func.count().filter(RuntimeArtifactPublication.status == "missing"),
                func.count().filter(RuntimeArtifactPublication.status == "checksum_conflict"),
            )
            .join(
                latest,
                and_(
                    RuntimeArtifactPublication.artifact_id == latest.c.artifact_id,
                    RuntimeArtifactPublication.publication_number == latest.c.publication_number,
                ),
            )
            .where(
                RuntimeArtifactPublication.organization_id == organization_id,
                RuntimeArtifactPublication.status.in_(
                    ("reserved", "publishing", "published", "missing", "checksum_conflict")
                ),
            )
        ).one()
        run_times = self.session.execute(
            select(
                func.max(case((SchedulerRun.trigger_type == "manual", SchedulerRun.requested_at))),
                func.max(case((SchedulerRun.status == "succeeded", SchedulerRun.finished_at))),
                func.max(case((SchedulerRun.status == "failed", SchedulerRun.finished_at))),
            )
            .join(OperationalJob, OperationalJob.id == SchedulerRun.operational_job_id)
            .where(
                SchedulerRun.organization_id == organization_id,
                OperationalJob.organization_id == organization_id,
                OperationalJob.operation_type == "artifact_publication_reconciliation",
            )
        ).one()
        return ReconciliationHealth(
            candidate_count=int(candidates[0] or 0),
            oldest_candidate_at=candidates[1],
            missing_candidates=int(candidates[2] or 0),
            checksum_conflict_candidates=int(candidates[3] or 0),
            last_manual_run_at=run_times[0],
            last_successful_run_at=run_times[1],
            last_failed_run_at=run_times[2],
        )

    def _data_max_timestamp(self, organization_id: UUID) -> datetime | None:
        values = self.session.execute(
            select(
                select(func.max(RuntimeExecution.updated_at))
                .where(RuntimeExecution.organization_id == organization_id)
                .scalar_subquery(),
                select(func.max(RuntimeArtifactPublication.created_at))
                .where(RuntimeArtifactPublication.organization_id == organization_id)
                .scalar_subquery(),
                select(func.max(SchedulerRun.created_at))
                .where(SchedulerRun.organization_id == organization_id)
                .scalar_subquery(),
            )
        ).one()
        timestamps = [value for value in values if value is not None]
        return max(timestamps) if timestamps else None
