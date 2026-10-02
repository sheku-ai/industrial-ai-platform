from datetime import UTC, datetime, timedelta

from app.schemas.operational_health import ArtifactPublicationHealth, RuntimeHealth, SchedulerHealth
from app.services.operational_health import OperationalHealthEvaluator, OperationalHealthThresholds


def _scheduler(**overrides):
    values = {
        "enabled_jobs": 0,
        "disabled_jobs": 0,
        "enabled_schedules": 0,
        "overdue_schedules": 0,
        "schedules_without_next_run": 0,
        "pending_runs": 0,
        "active_runs": 0,
        "failed_runs": 0,
        "oldest_pending_run_at": None,
        "expired_claims": 0,
        "latest_success_at": None,
        "latest_failure_at": None,
    }
    values.update(overrides)
    return SchedulerHealth(**values)


def _runtime(**overrides):
    values = {
        "pending_executions": 0,
        "running_executions": 0,
        "retryable_executions": 0,
        "failed_executions": 0,
        "dead_letter_executions": 0,
        "cancelled_executions": 0,
        "oldest_non_terminal_execution_at": None,
        "expired_leases": 0,
        "stale_attempts": 0,
    }
    values.update(overrides)
    return RuntimeHealth(**values)


def _publications(**overrides):
    values = {
        "reserved": 0,
        "publishing": 0,
        "published": 0,
        "verified": 0,
        "missing": 0,
        "checksum_conflict": 0,
        "failed": 0,
        "oldest_unverified_publication_at": None,
    }
    values.update(overrides)
    return ArtifactPublicationHealth(**values)


def test_health_is_healthy_without_issues() -> None:
    status, issues = OperationalHealthEvaluator.evaluate(
        scheduler=_scheduler(),
        runtime=_runtime(),
        publications=_publications(),
        thresholds=OperationalHealthThresholds(),
    )

    assert status == "healthy"
    assert issues == 0


def test_health_is_degraded_for_operational_recovery_signals() -> None:
    status, issues = OperationalHealthEvaluator.evaluate(
        scheduler=_scheduler(overdue_schedules=1, expired_claims=2),
        runtime=_runtime(retryable_executions=1),
        publications=_publications(missing=1),
        thresholds=OperationalHealthThresholds(),
    )

    assert status == "degraded"
    assert issues == 5


def test_health_is_critical_for_dead_letter_or_checksum_conflict() -> None:
    status, issues = OperationalHealthEvaluator.evaluate(
        scheduler=_scheduler(),
        runtime=_runtime(dead_letter_executions=1),
        publications=_publications(checksum_conflict=2),
        thresholds=OperationalHealthThresholds(),
    )

    assert status == "critical"
    assert issues == 3


def test_failed_run_threshold_is_configurable() -> None:
    status, issues = OperationalHealthEvaluator.evaluate(
        scheduler=_scheduler(failed_runs=3),
        runtime=_runtime(),
        publications=_publications(),
        thresholds=OperationalHealthThresholds(failed_run_critical_count=3),
    )

    assert status == "critical"
    assert issues == 1


def test_old_pending_state_degrades_health() -> None:
    now = datetime(2026, 6, 20, 12, 0, tzinfo=UTC)
    status, issues = OperationalHealthEvaluator.evaluate(
        scheduler=_scheduler(oldest_pending_run_at=now - timedelta(seconds=901)),
        runtime=_runtime(),
        publications=_publications(),
        thresholds=OperationalHealthThresholds(pending_warning_seconds=900),
        calculated_at=now,
    )

    assert status == "degraded"
    assert issues == 1


def test_enabled_schedules_without_organization_issues_remain_healthy() -> None:
    status, issues = OperationalHealthEvaluator.evaluate(
        scheduler=_scheduler(enabled_schedules=1),
        runtime=_runtime(),
        publications=_publications(),
        thresholds=OperationalHealthThresholds(),
    )

    assert status == "healthy"
    assert issues == 0


def test_scheduler_health_contract_excludes_platform_worker_state() -> None:
    assert {
        "worker_count",
        "active_workers",
        "degraded_workers",
        "stale_workers",
        "latest_worker_status",
    }.isdisjoint(SchedulerHealth.model_fields)
