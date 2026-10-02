from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from time import sleep
from uuid import UUID

from app.services.runtime_worker_daemon import RuntimeWorkerDaemon


@dataclass(frozen=True)
class RuntimeWorkerRunnerResult:
    cycles: int
    processed: int
    idle: int
    stopped: bool


class RuntimeWorkerRunner:
    """Deployment-neutral polling loop around RuntimeWorkerDaemon."""

    def __init__(
        self,
        daemon: RuntimeWorkerDaemon,
        *,
        poll_interval_seconds: float = 1.0,
        sleeper: Callable[[float], None] = sleep,
    ) -> None:
        if poll_interval_seconds < 0:
            raise ValueError("poll_interval_seconds cannot be negative")
        if not callable(sleeper):
            raise ValueError("sleeper is required")
        self.daemon = daemon
        self.poll_interval_seconds = poll_interval_seconds
        self.sleeper = sleeper

    def run(
        self,
        organization_id: UUID,
        *,
        execution_type: str | None = None,
        max_cycles: int | None = None,
    ) -> RuntimeWorkerRunnerResult:
        if max_cycles is not None and max_cycles <= 0:
            raise ValueError("max_cycles must be greater than zero")

        cycles = 0
        processed = 0
        idle = 0

        while True:
            if self.daemon.health().stop_requested:
                return RuntimeWorkerRunnerResult(cycles, processed, idle, True)
            if max_cycles is not None and cycles >= max_cycles:
                return RuntimeWorkerRunnerResult(cycles, processed, idle, False)

            result = self.daemon.run_cycle(
                organization_id,
                execution_type=execution_type,
            )
            if result.outcome == "stopped":
                return RuntimeWorkerRunnerResult(cycles, processed, idle, True)

            cycles += 1
            if result.claimed:
                processed += 1
            else:
                idle += 1
                if self.poll_interval_seconds > 0:
                    self.sleeper(self.poll_interval_seconds)
