from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from threading import Event

from app.orchestration.base import CancellationBoundary, OrchestrationPolicy

MonotonicClock = Callable[[], float]


class ExecutionTimedOut(TimeoutError):
    """Raised when the execution deadline has expired."""


class ExecutionCancelled(RuntimeError):
    """Raised when cooperative cancellation has been requested."""


class CancellationToken:
    """Thread-safe cooperative cancellation boundary."""

    def __init__(self) -> None:
        self._event = Event()

    def cancel(self) -> None:
        self._event.set()

    def is_cancelled(self) -> bool:
        return self._event.is_set()


@dataclass(frozen=True)
class ExecutionDeadline:
    started_at_monotonic: float
    expires_at_monotonic: float
    timeout_ms: int
    clock: MonotonicClock = time.monotonic

    @classmethod
    def from_policy(
        cls,
        *,
        requested_timeout_ms: int | None,
        policy: OrchestrationPolicy,
        clock: MonotonicClock = time.monotonic,
    ) -> ExecutionDeadline:
        if requested_timeout_ms is not None and requested_timeout_ms < 1:
            raise ValueError("requested timeout must be positive")

        timeout_ms = policy.default_timeout_ms if requested_timeout_ms is None else requested_timeout_ms
        timeout_ms = min(timeout_ms, policy.max_timeout_ms)

        started = clock()
        return cls(
            started_at_monotonic=started,
            expires_at_monotonic=started + (timeout_ms / 1000.0),
            timeout_ms=timeout_ms,
            clock=clock,
        )

    def elapsed_ms(self) -> int:
        return max(0, int((self.clock() - self.started_at_monotonic) * 1000))

    def remaining_ms(self) -> int:
        return max(0, int((self.expires_at_monotonic - self.clock()) * 1000))

    def is_expired(self) -> bool:
        return self.clock() >= self.expires_at_monotonic

    def require_remaining(self, *, minimum_ms: int = 1) -> int:
        remaining = self.remaining_ms()
        if self.is_expired() or remaining < minimum_ms:
            raise ExecutionTimedOut("execution deadline expired")
        return remaining


@dataclass(frozen=True)
class ExecutionControl:
    deadline: ExecutionDeadline
    cancellation: CancellationBoundary

    def checkpoint(self, *, minimum_remaining_ms: int = 1) -> int:
        if self.cancellation.is_cancelled():
            raise ExecutionCancelled("execution cancellation requested")
        return self.deadline.require_remaining(minimum_ms=minimum_remaining_ms)

    def remaining_timeout_ms(self, *, maximum_ms: int | None = None) -> int:
        remaining = self.checkpoint()
        if maximum_ms is None:
            return remaining
        if maximum_ms < 1:
            raise ValueError("maximum_ms must be positive")
        return min(remaining, maximum_ms)
