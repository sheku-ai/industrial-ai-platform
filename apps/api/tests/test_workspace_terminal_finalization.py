from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from app.services.checkpoint_runtime_worker import CheckpointRuntimeWorker
from app.services.runtime_lease import RuntimeLeaseLost
from app.services.runtime_worker import RuntimeAdapterRegistry, RuntimeAdapterResult
from app.services.workspace_cleanup import (
    AttemptWorkspaceFinalizer,
    WorkspaceCleanupService,
    WorkspaceRetentionPolicy,
    WorkspaceRetentionState,
    WorkspaceTerminalOutcome,
)


def _item():
    return SimpleNamespace(
        organization_id=uuid4(),
        execution_id=uuid4(),
        attempt_number=1,
    )


def test_cancelled_retention_is_distinct_from_failure(tmp_path: Path):
    policy = WorkspaceRetentionPolicy(
        failed_after=timedelta(days=2),
        cancelled_after=timedelta(minutes=15),
    )

    assert policy.retention_for(WorkspaceRetentionState.CANCELLED) == timedelta(minutes=15)
    assert policy.retention_for(WorkspaceRetentionState.FAILED) == timedelta(days=2)


def test_finalizer_maps_terminal_outcomes_to_retention_states(tmp_path: Path):
    finalizer = AttemptWorkspaceFinalizer(WorkspaceCleanupService(tmp_path, WorkspaceRetentionPolicy()))
    item = _item()
    now = datetime.now(UTC)

    assert (
        finalizer.finalize(item, WorkspaceTerminalOutcome.SUCCEEDED, finished_at=now).state
        == WorkspaceRetentionState.COMPLETED
    )
    assert (
        finalizer.finalize(item, WorkspaceTerminalOutcome.FAILED, finished_at=now).state
        == WorkspaceRetentionState.FAILED
    )
    assert (
        finalizer.finalize(item, WorkspaceTerminalOutcome.CANCELLED, finished_at=now).state
        == WorkspaceRetentionState.CANCELLED
    )
    assert (
        finalizer.finalize(item, WorkspaceTerminalOutcome.LEASE_LOST, finished_at=now).state
        == WorkspaceRetentionState.ABANDONED
    )


def test_finalizer_reports_cleanup_warning_without_raising():
    class BrokenCleanup:
        def cleanup(self, *args, **kwargs):
            raise OSError("filesystem unavailable")

    result = AttemptWorkspaceFinalizer(BrokenCleanup()).finalize(
        _item(),
        WorkspaceTerminalOutcome.FAILED,
    )

    assert result.cleanup is None
    assert result.warning_code == "workspace_cleanup_failed"
    assert result.state == WorkspaceRetentionState.FAILED


def test_zero_retention_removes_terminal_workspace_immediately(tmp_path: Path):
    item = _item()
    target = tmp_path / str(item.organization_id) / str(item.execution_id) / "1"
    target.mkdir(parents=True)
    (target / "temporary.bin").write_bytes(b"temporary")
    finalizer = AttemptWorkspaceFinalizer(
        WorkspaceCleanupService(
            tmp_path,
            WorkspaceRetentionPolicy(completed_after=timedelta(0)),
        )
    )

    result = finalizer.finalize(item, WorkspaceTerminalOutcome.SUCCEEDED)

    assert result.cleanup is not None
    assert result.cleanup.removed == 1
    assert not target.exists()


class _FinalizerSpy:
    def __init__(self):
        self.calls = []

    def finalize(self, item, outcome):
        self.calls.append((item.execution_id, outcome))
        return SimpleNamespace(warning_code=None)


class _Heartbeat:
    def checkpoint(self):
        return None


class _WorkerForFinalization(CheckpointRuntimeWorker):
    def __init__(self, adapter, finalizer):
        registry = RuntimeAdapterRegistry()
        registry.register(adapter)
        super().__init__(
            lambda: None,
            registry,
            worker_id="worker-1",
            workspace_finalizer=finalizer,
            heartbeat_factory=lambda *args, **kwargs: _Heartbeat(),
        )
        self.item = SimpleNamespace(
            organization_id=uuid4(),
            execution_id=uuid4(),
            execution_type=adapter.execution_type,
            subject_type="generic.subject",
            subject_id=uuid4(),
            attempt_id=uuid4(),
            attempt_number=1,
            lease_token=uuid4(),
            input_payload={},
            policy_snapshot={},
        )
        self.transitions = []

    def _claim(self, organization_id, execution_type, execution_id=None):
        return self.item

    def _start(self, item):
        self.transitions.append("start")

    def _succeed(self, item, metrics):
        self.transitions.append("succeed")

    def _fail(self, item, error_code, error_message):
        self.transitions.append("fail")

    def _cancel(self, item):
        self.transitions.append("cancel")


class _SuccessAdapter:
    execution_type = "generic.operation"

    def execute(self, item, heartbeat):
        return RuntimeAdapterResult(metrics={"ok": True})


class _LeaseLostAdapter:
    execution_type = "generic.lease-lost"

    def execute(self, item, heartbeat):
        raise RuntimeLeaseLost("lost")


def test_worker_finalizes_success_without_changing_terminal_transition():
    finalizer = _FinalizerSpy()
    worker = _WorkerForFinalization(_SuccessAdapter(), finalizer)

    worker.run_once(worker.item.organization_id)

    assert worker.transitions == ["start", "succeed"]
    assert finalizer.calls == [(worker.item.execution_id, WorkspaceTerminalOutcome.SUCCEEDED)]


def test_worker_finalizes_lease_loss_as_abandoned_without_fail_transition():
    finalizer = _FinalizerSpy()
    worker = _WorkerForFinalization(_LeaseLostAdapter(), finalizer)

    worker.run_once(worker.item.organization_id)

    assert worker.transitions == ["start"]
    assert finalizer.calls == [(worker.item.execution_id, WorkspaceTerminalOutcome.LEASE_LOST)]
