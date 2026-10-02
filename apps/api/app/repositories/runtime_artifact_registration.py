from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import UTC
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.artifact_publication import RuntimeArtifactPublication
from app.services.ingestion_artifact_registration import IngestionArtifactRecord


class SqlAlchemyRuntimeArtifactRegistry:
    """Persists ingestion artifact registrations in the existing runtime schema.

    The repository deliberately reuses runtime.artifact_publications instead of
    introducing a parallel artifact registry. Runtime execution identifiers are
    supplied by the worker orchestration context.
    """

    def __init__(
        self,
        session: Session,
        *,
        organization_id: uuid.UUID,
        execution_id: uuid.UUID,
        artifact_id: uuid.UUID,
        attempt_id: uuid.UUID | None = None,
    ) -> None:
        self.session = session
        self.organization_id = organization_id
        self.execution_id = execution_id
        self.artifact_id = artifact_id
        self.attempt_id = attempt_id

    def find(
        self,
        *,
        document_version_id: str,
        artifact_kind: str,
        object_name: str,
    ) -> IngestionArtifactRecord | None:
        statement = select(RuntimeArtifactPublication).where(
            RuntimeArtifactPublication.organization_id == self.organization_id,
            RuntimeArtifactPublication.execution_id == self.execution_id,
            RuntimeArtifactPublication.artifact_id == self.artifact_id,
            RuntimeArtifactPublication.storage_uri == object_name,
        )
        row = self.session.execute(statement).scalar_one_or_none()
        if row is None:
            return None
        metadata = dict(row.metadata_ or {})
        if metadata.get("document_version_id") != document_version_id:
            return None
        if metadata.get("artifact_kind") != artifact_kind:
            return None
        return _to_domain(row)

    def save(self, record: IngestionArtifactRecord) -> IngestionArtifactRecord:
        publication_number = self._next_publication_number()
        metadata: dict[str, Any] = dict(record.metadata)
        metadata.update(
            {
                "document_version_id": record.document_version_id,
                "artifact_kind": record.artifact_kind,
            }
        )
        row = RuntimeArtifactPublication(
            organization_id=self.organization_id,
            execution_id=self.execution_id,
            artifact_id=self.artifact_id,
            attempt_id=self.attempt_id,
            publication_number=publication_number,
            storage_uri=record.object_name,
            media_type=record.content_type,
            checksum_sha256=record.sha256,
            size_bytes=record.size_bytes,
            status="verified" if record.verified else "published",
            published_at=record.published_at,
            verified_at=record.published_at if record.verified else None,
            metadata_=metadata,
        )
        self.session.add(row)
        self.session.flush()
        return _to_domain(row)

    def _next_publication_number(self) -> int:
        statement = (
            select(RuntimeArtifactPublication.publication_number)
            .where(RuntimeArtifactPublication.artifact_id == self.artifact_id)
            .order_by(RuntimeArtifactPublication.publication_number.desc())
            .limit(1)
        )
        current = self.session.execute(statement).scalar_one_or_none()
        return int(current or 0) + 1


def _to_domain(row: RuntimeArtifactPublication) -> IngestionArtifactRecord:
    metadata: Mapping[str, Any] = dict(row.metadata_ or {})
    published_at = row.published_at or row.created_at
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=UTC)
    return IngestionArtifactRecord(
        document_version_id=str(metadata.get("document_version_id") or ""),
        artifact_kind=str(metadata.get("artifact_kind") or "knowledge_ndjson"),
        object_name=row.storage_uri,
        sha256=str(row.checksum_sha256 or ""),
        size_bytes=int(row.size_bytes or 0),
        content_type=str(row.media_type or "application/octet-stream"),
        publication_status=row.status,
        verified=row.status == "verified" or row.verified_at is not None,
        published_at=published_at,
        metadata={
            str(key): str(value)
            for key, value in metadata.items()
            if key not in {"document_version_id", "artifact_kind"}
        },
    )
