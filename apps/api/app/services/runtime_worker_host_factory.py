from __future__ import annotations

from collections.abc import Callable

from app.services.runtime_worker_daemon import RuntimeWorkerDaemon
from app.services.runtime_worker_process_host import RuntimeWorkerProcessHost
from app.services.runtime_worker_runner import RuntimeWorkerRunner


def build_runtime_worker_process_host(
    *,
    worker_id: str,
    session_factory: Callable[[], object],
    worker_factory: Callable[[object], object],
    poll_interval_seconds: float = 1.0,
    sleeper=None,
    signal_registrar=None,
) -> RuntimeWorkerProcessHost:
    daemon = RuntimeWorkerDaemon(
        worker_id=worker_id,
        session_factory=session_factory,
        worker_factory=worker_factory,
    )

    runner_kwargs = {"poll_interval_seconds": poll_interval_seconds}
    if sleeper is not None:
        runner_kwargs["sleeper"] = sleeper
    runner = RuntimeWorkerRunner(daemon, **runner_kwargs)

    host_kwargs = {}
    if signal_registrar is not None:
        host_kwargs["signal_registrar"] = signal_registrar
    return RuntimeWorkerProcessHost(daemon, runner, **host_kwargs)
