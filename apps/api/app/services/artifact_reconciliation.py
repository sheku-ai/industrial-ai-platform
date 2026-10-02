from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.models.artifact_publication import RuntimeArtifactPublication
from app.services.artifact_publication_lifecycle import ArtifactPublicationLifecycleService


@dataclass(frozen=True)
class ArtifactObjectMetadata:
    size_bytes: int | None = None
    checksum_sha256: str | None = None
    media_type: str | None = None


class ArtifactObjectStore(Protocol):
    def stat(self, storage_uri: str) -> ArtifactObjectMetadata | None: ...


@dataclass(frozen=True)
class ArtifactReconciliationResult:
    outcome: str
    source_publication_id: UUID
    resulting_publication_id: UUID
    changed: bool


@dataclass(frozen=True)
class ArtifactReconciliationPreview:
    outcome: str
    source_publication_id: UUID
    would_change: bool


class ArtifactReconciliationService:
    """Reconcile publication registry state against provider-neutral object metadata."""

    def __init__(
        self,
        lifecycle: ArtifactPublicationLifecycleService,
        object_store: ArtifactObjectStore,
    ) -> None:
        self.lifecycle = lifecycle
        self.object_store = object_store

    def preview(
        self,
        organization_id: UUID,
        publication_id: UUID,
    ) -> ArtifactReconciliationPreview:
        """Calculate the expected result without mutating publication history."""
        publication = self.lifecycle.get(organization_id, publication_id)
        if publication is None:
            raise ValueError("artifact publication was not found")

        metadata = self.object_store.stat(publication.storage_uri)
        if metadata is None:
            return ArtifactReconciliationPreview(
                outcome="missing",
                source_publication_id=publication.id,
                would_change=publication.status not in {"missing", "deleted"},
            )

        if self._has_conflict(publication, metadata):
            return ArtifactReconciliationPreview(
                outcome="checksum_conflict",
                source_publication_id=publication.id,
                would_change=publication.status != "checksum_conflict",
            )

        if publication.status in {"reserved", "publishing", "published"}:
            return ArtifactReconciliationPreview(
                outcome="verified",
                source_publication_id=publication.id,
                would_change=True,
            )

        return ArtifactReconciliationPreview(
            outcome=publication.status,
            source_publication_id=publication.id,
            would_change=False,
        )

    def reconcile(
        self,
        organization_id: UUID,
        publication_id: UUID,
    ) -> ArtifactReconciliationResult:
        publication = self.lifecycle.get(organization_id, publication_id, for_update=True)
        if publication is None:
            raise ValueError("artifact publication was not found")

        metadata = self.object_store.stat(publication.storage_uri)
        if metadata is None:
            if publication.status in {"missing", "deleted"}:
                return ArtifactReconciliationResult(
                    publication.status,
                    publication.id,
                    publication.id,
                    False,
                )
            result = self._record_finding(publication, "missing")
            return ArtifactReconciliationResult("missing", publication.id, result.id, True)

        if self._has_conflict(publication, metadata):
            if publication.status == "checksum_conflict":
                return ArtifactReconciliationResult(
                    "checksum_conflict",
                    publication.id,
                    publication.id,
                    False,
                )
            result = self._record_finding(publication, "checksum_conflict")
            return ArtifactReconciliationResult(
                "checksum_conflict",
                publication.id,
                result.id,
                True,
            )

        if publication.status == "verified":
            return ArtifactReconciliationResult("verified", publication.id, publication.id, False)
        if publication.status == "published":
            result = self.lifecycle.mark_verified(organization_id, publication.id)
            return ArtifactReconciliationResult("verified", publication.id, result.id, True)
        if publication.status in {"reserved", "publishing"}:
            result = self.lifecycle.mark_published(organization_id, publication.id)
            result = self.lifecycle.mark_verified(organization_id, result.id)
            return ArtifactReconciliationResult("verified", publication.id, result.id, True)

        return ArtifactReconciliationResult(publication.status, publication.id, publication.id, False)

    def _record_finding(
        self,
        publication: RuntimeArtifactPublication,
        status: str,
    ) -> RuntimeArtifactPublication:
        if publication.status in {"reserved", "publishing"}:
            return self.lifecycle.mark_terminal(
                publication.organization_id,
                publication.id,
                status=status,
            )

        finding = self.lifecycle.reserve(
            organization_id=publication.organization_id,
            execution_id=publication.execution_id,
            artifact_id=publication.artifact_id,
            attempt_id=publication.attempt_id,
            storage_uri=publication.storage_uri,
            media_type=publication.media_type,
            checksum_sha256=publication.checksum_sha256,
            size_bytes=publication.size_bytes,
            metadata={"reconciliation_of": str(publication.id)},
        )
        return self.lifecycle.mark_terminal(
            publication.organization_id,
            finding.id,
            status=status,
        )

    @staticmethod
    def _has_conflict(
        publication: RuntimeArtifactPublication,
        metadata: ArtifactObjectMetadata,
    ) -> bool:
        if (
            publication.checksum_sha256
            and metadata.checksum_sha256
            and publication.checksum_sha256 != metadata.checksum_sha256
        ):
            return True
        return (
            publication.size_bytes is not None
            and metadata.size_bytes is not None
            and publication.size_bytes != metadata.size_bytes
        )
