from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from shutil import rmtree
from uuid import UUID

from app.services.ingestion_contracts import IngestionContractError


class WorkspaceRetentionState(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    ABANDONED = "abandoned"


class WorkspaceTerminalOutcome(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    LEASE_LOST = "lease_lost"


@dataclass(frozen=True)
class WorkspaceRetentionPolicy:
    completed_after: timedelta = timedelta(hours=1)
    failed_after: timedelta = timedelta(days=1)
    cancelled_after: timedelta = timedelta(hours=1)
    abandoned_after: timedelta = timedelta(days=7)

    def __post_init__(self) -> None:
        for name, value in (
            ("completed_after", self.completed_after),
            ("failed_after", self.failed_after),
            ("cancelled_after", self.cancelled_after),
            ("abandoned_after", self.abandoned_after),
        ):
            if value.total_seconds() < 0:
                raise IngestionContractError(f"{name} cannot be negative")

    def retention_for(self, state: WorkspaceRetentionState) -> timedelta:
        if state == WorkspaceRetentionState.COMPLETED:
            return self.completed_after
        if state == WorkspaceRetentionState.FAILED:
            return self.failed_after
        if state == WorkspaceRetentionState.CANCELLED:
            return self.cancelled_after
        if state == WorkspaceRetentionState.ABANDONED:
            return self.abandoned_after
        raise IngestionContractError(f"unsupported workspace state: {state}")


@dataclass(frozen=True)
class WorkspaceCleanupCandidate:
    organization_id: UUID
    execution_id: UUID
    attempt_number: int
    state: WorkspaceRetentionState
    finished_at: datetime

    def __post_init__(self) -> None:
        if self.attempt_number <= 0:
            raise IngestionContractError("attempt_number must be positive")
        if self.finished_at.tzinfo is None:
            raise IngestionContractError("finished_at must be timezone-aware")


@dataclass(frozen=True)
class WorkspaceCleanupResult:
    inspected: int
    removed: int
    missing: int
    retained: int


@dataclass(frozen=True)
class WorkspaceFinalizationResult:
    outcome: WorkspaceTerminalOutcome
    state: WorkspaceRetentionState
    cleanup: WorkspaceCleanupResult | None
    warning_code: str | None = None


class WorkspaceCleanupService:
    """Remove expired attempt workspaces without escaping the configured root."""

    def __init__(
        self,
        workspace_root: Path,
        policy: WorkspaceRetentionPolicy,
    ) -> None:
        self._workspace_root = workspace_root.resolve()
        self._policy = policy

    def cleanup(
        self,
        candidates: Iterable[WorkspaceCleanupCandidate],
        *,
        now: datetime | None = None,
    ) -> WorkspaceCleanupResult:
        reference_time = now or datetime.now(UTC)
        if reference_time.tzinfo is None:
            raise IngestionContractError("cleanup reference time must be timezone-aware")

        inspected = 0
        removed = 0
        missing = 0
        retained = 0

        for candidate in candidates:
            inspected += 1
            expires_at = candidate.finished_at + self._policy.retention_for(candidate.state)
            if reference_time < expires_at:
                retained += 1
                continue

            target = self.workspace_path(
                candidate.organization_id,
                candidate.execution_id,
                candidate.attempt_number,
            )
            if not target.exists():
                missing += 1
                continue
            if not target.is_dir():
                raise IngestionContractError("workspace target is not a directory")

            rmtree(target)
            removed += 1
            self._prune_empty_parents(target.parent)

        return WorkspaceCleanupResult(
            inspected=inspected,
            removed=removed,
            missing=missing,
            retained=retained,
        )

    def workspace_path(
        self,
        organization_id: UUID,
        execution_id: UUID,
        attempt_number: int,
    ) -> Path:
        if attempt_number <= 0:
            raise IngestionContractError("attempt_number must be positive")

        target = (self._workspace_root / str(organization_id) / str(execution_id) / str(attempt_number)).resolve()
        if not target.is_relative_to(self._workspace_root):
            raise IngestionContractError("workspace path escapes configured root")
        return target

    def _prune_empty_parents(self, start: Path) -> None:
        current = start
        while current != self._workspace_root:
            if not current.exists() or any(current.iterdir()):
                break
            current.rmdir()
            current = current.parent


class AttemptWorkspaceFinalizer:
    """Apply terminal retention without changing the primary runtime outcome."""

    _STATE_BY_OUTCOME = {
        WorkspaceTerminalOutcome.SUCCEEDED: WorkspaceRetentionState.COMPLETED,
        WorkspaceTerminalOutcome.FAILED: WorkspaceRetentionState.FAILED,
        WorkspaceTerminalOutcome.CANCELLED: WorkspaceRetentionState.CANCELLED,
        WorkspaceTerminalOutcome.LEASE_LOST: WorkspaceRetentionState.ABANDONED,
    }

    def __init__(self, cleanup_service: WorkspaceCleanupService) -> None:
        self._cleanup_service = cleanup_service

    def finalize(
        self,
        item,
        outcome: WorkspaceTerminalOutcome | str,
        *,
        finished_at: datetime | None = None,
    ) -> WorkspaceFinalizationResult:
        canonical_outcome = (
            outcome if isinstance(outcome, WorkspaceTerminalOutcome) else WorkspaceTerminalOutcome(str(outcome))
        )
        state = self._STATE_BY_OUTCOME[canonical_outcome]
        terminal_time = finished_at or datetime.now(UTC)
        try:
            result = self._cleanup_service.cleanup(
                [
                    WorkspaceCleanupCandidate(
                        organization_id=item.organization_id,
                        execution_id=item.execution_id,
                        attempt_number=item.attempt_number,
                        state=state,
                        finished_at=terminal_time,
                    )
                ],
                now=terminal_time,
            )
            return WorkspaceFinalizationResult(
                outcome=canonical_outcome,
                state=state,
                cleanup=result,
            )
        except Exception:
            return WorkspaceFinalizationResult(
                outcome=canonical_outcome,
                state=state,
                cleanup=None,
                warning_code="workspace_cleanup_failed",
            )
