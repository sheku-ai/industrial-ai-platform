from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.core.config import get_settings


class SemanticPublicationConfigurationError(RuntimeError):
    code = "semantic_publication_not_configured"


@dataclass(frozen=True)
class SemanticPublicationOutcome:
    connected: bool
    enabled: bool
    published_documents: int
    provider: str


class SemanticPublisher(Protocol):
    provider_name: str

    def publish(
        self,
        *,
        organization_id: UUID,
        document_version_id: UUID,
        execution_id: UUID,
        texts: Sequence[str],
    ) -> int: ...


class OptionalSemanticPublicationService:
    """Feature-gated semantic publication boundary.

    The base platform always wires this service. Semantic publication remains
    disabled unless both embeddings and vector retrieval are enabled and a
    provider implementation is supplied.
    """

    def __init__(self, publisher: SemanticPublisher | None = None) -> None:
        self._publisher = publisher

    def publish(
        self,
        *,
        organization_id: UUID,
        document_version_id: UUID,
        execution_id: UUID,
        texts: Sequence[str],
    ) -> SemanticPublicationOutcome:
        settings = get_settings()
        enabled = bool(settings.feature_embeddings_enabled and settings.feature_vector_retrieval_enabled)
        if not enabled:
            return SemanticPublicationOutcome(
                connected=True,
                enabled=False,
                published_documents=0,
                provider="disabled",
            )
        if self._publisher is None:
            raise SemanticPublicationConfigurationError("semantic publication is enabled but no provider is configured")
        published = self._publisher.publish(
            organization_id=organization_id,
            document_version_id=document_version_id,
            execution_id=execution_id,
            texts=texts,
        )
        return SemanticPublicationOutcome(
            connected=True,
            enabled=True,
            published_documents=published,
            provider=self._publisher.provider_name,
        )
