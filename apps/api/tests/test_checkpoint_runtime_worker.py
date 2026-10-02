from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services.checkpoint_runtime_worker import (
    CheckpointRuntimeWorker,
    SessionRuntimeHeartbeat,
)
from app.services.runtime_cancellation import RuntimeCancellationRequested
from app.services.runtime_lease import RuntimeLeaseLost
from app.services.runtime_lifecycle import InvalidLeaseError
from app.services.runtime_worker import RuntimeAdapterRegistry, RuntimeAdapterResult
from tests.runtime_faults import FaultInjectingHeartbeatFactory, HeartbeatFaultPlan


class Session:
    def __init__(self, calls):
        self.calls = calls

    def scalar(self, statement):
        self.calls.append("check_cancel")
        return None

    def commit(self):
        self.calls.append("commit")

    def rollback(self):
        self.calls.append("rollback")

    def close(self):
        self.calls.append("close")


class Lifecycle:
    claimed = None
    heartbeat_error = None

    def __init__(self, session):
        self.session = session

    def claim(self, **kwargs):
        self.session.calls.append("claim")
        return self.claimed

    def start(self, *args, **kwargs):
        self.session.calls.append("start")

    def succeed(self, *args, **kwargs):
        self.session.calls.append("succeed")

    def fail(self, *args, **kwargs):
        self.session.calls.append("fail")

    def complete_cancel(self, *args, **kwargs):
        self.session.calls.append("complete_cancel")

    def heartbeat(self, *args, **kwargs):
        self.session.calls.append("heartbeat")
        if self.heartbeat_error is not None:
            raise self.heartbeat_error
        return SimpleNamespace()


class Adapter:
    execution_type = "document.ingestion"

    def __init__(self, calls):
        self.calls = calls

    def execute(self, item, heartbeat):
        self.calls.append("execute")
        heartbeat.pulse()
        return RuntimeAdapterResult(metrics={"ok": True})


class WorkspaceFinalizer:
    def __init__(self, calls):
        self.calls = calls

    def finalize(self, item, outcome):
        self.calls.append(f"workspace:{outcome.value}")


def _claimed(organization_id):
    return (
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


def _worker_with_fault(calls, plan):
    registry = RuntimeAdapterRegistry()
    registry.register(Adapter(calls))
    factory = FaultInjectingHeartbeatFactory(SessionRuntimeHeartbeat, plan)
    return CheckpointRuntimeWorker(
        lambda: Session(calls),
        registry,
        worker_id="worker-1",
        workspace_finalizer=WorkspaceFinalizer(calls),
        heartbeat_factory=factory,
    )


def _patch_lifecycle(monkeypatch):
    monkeypatch.setattr(
        "app.services.checkpoint_runtime_worker.RuntimeLifecycleService",
        Lifecycle,
    )
    monkeypatch.setattr(
        "app.services.checkpoint_runtime_worker.ContinuableRuntimeLifecycleService",
        Lifecycle,
    )


def test_worker_commits_each_checkpoint_and_closes_sessions(monkeypatch):
    calls = []
    organization_id = uuid4()
    Lifecycle.claimed = _claimed(organization_id)
    Lifecycle.heartbeat_error = None
    execution_id = Lifecycle.claimed[0].id
    _patch_lifecycle(monkeypatch)

    registry = RuntimeAdapterRegistry()
    registry.register(Adapter(calls))
    worker = CheckpointRuntimeWorker(lambda: Session(calls), registry, worker_id="worker-1")

    item = worker.run_once(organization_id, execution_type="document.ingestion")

    assert item.execution_id == execution_id
    assert calls == [
        "claim", "commit", "close",
        "start", "commit", "close",
        "execute",
        "heartbeat", "commit", "close",
        "check_cancel", "close",
        "heartbeat", "commit", "close",
        "succeed", "commit", "close",
    ]


def test_worker_uses_failure_checkpoint(monkeypatch):
    calls = []
    organization_id = uuid4()
    Lifecycle.claimed = _claimed(organization_id)
    Lifecycle.heartbeat_error = None
    _patch_lifecycle(monkeypatch)

    class FailedAdapter(Adapter):
        def execute(self, item, heartbeat):
            calls.append("execute")
            raise RuntimeError("failed")

    registry = RuntimeAdapterRegistry()
    registry.register(FailedAdapter(calls))
    worker = CheckpointRuntimeWorker(lambda: Session(calls), registry, worker_id="worker-1")

    worker.run_once(organization_id)

    assert "fail" in calls
    assert "succeed" not in calls
    assert calls.count("rollback") == 0


def test_heartbeat_translates_invalid_lease_to_typed_lease_loss(monkeypatch):
    calls = []
    organization_id = uuid4()
    Lifecycle.claimed = _claimed(organization_id)
    Lifecycle.heartbeat_error = InvalidLeaseError("expired")
    _patch_lifecycle(monkeypatch)

    class LeaseCheckingAdapter(Adapter):
        def execute(self, item, heartbeat):
            calls.append("execute")
            heartbeat.pulse()
            raise AssertionError("unreachable")

    registry = RuntimeAdapterRegistry()
    registry.register(LeaseCheckingAdapter(calls))
    worker = CheckpointRuntimeWorker(lambda: Session(calls), registry, worker_id="worker-1")

    worker.run_once(organization_id)

    assert "rollback" in calls
    assert "fail" not in calls
    assert "succeed" not in calls


def test_worker_does_not_succeed_when_final_checkpoint_loses_lease(monkeypatch):
    calls = []
    organization_id = uuid4()
    Lifecycle.claimed = _claimed(organization_id)
    _patch_lifecycle(monkeypatch)

    heartbeat_calls = 0

    def heartbeat(self, *args, **kwargs):
        nonlocal heartbeat_calls
        heartbeat_calls += 1
        self.session.calls.append("heartbeat")
        if heartbeat_calls == 2:
            raise InvalidLeaseError("expired before success")
        return SimpleNamespace()

    monkeypatch.setattr(Lifecycle, "heartbeat", heartbeat)
    Lifecycle.heartbeat_error = None

    registry = RuntimeAdapterRegistry()
    registry.register(Adapter(calls))
    worker = CheckpointRuntimeWorker(lambda: Session(calls), registry, worker_id="worker-1")

    worker.run_once(organization_id)

    assert heartbeat_calls == 2
    assert "succeed" not in calls
    assert "fail" not in calls


@pytest.mark.parametrize("operation", ["pulse", "checkpoint"])
def test_deterministic_cancellation_never_succeeds_or_fails(monkeypatch, operation):
    calls = []
    organization_id = uuid4()
    Lifecycle.claimed = _claimed(organization_id)
    Lifecycle.heartbeat_error = None
    _patch_lifecycle(monkeypatch)

    worker = _worker_with_fault(
        calls,
        HeartbeatFaultPlan(
            operation=operation,
            occurrence=1,
            exception_factory=lambda: RuntimeCancellationRequested("injected cancellation"),
        ),
    )

    worker.run_once(organization_id)

    assert calls.count("complete_cancel") == 1
    assert "succeed" not in calls
    assert "fail" not in calls
    assert "workspace:cancelled" in calls


@pytest.mark.parametrize("operation", ["pulse", "checkpoint"])
def test_deterministic_lease_loss_writes_no_terminal_transition(monkeypatch, operation):
    calls = []
    organization_id = uuid4()
    Lifecycle.claimed = _claimed(organization_id)
    Lifecycle.heartbeat_error = None
    _patch_lifecycle(monkeypatch)

    worker = _worker_with_fault(
        calls,
        HeartbeatFaultPlan(
            operation=operation,
            occurrence=1,
            exception_factory=lambda: RuntimeLeaseLost("injected lease loss"),
        ),
    )

    worker.run_once(organization_id)

    assert "succeed" not in calls
    assert "fail" not in calls
    assert "complete_cancel" not in calls
    assert "workspace:lease_lost" in calls


def test_runtime_lease_lost_has_stable_machine_code():
    assert RuntimeLeaseLost.code == "runtime_lease_lost"
