from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from app.services.processing_revision_lifecycle import ProcessingRevisionLifecycleService


class ProcessingRevisionRuntime:
    """Transaction boundary used by runtime adapters for processing revisions."""

    def __init__(self, session_factory) -> None:
        self._session_factory = session_factory

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
    ) -> UUID:
        session = self._session_factory()
        try:
            revision = ProcessingRevisionLifecycleService(session).start(
                organization_id=organization_id,
                document_record_id=document_record_id,
                document_version_id=document_version_id,
                runtime_execution_id=runtime_execution_id,
                runtime_attempt_id=runtime_attempt_id,
                pipeline_profile_id=pipeline_profile_id,
                pipeline_profile_revision=pipeline_profile_revision,
                adapter_key=adapter_key,
                adapter_version=adapter_version,
                configuration_snapshot=configuration_snapshot,
                source_checksum_sha256=source_checksum_sha256,
            )
            session.commit()
            return revision.id
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def complete(
        self,
        *,
        organization_id: UUID,
        runtime_execution_id: UUID,
        runtime_attempt_id: UUID,
        content_unit_count: int,
        chunk_count: int,
        manifest_artifact_id: UUID | None = None,
    ) -> None:
        self._finish(
            method_name="complete",
            organization_id=organization_id,
            runtime_execution_id=runtime_execution_id,
            runtime_attempt_id=runtime_attempt_id,
            content_unit_count=content_unit_count,
            chunk_count=chunk_count,
            manifest_artifact_id=manifest_artifact_id,
        )

    def fail(
        self,
        *,
        organization_id: UUID,
        runtime_execution_id: UUID,
        runtime_attempt_id: UUID,
        status: str,
    ) -> None:
        self._finish(
            method_name="fail",
            organization_id=organization_id,
            runtime_execution_id=runtime_execution_id,
            runtime_attempt_id=runtime_attempt_id,
            status=status,
        )

    def _finish(self, *, method_name: str, **kwargs) -> None:
        session = self._session_factory()
        try:
            lifecycle = ProcessingRevisionLifecycleService(session)
            getattr(lifecycle, method_name)(**kwargs)
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
