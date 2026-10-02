from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from app.services.knowledge_artifact_publisher import PublishableKnowledgeArtifact


@dataclass(frozen=True)
class StoredArtifactInfo:
    object_name: str
    size_bytes: int
    sha256: str
    content_type: str
    version_tag: str | None = None


@dataclass(frozen=True)
class ArtifactPublicationResult:
    status: str
    object_name: str
    sha256: str
    size_bytes: int
    content_type: str
    idempotent: bool
    verified: bool


class ArtifactStoragePort(Protocol):
    def inspect(self, object_name: str) -> StoredArtifactInfo | None: ...

    def write(
        self,
        object_name: str,
        payload: bytes,
        *,
        content_type: str,
        metadata: Mapping[str, str],
    ) -> StoredArtifactInfo: ...

    def remove(self, object_name: str) -> None: ...


class KnowledgeArtifactStorageService:
    def __init__(self, storage: ArtifactStoragePort) -> None:
        self.storage = storage

    def publish(self, artifact: PublishableKnowledgeArtifact) -> ArtifactPublicationResult:
        actual_sha = hashlib.sha256(artifact.payload).hexdigest()
        actual_size = len(artifact.payload)
        expected_sha = str(artifact.manifest.get("sha256") or "")
        expected_size = int(artifact.manifest.get("size_bytes") or -1)

        if actual_sha != expected_sha or actual_size != expected_size:
            raise ValueError("artifact payload does not match its manifest")

        existing = self.storage.inspect(artifact.object_name)
        if existing is not None:
            if existing.sha256 == actual_sha and existing.size_bytes == actual_size:
                return ArtifactPublicationResult(
                    status="already_published",
                    object_name=artifact.object_name,
                    sha256=actual_sha,
                    size_bytes=actual_size,
                    content_type=artifact.content_type,
                    idempotent=True,
                    verified=True,
                )
            raise RuntimeError("artifact path already contains different content")

        stored = self.storage.write(
            artifact.object_name,
            artifact.payload,
            content_type=artifact.content_type,
            metadata={
                "sha256": actual_sha,
                "manifest_schema": str(artifact.manifest.get("schema") or ""),
                "document_version_id": str(artifact.manifest.get("document_version_id") or ""),
            },
        )
        verified = (
            stored.object_name == artifact.object_name
            and stored.sha256 == actual_sha
            and stored.size_bytes == actual_size
            and stored.content_type == artifact.content_type
        )
        if not verified:
            raise RuntimeError("stored artifact verification failed")

        return ArtifactPublicationResult(
            status="published",
            object_name=artifact.object_name,
            sha256=actual_sha,
            size_bytes=actual_size,
            content_type=artifact.content_type,
            idempotent=False,
            verified=True,
        )

    def compensate(self, publication: ArtifactPublicationResult) -> bool:
        if publication.idempotent:
            return False
        remover = getattr(self.storage, "remove", None)
        if not callable(remover):
            raise RuntimeError("artifact storage does not support compensation")
        remover(publication.object_name)
        return True
