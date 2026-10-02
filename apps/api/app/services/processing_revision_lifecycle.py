from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.processing import ProcessingRevision

TERMINAL_PROCESSING_REVISION_STATUSES = {"completed", "failed", "cancelled", "abandoned"}


class ProcessingRevisionError(RuntimeError):
    code = "processing_revision_error"


class ProcessingRevisionConflictError(ProcessingRevisionError):
    code = "processing_revision_conflict"


class ProcessingRevisionNotFoundError(ProcessingRevisionError):
    code = "processing_revision_not_found"


class ProcessingRevisionLifecycleService:
    """Own processing-revision creation and terminal state transitions.

    The caller owns commit and rollback. One runtime attempt may own at most one
    revision. Terminal revisions are immutable.
    """

    def __init__(self, session: Session) -> None:
        self.session = session

    @staticmethod
    def _utcnow() -> datetime:
        return datetime.now(UTC)

    def get_for_attempt(
        self,
        organization_id: UUID,
        runtime_execution_id: UUID,
        runtime_attempt_id: UUID,
        *,
        for_update: bool = False,
    ) -> ProcessingRevision | None:
        statement = select(ProcessingRevision).where(
            ProcessingRevision.organization_id == organization_id,
            ProcessingRevision.runtime_execution_id == runtime_execution_id,
            ProcessingRevision.runtime_attempt_id == runtime_attempt_id,
        )
        if for_update:
            statement = statement.with_for_update()
        return self.session.scalar(statement)

    def start(
        self,
        *,
        organization_id: UUID,
        document_record_id: UUID,
        document_version_id: UUID,
        runtime_execution_id: UUID,
        runtime_attempt_id: UUID,
        pipeline_profile_id: UUID | None,
        pipeline_profile_revision: str,
        adapter_key: str,
        adapter_version: str,
        configuration_snapshot: Mapping[str, Any] | None = None,
        source_checksum_sha256: str | None = None,
        started_at: datetime | None = None,
    ) -> ProcessingRevision:
        profile_revision = pipeline_profile_revision.strip()
        canonical_adapter_key = adapter_key.strip()
        canonical_adapter_version = adapter_version.strip()
        if not profile_revision:
            raise ProcessingRevisionConflictError("pipeline_profile_revision is required")
        if not canonical_adapter_key:
            raise ProcessingRevisionConflictError("adapter_key is required")
        if not canonical_adapter_version:
            raise ProcessingRevisionConflictError("adapter_version is required")
        if source_checksum_sha256 is not None and len(source_checksum_sha256) != 64:
            raise ProcessingRevisionConflictError("source checksum must be a SHA-256 hex digest")

        existing = self.get_for_attempt(
            organization_id,
            runtime_execution_id,
            runtime_attempt_id,
            for_update=True,
        )
        if existing is not None:
            self._validate_same_identity(
                existing,
                document_record_id=document_record_id,
                document_version_id=document_version_id,
                pipeline_profile_id=pipeline_profile_id,
                pipeline_profile_revision=profile_revision,
                adapter_key=canonical_adapter_key,
                adapter_version=canonical_adapter_version,
            )
            return existing

        event_time = started_at or self._utcnow()
        if event_time.tzinfo is None:
            raise ProcessingRevisionConflictError("started_at must be timezone-aware")
        revision = ProcessingRevision(
            organization_id=organization_id,
            document_record_id=document_record_id,
            document_version_id=document_version_id,
            runtime_execution_id=runtime_execution_id,
            runtime_attempt_id=runtime_attempt_id,
            pipeline_profile_id=pipeline_profile_id,
            pipeline_profile_revision=profile_revision,
            adapter_key=canonical_adapter_key,
            adapter_version=canonical_adapter_version,
            configuration_snapshot=dict(configuration_snapshot or {}),
            source_checksum_sha256=source_checksum_sha256,
            status="processing",
            started_at=event_time,
            completed_at=None,
            content_unit_count=0,
            chunk_count=0,
            created_at=event_time,
            updated_at=event_time,
        )
        self.session.add(revision)
        self.session.flush()
        return revision

    def complete(
        self,
        *,
        organization_id: UUID,
        runtime_execution_id: UUID,
        runtime_attempt_id: UUID,
        content_unit_count: int,
        chunk_count: int,
        manifest_artifact_id: UUID | None = None,
        completed_at: datetime | None = None,
    ) -> ProcessingRevision:
        return self._finish(
            organization_id=organization_id,
            runtime_execution_id=runtime_execution_id,
            runtime_attempt_id=runtime_attempt_id,
            status="completed",
            content_unit_count=content_unit_count,
            chunk_count=chunk_count,
            manifest_artifact_id=manifest_artifact_id,
            completed_at=completed_at,
        )

    def fail(
        self,
        *,
        organization_id: UUID,
        runtime_execution_id: UUID,
        runtime_attempt_id: UUID,
        status: str = "failed",
        completed_at: datetime | None = None,
    ) -> ProcessingRevision:
        if status not in {"failed", "cancelled", "abandoned"}:
            raise ProcessingRevisionConflictError("unsupported terminal processing revision status")
        return self._finish(
            organization_id=organization_id,
            runtime_execution_id=runtime_execution_id,
            runtime_attempt_id=runtime_attempt_id,
            status=status,
            content_unit_count=None,
            chunk_count=None,
            manifest_artifact_id=None,
            completed_at=completed_at,
        )

    def _finish(
        self,
        *,
        organization_id: UUID,
        runtime_execution_id: UUID,
        runtime_attempt_id: UUID,
        status: str,
        content_unit_count: int | None,
        chunk_count: int | None,
        manifest_artifact_id: UUID | None,
        completed_at: datetime | None,
    ) -> ProcessingRevision:
        revision = self.get_for_attempt(
            organization_id,
            runtime_execution_id,
            runtime_attempt_id,
            for_update=True,
        )
        if revision is None:
            raise ProcessingRevisionNotFoundError("processing revision was not found")
        if revision.status in TERMINAL_PROCESSING_REVISION_STATUSES:
            if revision.status != status:
                raise ProcessingRevisionConflictError("terminal processing revision is immutable")
            return revision
        if revision.status != "processing":
            raise ProcessingRevisionConflictError("processing revision is not active")

        event_time = completed_at or self._utcnow()
        if event_time.tzinfo is None:
            raise ProcessingRevisionConflictError("completed_at must be timezone-aware")
        if event_time < revision.started_at:
            raise ProcessingRevisionConflictError("completion cannot precede start")
        if content_unit_count is not None and content_unit_count < 0:
            raise ProcessingRevisionConflictError("content_unit_count cannot be negative")
        if chunk_count is not None and chunk_count < 0:
            raise ProcessingRevisionConflictError("chunk_count cannot be negative")

        revision.status = status
        revision.completed_at = event_time
        revision.updated_at = event_time
        if content_unit_count is not None:
            revision.content_unit_count = content_unit_count
        if chunk_count is not None:
            revision.chunk_count = chunk_count
        if manifest_artifact_id is not None:
            revision.manifest_artifact_id = manifest_artifact_id
        self.session.flush()
        return revision

    @staticmethod
    def _validate_same_identity(
        revision: ProcessingRevision,
        *,
        document_record_id: UUID,
        document_version_id: UUID,
        pipeline_profile_id: UUID | None,
        pipeline_profile_revision: str,
        adapter_key: str,
        adapter_version: str,
    ) -> None:
        expected = (
            document_record_id,
            document_version_id,
            pipeline_profile_id,
            pipeline_profile_revision,
            adapter_key,
            adapter_version,
        )
        actual = (
            revision.document_record_id,
            revision.document_version_id,
            revision.pipeline_profile_id,
            revision.pipeline_profile_revision,
            revision.adapter_key,
            revision.adapter_version,
        )
        if actual != expected:
            raise ProcessingRevisionConflictError(
                "runtime attempt is already bound to a different processing revision identity"
            )
