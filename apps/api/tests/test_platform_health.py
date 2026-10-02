from datetime import UTC, datetime, timedelta

from sqlalchemy.dialects import postgresql

from app.services.platform_health import (
    build_worker_count_statement,
    build_worker_health_statement,
    evaluate_platform_health,
)


class _Result:
    def __init__(self, one=None):
        self._one = one

    def one(self):
        return self._one


class _Session:
    def __init__(
        self,
        enabled_schedules=0,
        active_workers=0,
        stale_workers=0,
        degraded_workers=0,
        latest_heartbeat_at=None,
        latest_cycle_started_at=None,
        latest_cycle_completed_at=None,
        cycles_completed=0,
        fail=False,
    ):
        self.enabled_schedules = enabled_schedules
        self.worker_health = (
            active_workers,
            stale_workers,
            degraded_workers,
            latest_heartbeat_at,
            latest_cycle_started_at,
            latest_cycle_completed_at,
            cycles_completed,
        )
        self.fail = fail
        self.calls = 0
        self.rolled_back = False

    def execute(self, statement):
        self.calls += 1
        if self.fail:
            raise RuntimeError("unavailable")
        if self.calls == 1:
            return _Result()
        return _Result(self.worker_health)

    def scalar(self, statement):
        return self.enabled_schedules

    def rollback(self):
        self.rolled_back = True


def test_worker_count_statement_limits_active_and_stale_counts_to_running_workers() -> None:
    statement = build_worker_count_statement(datetime(2026, 6, 20, tzinfo=UTC))
    sql = str(statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    worker_table = "runtime.workers"

    assert sql.count(f"{worker_table}.worker_type = 'runtime.scheduler'") >= 2
    assert sql.count(f"{worker_table}.desired_state = 'active'") == 2
    assert sql.count(f"{worker_table}.observed_state IN ('ready', 'busy')") == 2
    assert f"{worker_table}.heartbeat_at >=" in sql
    assert f"{worker_table}.heartbeat_at <" in sql


def test_worker_health_statement_includes_operational_progress_evidence() -> None:
    statement = build_worker_health_statement(datetime(2026, 6, 20, tzinfo=UTC))
    sql = str(statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))

    assert "last_cycle_started_at" in sql
    assert "last_cycle_completed_at" in sql
    assert "cycles_completed" in sql
    assert "observed_state = 'failed'" in sql


def test_platform_health_is_critical_without_database_session() -> None:
    snapshot = evaluate_platform_health(None)
    assert snapshot.status == "critical"
    assert snapshot.database == "unavailable"


def test_platform_health_is_healthy_when_scheduler_not_required() -> None:
    snapshot = evaluate_platform_health(_Session(enabled_schedules=0))
    assert snapshot.status == "healthy"
    assert snapshot.scheduler == "not_required"


def test_platform_health_is_degraded_without_current_worker() -> None:
    snapshot = evaluate_platform_health(
        _Session(enabled_schedules=2, active_workers=0, stale_workers=1)
    )
    assert snapshot.status == "degraded"
    assert snapshot.scheduler == "degraded"
    assert snapshot.enabled_schedules == 2
    assert snapshot.stale_workers == 1
    assert snapshot.scheduler_execution_capable is False


def test_platform_health_is_degraded_when_heartbeat_exists_without_loop_progress() -> None:
    now = datetime.now(UTC)
    snapshot = evaluate_platform_health(
        _Session(
            enabled_schedules=1,
            active_workers=1,
            latest_heartbeat_at=now,
            latest_cycle_started_at=now,
            latest_cycle_completed_at=now - timedelta(minutes=10),
            cycles_completed=4,
        )
    )

    assert snapshot.status == "degraded"
    assert snapshot.scheduler_heartbeat_current is True
    assert snapshot.scheduler_loop_progressing is False
    assert snapshot.scheduler_execution_capable is False


def test_platform_health_is_degraded_when_worker_reports_error_state() -> None:
    now = datetime.now(UTC)
    snapshot = evaluate_platform_health(
        _Session(
            enabled_schedules=1,
            degraded_workers=1,
            latest_heartbeat_at=now,
            latest_cycle_completed_at=now,
            cycles_completed=4,
        )
    )

    assert snapshot.status == "degraded"
    assert snapshot.scheduler == "degraded"
    assert snapshot.degraded_workers == 1


def test_platform_health_is_healthy_with_current_heartbeat_and_cycle_progress() -> None:
    now = datetime.now(UTC)
    snapshot = evaluate_platform_health(
        _Session(
            enabled_schedules=1,
            active_workers=1,
            latest_heartbeat_at=now,
            latest_cycle_started_at=now,
            latest_cycle_completed_at=now,
            cycles_completed=5,
        )
    )

    assert snapshot.status == "healthy"
    assert snapshot.scheduler == "healthy"
    assert snapshot.scheduler_heartbeat_current is True
    assert snapshot.scheduler_loop_progressing is True
    assert snapshot.scheduler_execution_capable is True
    assert snapshot.scheduler_cycles_completed == 5


def test_platform_health_rolls_back_when_database_check_fails() -> None:
    session = _Session(fail=True)
    snapshot = evaluate_platform_health(session)
    assert snapshot.status == "critical"
    assert session.rolled_back is True
