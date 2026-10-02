from datetime import UTC, datetime, timedelta

import pytest

from app.services.scheduler_policy import plan_due_occurrences

UTC = UTC


def _next_hour(value: datetime) -> datetime:
    return value + timedelta(hours=1)


def test_skip_policy_drops_missed_occurrence() -> None:
    scheduled = datetime(2026, 6, 20, 10, 0, tzinfo=UTC)
    now = datetime(2026, 6, 20, 12, 0, tzinfo=UTC)

    plan = plan_due_occurrences(
        policy="skip",
        scheduled_for=scheduled,
        evaluated_at=now,
        start_at=None,
        end_at=None,
        limit=10,
        next_occurrence=_next_hour,
    )

    assert plan.occurrences == ()
    assert plan.next_run_at == datetime(2026, 6, 20, 13, 0, tzinfo=UTC)


def test_run_once_collapses_missed_occurrences() -> None:
    scheduled = datetime(2026, 6, 20, 10, 0, tzinfo=UTC)
    now = datetime(2026, 6, 20, 12, 0, tzinfo=UTC)

    plan = plan_due_occurrences(
        policy="run_once",
        scheduled_for=scheduled,
        evaluated_at=now,
        start_at=None,
        end_at=None,
        limit=10,
        next_occurrence=_next_hour,
    )

    assert plan.occurrences == (scheduled,)
    assert plan.next_run_at == datetime(2026, 6, 20, 13, 0, tzinfo=UTC)


def test_catch_up_bounded_respects_limit() -> None:
    scheduled = datetime(2026, 6, 20, 10, 0, tzinfo=UTC)
    now = datetime(2026, 6, 20, 14, 0, tzinfo=UTC)

    plan = plan_due_occurrences(
        policy="catch_up_bounded",
        scheduled_for=scheduled,
        evaluated_at=now,
        start_at=None,
        end_at=None,
        limit=3,
        next_occurrence=_next_hour,
    )

    assert plan.occurrences == (
        datetime(2026, 6, 20, 10, 0, tzinfo=UTC),
        datetime(2026, 6, 20, 11, 0, tzinfo=UTC),
        datetime(2026, 6, 20, 12, 0, tzinfo=UTC),
    )
    assert plan.next_run_at == datetime(2026, 6, 20, 13, 0, tzinfo=UTC)


def test_start_window_advances_without_execution() -> None:
    scheduled = datetime(2026, 6, 20, 10, 0, tzinfo=UTC)
    start_at = datetime(2026, 6, 20, 12, 0, tzinfo=UTC)

    plan = plan_due_occurrences(
        policy="run_once",
        scheduled_for=scheduled,
        evaluated_at=start_at,
        start_at=start_at,
        end_at=None,
        limit=10,
        next_occurrence=_next_hour,
    )

    assert plan.occurrences == ()
    assert plan.next_run_at == datetime(2026, 6, 20, 13, 0, tzinfo=UTC)


def test_end_window_stops_schedule() -> None:
    scheduled = datetime(2026, 6, 20, 15, 0, tzinfo=UTC)
    end_at = datetime(2026, 6, 20, 14, 0, tzinfo=UTC)

    plan = plan_due_occurrences(
        policy="run_once",
        scheduled_for=scheduled,
        evaluated_at=scheduled,
        start_at=None,
        end_at=end_at,
        limit=10,
        next_occurrence=_next_hour,
    )

    assert plan.occurrences == ()
    assert plan.next_run_at is None


def test_unknown_policy_is_rejected() -> None:
    with pytest.raises(ValueError, match="unsupported misfire policy"):
        plan_due_occurrences(
            policy="unknown",
            scheduled_for=datetime(2026, 6, 20, 10, 0, tzinfo=UTC),
            evaluated_at=datetime(2026, 6, 20, 10, 0, tzinfo=UTC),
            start_at=None,
            end_at=None,
            limit=10,
            next_occurrence=_next_hour,
        )
