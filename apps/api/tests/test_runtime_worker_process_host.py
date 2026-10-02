from dataclasses import dataclass
from uuid import uuid4

from app.services.runtime_worker_process_host import RuntimeWorkerProcessHost


@dataclass
class Health:
    worker_id: str = "worker-1"
    live: bool = True
    ready: bool = True
    stop_requested: bool = False
    active: bool = False
    cycles_total: int = 0
    claimed_total: int = 0
    idle_total: int = 0
    failed_cycles_total: int = 0
    last_cycle_started_at: object = None
    last_cycle_finished_at: object = None
    last_error_code: object = None


class DaemonStub:
    def __init__(self):
        self.stop_requests = 0

    def request_stop(self):
        self.stop_requests += 1

    def health(self):
        return Health(stop_requested=self.stop_requests > 0, ready=self.stop_requests == 0)


class RunnerStub:
    def __init__(self, daemon):
        self.daemon = daemon
        self.calls = []

    def run(self, organization_id, *, execution_type=None, max_cycles=None):
        self.calls.append((organization_id, execution_type, max_cycles))
        return {"completed": True}


def test_process_host_registers_signals_once_and_requests_stop():
    daemon = DaemonStub()
    runner = RunnerStub(daemon)
    registrations = []
    host = RuntimeWorkerProcessHost(
        daemon,
        runner,
        signal_registrar=lambda signum, handler: registrations.append((signum, handler)),
    )

    host.register_shutdown_signals()
    host.register_shutdown_signals()

    assert len(registrations) == 2
    registrations[0][1](registrations[0][0], None)
    assert daemon.stop_requests == 1
    assert host.health_payload()["ready"] is False


def test_process_host_runs_with_bounded_options():
    daemon = DaemonStub()
    runner = RunnerStub(daemon)
    host = RuntimeWorkerProcessHost(
        daemon,
        runner,
        signal_registrar=lambda signum, handler: None,
    )
    organization_id = uuid4()

    result = host.run(
        organization_id,
        execution_type="document.ingestion",
        max_cycles=3,
        register_signals=False,
    )

    assert result == {"completed": True}
    assert runner.calls == [(organization_id, "document.ingestion", 3)]
