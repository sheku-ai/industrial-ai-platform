from types import SimpleNamespace
from uuid import uuid4

from app.services.checkpoint_runtime_worker import CheckpointRuntimeWorker
from app.services.document_ingestion_runtime_adapter import HeartbeatIngestionControl
from app.services.runtime_cancellation import RuntimeCancellationRequested
from app.services.runtime_worker import RuntimeAdapterRegistry


class ControlHeartbeat:
    def __init__(self):
        self.checked = 0

    def pulse(self):
        return None

    def is_cancellation_requested(self):
        return True

    def raise_if_cancellation_requested(self):
        self.checked += 1
        raise RuntimeCancellationRequested("requested")


class Session:
    def __init__(self, calls):
        self.calls = calls

    def commit(self):
        self.calls.append("commit")

    def rollback(self):
        self.calls.append("rollback")

    def close(self):
        self.calls.append("close")


class Lifecycle:
    claimed = None

    def __init__(self, session):
        self.session = session

    def claim(self, **kwargs):
        self.session.calls.append("claim")
        return self.claimed

    def start(self, *args, **kwargs):
        self.session.calls.append("start")

    def complete_cancel(self, *args, **kwargs):
        self.session.calls.append("cancel")


class CancellingAdapter:
    execution_type = "document.ingestion"

    def execute(self, item, heartbeat):
        raise RuntimeCancellationRequested("requested")


def test_ingestion_control_delegates_cancellation_signal():
    heartbeat = ControlHeartbeat()
    control = HeartbeatIngestionControl(heartbeat)

    assert control.is_cancellation_requested() is True
    try:
        control.raise_if_cancellation_requested()
    except RuntimeCancellationRequested:
        pass
    else:
        raise AssertionError("cancellation signal was not propagated")
    assert heartbeat.checked == 1


def test_checkpoint_worker_completes_cancellation(monkeypatch):
    calls = []
    organization_id = uuid4()
    Lifecycle.claimed = (
        SimpleNamespace(
            organization_id=organization_id,
            id=uuid4(),
            execution_type="document.ingestion",
            subject_type="document_version",
            subject_id=uuid4(),
            input_payload={},
            policy_snapshot={},
        ),
        SimpleNamespace(id=uuid4(), attempt_number=1, lease_token=uuid4()),
    )
    monkeypatch.setattr(
        "app.services.checkpoint_runtime_worker.RuntimeLifecycleService",
        Lifecycle,
    )
    monkeypatch.setattr(
        "app.services.checkpoint_runtime_worker.ContinuableRuntimeLifecycleService",
        Lifecycle,
    )

    registry = RuntimeAdapterRegistry()
    registry.register(CancellingAdapter())
    worker = CheckpointRuntimeWorker(lambda: Session(calls), registry, worker_id="worker-1")

    worker.run_once(organization_id)

    assert "cancel" in calls
    assert "rollback" not in calls
