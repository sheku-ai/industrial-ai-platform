from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select

from app.models.artifact_publication import RuntimeArtifactPublication
from app.services.artifact_publication_lifecycle import ArtifactPublicationLifecycleService


@dataclass(frozen=True)
class ArtifactPublicationRetryResult:
    publication_id: UUID
    reused: bool


class ArtifactPublicationRetryService:
    """Resolve idempotent retries before creating a new publication attempt."""

    def __init__(self, lifecycle: ArtifactPublicationLifecycleService) -> None:
        self.lifecycle = lifecycle

    def resolve_or_reserve(
        self,
        *,
        organization_id: UUID,
        execution_id: UUID,
        artifact_id: UUID,
        attempt_id: UUID | None,
        storage_uri: str,
        media_type: str | None,
        checksum_sha256: str,
        size_bytes: int,
        metadata: dict[str, object] | None = None,
    ) -> ArtifactPublicationRetryResult:
        existing = self.lifecycle.session.scalar(
            select(RuntimeArtifactPublication)
            .where(
                RuntimeArtifactPublication.organization_id == organization_id,
                RuntimeArtifactPublication.execution_id == execution_id,
                RuntimeArtifactPublication.artifact_id == artifact_id,
                RuntimeArtifactPublication.storage_uri == storage_uri.strip(),
                RuntimeArtifactPublication.checksum_sha256 == checksum_sha256,
                RuntimeArtifactPublication.size_bytes == size_bytes,
                RuntimeArtifactPublication.status.in_(("published", "verified")),
            )
            .order_by(RuntimeArtifactPublication.publication_number.desc())
            .limit(1)
        )
        if existing is not None:
            return ArtifactPublicationRetryResult(existing.id, True)

        publication = self.lifecycle.reserve(
            organization_id=organization_id,
            execution_id=execution_id,
            artifact_id=artifact_id,
            attempt_id=attempt_id,
            storage_uri=storage_uri,
            media_type=media_type,
            checksum_sha256=checksum_sha256,
            size_bytes=size_bytes,
            metadata=metadata,
        )
        return ArtifactPublicationRetryResult(publication.id, False)
