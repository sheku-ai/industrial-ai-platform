from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from app.services.scheduler_health import evaluate_scheduler_operational_health


class _Session:
    def __init__(self, worker):
        self.worker = worker

    def scalar(self, _statement):
        return self.worker


def _worker(now: datetime, **overrides):
    values = {
        "desired_state": "active",
        "observed_state": "ready",
        "heartbeat_at": now,
        "metrics": {
            "last_cycle_completed_at": now.isoformat(),
            "cycles_completed": 3,
        },
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_scheduler_health_is_unhealthy_without_worker_state() -> None:
    snapshot = evaluate_scheduler_operational_health(
        _Session(None),
        owner_id="scheduler-container",
        heartbeat_stale_seconds=30,
        cycle_stale_seconds=60,
        checked_at=datetime(2026, 6, 21, tzinfo=UTC),
    )

    assert snapshot.healthy is False
    assert snapshot.reason == "scheduler worker state is missing"


def test_scheduler_health_requires_running_status() -> None:
    now = datetime(2026, 6, 21, tzinfo=UTC)
    snapshot = evaluate_scheduler_operational_health(
        _Session(_worker(now, observed_state="failed")),
        owner_id="scheduler-container",
        heartbeat_stale_seconds=30,
        cycle_stale_seconds=60,
        checked_at=now,
    )

    assert snapshot.healthy is False
    assert "degraded" in snapshot.reason


def test_scheduler_health_rejects_stale_heartbeat() -> None:
    now = datetime(2026, 6, 21, tzinfo=UTC)
    snapshot = evaluate_scheduler_operational_health(
        _Session(_worker(now, heartbeat_at=now - timedelta(seconds=31))),
        owner_id="scheduler-container",
        heartbeat_stale_seconds=30,
        cycle_stale_seconds=60,
        checked_at=now,
    )

    assert snapshot.healthy is False
    assert snapshot.reason == "scheduler heartbeat is stale"


def test_scheduler_health_rejects_stale_cycle_progress() -> None:
    now = datetime(2026, 6, 21, tzinfo=UTC)
    snapshot = evaluate_scheduler_operational_health(
        _Session(
            _worker(
                now,
                metrics={
                    "last_cycle_completed_at": (
                        now - timedelta(seconds=61)
                    ).isoformat(),
                    "cycles_completed": 3,
                },
            )
        ),
        owner_id="scheduler-container",
        heartbeat_stale_seconds=30,
        cycle_stale_seconds=60,
        checked_at=now,
    )

    assert snapshot.healthy is False
    assert snapshot.reason == "scheduler loop has not completed a recent cycle"


def test_scheduler_health_is_healthy_with_current_heartbeat_and_cycle() -> None:
    now = datetime(2026, 6, 21, tzinfo=UTC)
    snapshot = evaluate_scheduler_operational_health(
        _Session(_worker(now)),
        owner_id="scheduler-container",
        heartbeat_stale_seconds=30,
        cycle_stale_seconds=60,
        checked_at=now,
    )

    assert snapshot.healthy is True
    assert snapshot.cycles_completed == 3
    assert snapshot.reason == "scheduler heartbeat and loop progress are current"
