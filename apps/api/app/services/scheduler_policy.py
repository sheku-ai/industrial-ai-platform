from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(frozen=True)
class DuePlan:
    occurrences: tuple[datetime, ...]
    next_run_at: datetime | None


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def in_window(
    occurrence: datetime,
    *,
    start_at: datetime | None,
    end_at: datetime | None,
) -> bool:
    occurrence = as_utc(occurrence)
    if start_at is not None and occurrence < as_utc(start_at):
        return False
    return not (end_at is not None and occurrence > as_utc(end_at))


def plan_due_occurrences(
    *,
    policy: str,
    scheduled_for: datetime,
    evaluated_at: datetime,
    start_at: datetime | None,
    end_at: datetime | None,
    limit: int,
    next_occurrence: Callable[[datetime], datetime | None],
) -> DuePlan:
    now = as_utc(evaluated_at)
    scheduled = as_utc(scheduled_for)

    if end_at is not None and scheduled > as_utc(end_at):
        return DuePlan((), None)

    if start_at is not None and scheduled < as_utc(start_at):
        return DuePlan((), next_occurrence(as_utc(start_at)))

    if policy == "skip":
        if scheduled < now:
            return DuePlan((), next_occurrence(now))
        return DuePlan((scheduled,), next_occurrence(scheduled))

    if policy == "run_once":
        return DuePlan((scheduled,), next_occurrence(now))

    if policy == "catch_up_bounded":
        occurrences: list[datetime] = []
        cursor: datetime | None = scheduled
        while cursor is not None and cursor <= now and len(occurrences) < max(1, limit):
            if in_window(cursor, start_at=start_at, end_at=end_at):
                occurrences.append(cursor)
            next_cursor = next_occurrence(cursor)
            if next_cursor is None or next_cursor <= cursor:
                cursor = None
                break
            cursor = next_cursor
        return DuePlan(tuple(occurrences), cursor)

    raise ValueError(f"unsupported misfire policy: {policy}")
