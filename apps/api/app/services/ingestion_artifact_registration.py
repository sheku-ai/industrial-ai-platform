from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from app.services.knowledge_artifact_storage import ArtifactPublicationResult


@dataclass(frozen=True)
class IngestionArtifactRecord:
    document_version_id: str
    artifact_kind: str
    object_name: str
    sha256: str
    size_bytes: int
    content_type: str
    publication_status: str
    verified: bool
    published_at: datetime
    metadata: Mapping[str, str]


class IngestionArtifactRegistryPort(Protocol):
    def find(
        self,
        *,
        document_version_id: str,
        artifact_kind: str,
        object_name: str,
    ) -> IngestionArtifactRecord | None: ...

    def save(self, record: IngestionArtifactRecord) -> IngestionArtifactRecord: ...


class IngestionArtifactRegistrationService:
    """Registers storage publication outcomes without depending on storage SDKs."""

    def __init__(self, registry: IngestionArtifactRegistryPort) -> None:
        self.registry = registry

    def register(
        self,
        publication: ArtifactPublicationResult,
        *,
        document_version_id: str,
        artifact_kind: str = "knowledge_ndjson",
        metadata: Mapping[str, str] | None = None,
    ) -> IngestionArtifactRecord:
        document_version_id = document_version_id.strip()
        artifact_kind = artifact_kind.strip()
        if not document_version_id:
            raise ValueError("document_version_id is required")
        if not artifact_kind:
            raise ValueError("artifact_kind is required")
        if not publication.verified:
            raise ValueError("unverified publication cannot be registered")

        existing = self.registry.find(
            document_version_id=document_version_id,
            artifact_kind=artifact_kind,
            object_name=publication.object_name,
        )
        if existing is not None:
            if (
                existing.sha256 == publication.sha256
                and existing.size_bytes == publication.size_bytes
                and existing.content_type == publication.content_type
            ):
                return existing
            raise RuntimeError("registered artifact conflicts with publication")

        record = IngestionArtifactRecord(
            document_version_id=document_version_id,
            artifact_kind=artifact_kind,
            object_name=publication.object_name,
            sha256=publication.sha256,
            size_bytes=publication.size_bytes,
            content_type=publication.content_type,
            publication_status=publication.status,
            verified=publication.verified,
            published_at=datetime.now(UTC),
            metadata=dict(metadata or {}),
        )
        return self.registry.save(record)
