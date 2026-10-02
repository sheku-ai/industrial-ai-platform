from uuid import uuid4

from app.services.runtime_worker_daemon import RuntimeWorkerDaemon


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


def test_idle_cycle_commits_and_closes_session():
    session = SessionStub()
    daemon = RuntimeWorkerDaemon(
        worker_id="worker-1",
        session_factory=lambda: session,
        worker_factory=lambda current_session: WorkerStub(),
    )

    result = daemon.run_cycle(uuid4())

    assert result.outcome == "idle"
    assert session.committed is True
    assert session.closed is True
    assert daemon.health().idle_total == 1


def test_stop_request_prevents_new_cycle():
    session = SessionStub()
    daemon = RuntimeWorkerDaemon(
        worker_id="worker-1",
        session_factory=lambda: session,
        worker_factory=lambda current_session: WorkerStub(),
    )

    daemon.request_stop()
    result = daemon.run_cycle(uuid4())

    assert result.outcome == "stopped"
    assert daemon.health().ready is False
    assert session.committed is False
