from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from app.services.ingestion_artifact_registration import IngestionArtifactRecord, IngestionArtifactRegistrationService
from app.services.knowledge_artifact_publisher import PublishableKnowledgeArtifact
from app.services.knowledge_artifact_storage import ArtifactPublicationResult, KnowledgeArtifactStorageService


@dataclass(frozen=True)
class KnowledgeArtifactPublicationOutcome:
    publication: ArtifactPublicationResult
    registration: IngestionArtifactRecord


class ArtifactRegistrationAfterPublicationError(RuntimeError):
    def __init__(self, publication: ArtifactPublicationResult, cause: Exception, compensated: bool) -> None:
        super().__init__("artifact registration failed after storage publication")
        self.publication = publication
        self.compensated = compensated
        self.__cause__ = cause


class KnowledgeArtifactPublicationFlow:
    def __init__(
        self,
        storage_service: KnowledgeArtifactStorageService,
        registration_service: IngestionArtifactRegistrationService,
    ) -> None:
        self.storage_service = storage_service
        self.registration_service = registration_service

    def execute(
        self,
        artifact: PublishableKnowledgeArtifact,
        *,
        document_version_id: str,
        artifact_kind: str = "knowledge_ndjson",
        metadata: Mapping[str, str] | None = None,
    ) -> KnowledgeArtifactPublicationOutcome:
        publication = self.storage_service.publish(artifact)
        if not publication.verified:
            raise RuntimeError("artifact publication was not verified")
        try:
            registration = self.registration_service.register(
                publication,
                document_version_id=document_version_id,
                artifact_kind=artifact_kind,
                metadata=metadata,
            )
        except Exception as exc:
            compensated = self.storage_service.compensate(publication)
            raise ArtifactRegistrationAfterPublicationError(
                publication,
                exc,
                compensated,
            ) from exc
        return KnowledgeArtifactPublicationOutcome(
            publication=publication,
            registration=registration,
        )
