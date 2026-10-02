from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from app.services.ingestion_contracts import IngestionContractError
from app.services.workspace_cleanup import (
    WorkspaceCleanupCandidate,
    WorkspaceCleanupService,
    WorkspaceRetentionPolicy,
    WorkspaceRetentionState,
)


def candidate(
    organization_id,
    execution_id,
    *,
    attempt_number: int = 1,
    state: WorkspaceRetentionState = WorkspaceRetentionState.COMPLETED,
    finished_at: datetime,
) -> WorkspaceCleanupCandidate:
    return WorkspaceCleanupCandidate(
        organization_id=organization_id,
        execution_id=execution_id,
        attempt_number=attempt_number,
        state=state,
        finished_at=finished_at,
    )


def test_removes_expired_completed_workspace_and_prunes_empty_parents(tmp_path: Path) -> None:
    organization_id = uuid4()
    execution_id = uuid4()
    target = tmp_path / str(organization_id) / str(execution_id) / "1"
    target.mkdir(parents=True)
    (target / "source.txt").write_text("content", encoding="utf-8")
    now = datetime.now(UTC)

    result = WorkspaceCleanupService(
        tmp_path,
        WorkspaceRetentionPolicy(completed_after=timedelta(minutes=5)),
    ).cleanup(
        [candidate(organization_id, execution_id, finished_at=now - timedelta(minutes=6))],
        now=now,
    )

    assert result.removed == 1
    assert not target.exists()
    assert not (tmp_path / str(organization_id)).exists()


def test_retains_workspace_inside_retention_window(tmp_path: Path) -> None:
    organization_id = uuid4()
    execution_id = uuid4()
    target = tmp_path / str(organization_id) / str(execution_id) / "1"
    target.mkdir(parents=True)
    now = datetime.now(UTC)

    result = WorkspaceCleanupService(
        tmp_path,
        WorkspaceRetentionPolicy(completed_after=timedelta(hours=1)),
    ).cleanup(
        [candidate(organization_id, execution_id, finished_at=now - timedelta(minutes=30))],
        now=now,
    )

    assert result.retained == 1
    assert target.exists()


def test_uses_state_specific_retention(tmp_path: Path) -> None:
    organization_id = uuid4()
    completed_execution = uuid4()
    failed_execution = uuid4()
    completed = tmp_path / str(organization_id) / str(completed_execution) / "1"
    failed = tmp_path / str(organization_id) / str(failed_execution) / "1"
    completed.mkdir(parents=True)
    failed.mkdir(parents=True)
    now = datetime.now(UTC)
    policy = WorkspaceRetentionPolicy(
        completed_after=timedelta(hours=1),
        failed_after=timedelta(days=1),
    )

    result = WorkspaceCleanupService(tmp_path, policy).cleanup(
        [
            candidate(
                organization_id,
                completed_execution,
                state=WorkspaceRetentionState.COMPLETED,
                finished_at=now - timedelta(hours=2),
            ),
            candidate(
                organization_id,
                failed_execution,
                state=WorkspaceRetentionState.FAILED,
                finished_at=now - timedelta(hours=2),
            ),
        ],
        now=now,
    )

    assert result.removed == 1
    assert result.retained == 1
    assert not completed.exists()
    assert failed.exists()


def test_reports_missing_expired_workspace(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    result = WorkspaceCleanupService(tmp_path, WorkspaceRetentionPolicy()).cleanup(
        [candidate(uuid4(), uuid4(), finished_at=now - timedelta(days=2))],
        now=now,
    )
    assert result.missing == 1


def test_rejects_naive_times(tmp_path: Path) -> None:
    with pytest.raises(IngestionContractError, match="timezone-aware"):
        WorkspaceCleanupCandidate(
            organization_id=uuid4(),
            execution_id=uuid4(),
            attempt_number=1,
            state=WorkspaceRetentionState.COMPLETED,
            finished_at=datetime.now(),
        )

    with pytest.raises(IngestionContractError, match="reference time"):
        WorkspaceCleanupService(tmp_path, WorkspaceRetentionPolicy()).cleanup(
            [], now=datetime.now()
        )


def test_rejects_negative_retention() -> None:
    with pytest.raises(IngestionContractError, match="cannot be negative"):
        WorkspaceRetentionPolicy(completed_after=timedelta(seconds=-1))


def test_rejects_file_instead_of_workspace_directory(tmp_path: Path) -> None:
    organization_id = uuid4()
    execution_id = uuid4()
    target = tmp_path / str(organization_id) / str(execution_id) / "1"
    target.parent.mkdir(parents=True)
    target.write_text("not a directory", encoding="utf-8")
    now = datetime.now(UTC)

    with pytest.raises(IngestionContractError, match="not a directory"):
        WorkspaceCleanupService(tmp_path, WorkspaceRetentionPolicy()).cleanup(
            [candidate(organization_id, execution_id, finished_at=now - timedelta(days=2))],
            now=now,
        )
