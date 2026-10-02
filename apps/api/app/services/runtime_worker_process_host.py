from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
from signal import SIGINT, SIGTERM, signal
from uuid import UUID

from app.services.runtime_worker_daemon import RuntimeWorkerDaemon
from app.services.runtime_worker_runner import RuntimeWorkerRunner, RuntimeWorkerRunnerResult


class RuntimeWorkerProcessHost:
    """OS-host boundary for signal registration and daemon execution."""

    def __init__(
        self,
        daemon: RuntimeWorkerDaemon,
        runner: RuntimeWorkerRunner,
        *,
        signal_registrar: Callable[[int, Callable], object] = signal,
    ) -> None:
        if runner.daemon is not daemon:
            raise ValueError("runner must reference the supplied daemon")
        if not callable(signal_registrar):
            raise ValueError("signal_registrar is required")
        self.daemon = daemon
        self.runner = runner
        self.signal_registrar = signal_registrar
        self._signals_registered = False

    def register_shutdown_signals(self) -> None:
        if self._signals_registered:
            return
        self.signal_registrar(SIGINT, self._handle_stop_signal)
        self.signal_registrar(SIGTERM, self._handle_stop_signal)
        self._signals_registered = True

    def run(
        self,
        organization_id: UUID,
        *,
        execution_type: str | None = None,
        max_cycles: int | None = None,
        register_signals: bool = True,
    ) -> RuntimeWorkerRunnerResult:
        if register_signals:
            self.register_shutdown_signals()
        return self.runner.run(
            organization_id,
            execution_type=execution_type,
            max_cycles=max_cycles,
        )

    def health_payload(self) -> dict[str, object]:
        return asdict(self.daemon.health())

    def _handle_stop_signal(self, signum, frame) -> None:
        self.daemon.request_stop()
