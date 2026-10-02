from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

from app.services.workspace_cleanup import (
    AttemptWorkspaceFinalizer,
    WorkspaceCleanupService,
    WorkspaceRetentionPolicy,
    WorkspaceRetentionState,
    WorkspaceTerminalOutcome,
)


def build_finalizer(tmp_path):
    policy = WorkspaceRetentionPolicy(
        completed_after=timedelta(0),
        failed_after=timedelta(0),
        cancelled_after=timedelta(0),
        abandoned_after=timedelta(0),
    )
    return AttemptWorkspaceFinalizer(WorkspaceCleanupService(tmp_path, policy))


def create_workspace(tmp_path, item):
    target = tmp_path / str(item.organization_id) / str(item.execution_id) / str(item.attempt_number)
    target.mkdir(parents=True)
    (target / "payload.tmp").write_text("temporary", encoding="utf-8")
    return target


def test_all_terminal_paths_remove_only_attempt_workspace(tmp_path):
    expected = {
        WorkspaceTerminalOutcome.SUCCEEDED: WorkspaceRetentionState.COMPLETED,
        WorkspaceTerminalOutcome.FAILED: WorkspaceRetentionState.FAILED,
        WorkspaceTerminalOutcome.CANCELLED: WorkspaceRetentionState.CANCELLED,
        WorkspaceTerminalOutcome.LEASE_LOST: WorkspaceRetentionState.ABANDONED,
    }
    finalizer = build_finalizer(tmp_path)
    finished_at = datetime.now(UTC)

    for outcome, state in expected.items():
        item = SimpleNamespace(
            organization_id=uuid4(),
            execution_id=uuid4(),
            attempt_number=1,
        )
        target = create_workspace(tmp_path, item)

        result = finalizer.finalize(item, outcome, finished_at=finished_at)

        assert result.outcome == outcome
        assert result.state == state
        assert result.warning_code is None
        assert result.cleanup is not None
        assert result.cleanup.removed == 1
        assert not target.exists()


def test_cleanup_failure_does_not_replace_terminal_outcome(tmp_path):
    item = SimpleNamespace(
        organization_id=uuid4(),
        execution_id=uuid4(),
        attempt_number=1,
    )
    target = tmp_path / str(item.organization_id) / str(item.execution_id) / str(item.attempt_number)
    target.parent.mkdir(parents=True)
    target.write_text("not-a-directory", encoding="utf-8")

    result = build_finalizer(tmp_path).finalize(
        item,
        WorkspaceTerminalOutcome.FAILED,
        finished_at=datetime.now(UTC),
    )

    assert result.outcome == WorkspaceTerminalOutcome.FAILED
    assert result.state == WorkspaceRetentionState.FAILED
    assert result.cleanup is None
    assert result.warning_code == "workspace_cleanup_failed"
