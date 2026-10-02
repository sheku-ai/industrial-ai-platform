from uuid import uuid4

from app.services.runtime_worker_host_factory import build_runtime_worker_process_host


class SessionStub:
    def __init__(self):
        self.committed = False
        self.closed = False

    def commit(self):
        self.committed = True

    def rollback(self):
        pass

    def close(self):
        self.closed = True


class WorkerStub:
    worker_id = "worker-1"

    def run_once(self, organization_id, *, execution_type=None):
        return None


def test_factory_wires_daemon_runner_and_process_host():
    session = SessionStub()
    sleeps = []
    registrations = []

    host = build_runtime_worker_process_host(
        worker_id="worker-1",
        session_factory=lambda: session,
        worker_factory=lambda current_session: WorkerStub(),
        poll_interval_seconds=0.25,
        sleeper=sleeps.append,
        signal_registrar=lambda signum, handler: registrations.append((signum, handler)),
    )

    result = host.run(uuid4(), max_cycles=1)
    health = host.health_payload()

    assert result.cycles == 1
    assert result.idle == 1
    assert session.committed is True
    assert session.closed is True
    assert sleeps == [0.25]
    assert len(registrations) == 2
    assert health["worker_id"] == "worker-1"
    assert health["cycles_total"] == 1
    assert health["idle_total"] == 1
