from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.artifact_publication import RuntimeArtifactPublication
from app.models.runtime import RuntimeExecutionArtifact

ACTIVE_PUBLICATION_STATUSES = {"reserved", "publishing"}
TERMINAL_PUBLICATION_STATUSES = {
    "published",
    "verified",
    "missing",
    "checksum_conflict",
    "reconciliation_required",
    "failed",
    "retained",
    "deleted",
}


class ArtifactPublicationError(RuntimeError):
    code = "artifact_publication_error"


class ArtifactPublicationConflictError(ArtifactPublicationError):
    code = "artifact_publication_conflict"


class ArtifactPublicationNotFoundError(ArtifactPublicationError):
    code = "artifact_publication_not_found"


class ArtifactPublicationLifecycleService:
    """Own immutable publication-attempt creation and state transitions.

    The caller owns commit and rollback. Publication identity fields are immutable;
    retries create a new publication number instead of rewriting prior attempts.
    """

    def __init__(self, session: Session) -> None:
        self.session = session

    @staticmethod
    def _utcnow() -> datetime:
        return datetime.now(UTC)

    def reserve(
        self,
        *,
        organization_id: UUID,
        execution_id: UUID,
        artifact_id: UUID,
        attempt_id: UUID | None,
        storage_uri: str,
        media_type: str | None = None,
        checksum_sha256: str | None = None,
        size_bytes: int | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> RuntimeArtifactPublication:
        artifact = self.session.scalar(
            select(RuntimeExecutionArtifact)
            .where(
                RuntimeExecutionArtifact.id == artifact_id,
                RuntimeExecutionArtifact.organization_id == organization_id,
                RuntimeExecutionArtifact.execution_id == execution_id,
            )
            .with_for_update()
        )
        if artifact is None:
            raise ArtifactPublicationNotFoundError("logical artifact was not found")

        canonical_uri = storage_uri.strip()
        if not canonical_uri:
            raise ArtifactPublicationConflictError("storage_uri is required")
        if checksum_sha256 is not None and (
            len(checksum_sha256) != 64
            or checksum_sha256.lower() != checksum_sha256
            or any(character not in "0123456789abcdef" for character in checksum_sha256)
        ):
            raise ArtifactPublicationConflictError("checksum must be a lowercase SHA-256 digest")
        if size_bytes is not None and size_bytes < 0:
            raise ArtifactPublicationConflictError("size_bytes cannot be negative")

        publication_number = self.session.scalar(
            select(func.coalesce(func.max(RuntimeArtifactPublication.publication_number), 0) + 1).where(
                RuntimeArtifactPublication.artifact_id == artifact_id
            )
        )
        publication = RuntimeArtifactPublication(
            organization_id=organization_id,
            execution_id=execution_id,
            artifact_id=artifact_id,
            attempt_id=attempt_id,
            publication_number=int(publication_number or 1),
            storage_uri=canonical_uri,
            media_type=media_type.strip() if media_type else None,
            checksum_sha256=checksum_sha256,
            size_bytes=size_bytes,
            status="reserved",
            metadata_=dict(metadata or {}),
        )
        self.session.add(publication)
        self.session.flush()
        return publication

    def get(
        self,
        organization_id: UUID,
        publication_id: UUID,
        *,
        for_update: bool = False,
    ) -> RuntimeArtifactPublication | None:
        statement = select(RuntimeArtifactPublication).where(
            RuntimeArtifactPublication.organization_id == organization_id,
            RuntimeArtifactPublication.id == publication_id,
        )
        if for_update:
            statement = statement.with_for_update()
        return self.session.scalar(statement)

    def mark_publishing(self, organization_id: UUID, publication_id: UUID) -> RuntimeArtifactPublication:
        return self._transition(organization_id, publication_id, "publishing")

    def mark_published(
        self,
        organization_id: UUID,
        publication_id: UUID,
        *,
        published_at: datetime | None = None,
    ) -> RuntimeArtifactPublication:
        return self._transition(
            organization_id,
            publication_id,
            "published",
            published_at=published_at or self._utcnow(),
        )

    def mark_verified(
        self,
        organization_id: UUID,
        publication_id: UUID,
        *,
        verified_at: datetime | None = None,
    ) -> RuntimeArtifactPublication:
        publication = self.get(organization_id, publication_id, for_update=True)
        if publication is None:
            raise ArtifactPublicationNotFoundError("artifact publication was not found")
        if publication.status == "verified":
            return publication
        if publication.status != "published":
            raise ArtifactPublicationConflictError("only a published artifact can be verified")
        event_time = verified_at or self._utcnow()
        self._require_aware(event_time, "verified_at")
        if publication.published_at is None or event_time < publication.published_at:
            raise ArtifactPublicationConflictError("verification cannot precede publication")
        publication.status = "verified"
        publication.verified_at = event_time
        self.session.flush()
        return publication

    def mark_terminal(
        self,
        organization_id: UUID,
        publication_id: UUID,
        *,
        status: str,
        error_code: str | None = None,
    ) -> RuntimeArtifactPublication:
        if status not in TERMINAL_PUBLICATION_STATUSES - {"published", "verified"}:
            raise ArtifactPublicationConflictError("unsupported terminal publication status")
        return self._transition(
            organization_id,
            publication_id,
            status,
            error_code=error_code,
        )

    def _transition(
        self,
        organization_id: UUID,
        publication_id: UUID,
        status: str,
        *,
        published_at: datetime | None = None,
        error_code: str | None = None,
    ) -> RuntimeArtifactPublication:
        publication = self.get(organization_id, publication_id, for_update=True)
        if publication is None:
            raise ArtifactPublicationNotFoundError("artifact publication was not found")
        if publication.status == status:
            return publication
        if publication.status in TERMINAL_PUBLICATION_STATUSES:
            raise ArtifactPublicationConflictError("terminal artifact publication is immutable")
        if status == "publishing" and publication.status != "reserved":
            raise ArtifactPublicationConflictError("only a reserved publication can start publishing")
        if status == "published" and publication.status not in ACTIVE_PUBLICATION_STATUSES:
            raise ArtifactPublicationConflictError("publication is not active")
        if published_at is not None:
            self._require_aware(published_at, "published_at")
            publication.published_at = published_at
        publication.status = status
        publication.error_code = error_code.strip() if error_code else None
        self.session.flush()
        return publication

    @staticmethod
    def _require_aware(value: datetime, field_name: str) -> None:
        if value.tzinfo is None:
            raise ArtifactPublicationConflictError(f"{field_name} must be timezone-aware")
