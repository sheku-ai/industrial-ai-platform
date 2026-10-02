from __future__ import annotations

from app.models.runtime_worker import RuntimeWorker
from app.schemas.operational_health import OperationalHealthResponse
from app.schemas.operational_health_issue import OperationalHealthIssue
from app.services.runtime_worker_health import RuntimeWorkerHealthService


def build_operational_health_issues(
    snapshot: OperationalHealthResponse,
    workers: list[RuntimeWorker],
    *,
    worker_health: RuntimeWorkerHealthService,
) -> list[OperationalHealthIssue]:
    """Build organization-scoped issues.

    Worker arguments remain for call-site compatibility but platform worker state is
    intentionally excluded from an organization health snapshot.
    """
    del workers, worker_health
    issues: list[OperationalHealthIssue] = []

    def add(code: str, severity: str, source: str, resource_type: str, message: str, value=None, key=None) -> None:
        issues.append(
            OperationalHealthIssue(
                code=code,
                severity=severity,
                source=source,
                resource_type=resource_type,
                resource_key=key,
                message=message,
                observed_value=value,
            )
        )

    if snapshot.runtime.dead_letter_executions:
        add(
            "runtime_dead_letter_executions",
            "critical",
            "runtime",
            "runtime.execution",
            "Dead-letter executions require operator review.",
            snapshot.runtime.dead_letter_executions,
        )
    if snapshot.artifact_publications.checksum_conflict:
        add(
            "artifact_checksum_conflict",
            "critical",
            "artifact_publications",
            "runtime.artifact_publication",
            "Artifact publication checksum conflicts were detected.",
            snapshot.artifact_publications.checksum_conflict,
        )
    if snapshot.scheduler.failed_runs >= 5:
        add(
            "scheduler_failed_runs_threshold",
            "critical",
            "scheduler",
            "control_plane.scheduler_run",
            "Scheduler failed runs reached the critical threshold.",
            snapshot.scheduler.failed_runs,
        )

    degraded = (
        (
            "runtime_expired_leases",
            snapshot.runtime.expired_leases,
            "runtime",
            "runtime.execution_attempt",
            "Expired execution leases require reconciliation.",
        ),
        (
            "runtime_retryable_executions",
            snapshot.runtime.retryable_executions,
            "runtime",
            "runtime.execution",
            "Executions are awaiting retry.",
        ),
        (
            "scheduler_overdue_schedules",
            snapshot.scheduler.overdue_schedules,
            "scheduler",
            "control_plane.schedule",
            "Enabled schedules are overdue.",
        ),
        (
            "scheduler_expired_claims",
            snapshot.scheduler.expired_claims,
            "scheduler",
            "control_plane.scheduler_claim",
            "Scheduler claims have expired.",
        ),
        (
            "artifact_publications_missing",
            snapshot.artifact_publications.missing,
            "artifact_publications",
            "runtime.artifact_publication",
            "Artifact publications are missing from target storage.",
        ),
    )
    for code, value, source, resource_type, message in degraded:
        if value:
            add(code, "degraded", source, resource_type, message, value)

    return sorted(
        issues,
        key=lambda item: (0 if item.severity == "critical" else 1, item.code, item.resource_key or ""),
    )
