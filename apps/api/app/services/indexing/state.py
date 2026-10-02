"""Indexing state transition helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from app.services.indexing.contracts import IndexingExecutionResult, IndexingJobStatus


@dataclass(frozen=True)
class IndexingStateTransition:
    """Persistable indexing job transition."""

    indexing_job_id: UUID
    status: IndexingJobStatus
    indexed_chunk_count: int = 0
    failed_chunk_count: int = 0
    metrics: dict[str, Any] = field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class DeterministicIndexingStateBuilder:
    """Builds deterministic transitions for documents.indexing_jobs."""

    def mark_running(self, indexing_job_id: UUID) -> IndexingStateTransition:
        return IndexingStateTransition(
            indexing_job_id=indexing_job_id,
            status=IndexingJobStatus.RUNNING,
            started_at=datetime.now(UTC),
        )

    def from_result(self, result: IndexingExecutionResult) -> IndexingStateTransition:
        return IndexingStateTransition(
            indexing_job_id=result.indexing_job_id,
            status=result.status,
            indexed_chunk_count=result.indexed_chunk_count,
            failed_chunk_count=result.failed_chunk_count,
            metrics=result.metrics,
            error_code=result.error_code,
            error_message=result.error_message,
            finished_at=result.finished_at or datetime.now(UTC),
        )
