from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from sqlalchemy import select

from app.models.artifact_publication import RuntimeArtifactPublication
from app.services.artifact_publication_lifecycle import ArtifactPublicationLifecycleService
from app.services.artifact_reconciliation import ArtifactObjectMetadata


class ArtifactMetadataStore(Protocol):
    def stat(self, storage_uri: str) -> ArtifactObjectMetadata | None: ...


@dataclass(frozen=True)
class ArtifactRegistrationResult:
    outcome: str
    publication_id: UUID | None
    changed: bool


class ArtifactUnregisteredObjectService:
    def __init__(self, lifecycle: ArtifactPublicationLifecycleService, object_store: ArtifactMetadataStore) -> None:
        self.lifecycle = lifecycle
        self.object_store = object_store

    def register(
        self,
        *,
        organization_id: UUID,
        execution_id: UUID,
        artifact_id: UUID,
        attempt_id: UUID | None,
        storage_uri: str,
        media_type: str | None = None,
    ) -> ArtifactRegistrationResult:
        canonical_uri = storage_uri.strip()
        if not canonical_uri:
            raise ValueError("storage_uri is required")

        metadata = self.object_store.stat(canonical_uri)
        if metadata is None:
            return ArtifactRegistrationResult("object_missing", None, False)

        existing = self.lifecycle.session.scalar(
            select(RuntimeArtifactPublication)
            .where(
                RuntimeArtifactPublication.organization_id == organization_id,
                RuntimeArtifactPublication.execution_id == execution_id,
                RuntimeArtifactPublication.artifact_id == artifact_id,
                RuntimeArtifactPublication.storage_uri == canonical_uri,
                RuntimeArtifactPublication.checksum_sha256 == metadata.checksum_sha256,
                RuntimeArtifactPublication.size_bytes == metadata.size_bytes,
                RuntimeArtifactPublication.status == "verified",
            )
            .order_by(RuntimeArtifactPublication.publication_number.desc())
            .limit(1)
        )
        if existing is not None:
            return ArtifactRegistrationResult("verified", existing.id, False)

        publication = self.lifecycle.reserve(
            organization_id=organization_id,
            execution_id=execution_id,
            artifact_id=artifact_id,
            attempt_id=attempt_id,
            storage_uri=canonical_uri,
            media_type=metadata.media_type or media_type,
            checksum_sha256=metadata.checksum_sha256,
            size_bytes=metadata.size_bytes,
            metadata={"reconciled_from_object": True},
        )
        self.lifecycle.mark_publishing(organization_id, publication.id)
        self.lifecycle.mark_published(organization_id, publication.id)
        self.lifecycle.mark_verified(organization_id, publication.id)
        return ArtifactRegistrationResult("verified", publication.id, True)
