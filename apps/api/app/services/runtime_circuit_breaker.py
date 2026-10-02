from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from time import monotonic


@dataclass(frozen=True)
class CircuitBreakerDecision:
    allowed: bool
    state: str
    reason: str
    consecutive_failures: int


@dataclass(frozen=True)
class CircuitBreakerSnapshot:
    state: str
    consecutive_failures: int
    opened_total: int
    rejected_total: int
    last_failure_code: str | None


class RuntimeCircuitBreaker:
    """In-process circuit breaker for bounded worker failure isolation."""

    def __init__(
        self,
        *,
        failure_threshold: int = 3,
        recovery_timeout_seconds: float = 30.0,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        if failure_threshold < 1:
            raise ValueError("failure_threshold must be greater than zero")
        if recovery_timeout_seconds <= 0:
            raise ValueError("recovery_timeout_seconds must be greater than zero")
        if not callable(clock):
            raise ValueError("clock is required")
        self.failure_threshold = failure_threshold
        self.recovery_timeout_seconds = recovery_timeout_seconds
        self._clock = clock
        self._state = "closed"
        self._consecutive_failures = 0
        self._opened_at: float | None = None
        self._opened_total = 0
        self._rejected_total = 0
        self._last_failure_code: str | None = None
        self._probe_active = False

    def before_call(self) -> CircuitBreakerDecision:
        if self._state == "open":
            opened_at = self._opened_at
            if opened_at is None:
                opened_at = self._clock()
                self._opened_at = opened_at
            if self._clock() - opened_at >= self.recovery_timeout_seconds:
                self._state = "half_open"
                self._probe_active = True
                return self._decision(True, "recovery_probe")
            self._rejected_total += 1
            return self._decision(False, "circuit_open")
        if self._state == "half_open" and self._probe_active:
            self._rejected_total += 1
            return self._decision(False, "probe_in_progress")
        return self._decision(True, "circuit_closed")

    def record_success(self) -> None:
        self._state = "closed"
        self._consecutive_failures = 0
        self._opened_at = None
        self._last_failure_code = None
        self._probe_active = False

    def record_failure(self, error_code: str | None = None) -> None:
        self._last_failure_code = error_code
        self._probe_active = False
        if self._state == "half_open":
            self._open()
            return
        self._consecutive_failures += 1
        if self._consecutive_failures >= self.failure_threshold:
            self._open()

    def snapshot(self) -> CircuitBreakerSnapshot:
        return CircuitBreakerSnapshot(
            state=self._state,
            consecutive_failures=self._consecutive_failures,
            opened_total=self._opened_total,
            rejected_total=self._rejected_total,
            last_failure_code=self._last_failure_code,
        )

    def _open(self) -> None:
        self._state = "open"
        self._opened_at = self._clock()
        self._opened_total += 1
        self._probe_active = False

    def _decision(self, allowed: bool, reason: str) -> CircuitBreakerDecision:
        return CircuitBreakerDecision(
            allowed=allowed,
            state=self._state,
            reason=reason,
            consecutive_failures=self._consecutive_failures,
        )
