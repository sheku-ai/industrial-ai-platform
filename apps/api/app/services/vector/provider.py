from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class VectorProviderRequest:
    """Generic vector provider resolution request.

    Sprint 13.2 resolves provider references only. It does not call a vector
    database, generate embeddings or perform vector search.
    """

    vector_provider_ref: str | None
    retrieval_mode: str
    embedding_enabled: bool = False
    embedding_model_ref: str | None = None
    embedding_provider_ref: str | None = None
    embedding_dimension: int | None = None
    collection_ids: tuple[str, ...] = ()
    runtime_options: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class VectorProviderResolution:
    """Normalized vector provider resolution result."""

    configured: bool
    available: bool
    vector_provider_ref: str | None = None
    provider_adapter: str = "disabled_vector_provider_v1"
    status: str = "disabled"
    error_code: str | None = None
    error_message: str | None = None
    runtime_metadata: dict[str, Any] = field(default_factory=dict)

    def as_metrics(self) -> dict[str, Any]:
        return {
            "vector_provider_ref": self.vector_provider_ref,
            "vector_provider_adapter": self.provider_adapter,
            "vector_provider_configured": self.configured,
            "vector_provider_available": self.available,
            "vector_provider_status": self.status,
            "vector_provider_error_code": self.error_code,
            **self.runtime_metadata,
        }


class VectorProvider(Protocol):
    """Replaceable vector provider boundary."""

    provider_adapter: str

    def resolve(self, request: VectorProviderRequest) -> VectorProviderResolution:
        """Resolve provider availability and configuration state."""


class DisabledVectorProvider:
    """Safe default vector provider used when vector retrieval is not configured."""

    provider_adapter = "disabled_vector_provider_v1"

    def resolve(self, request: VectorProviderRequest) -> VectorProviderResolution:
        return VectorProviderResolution(
            configured=False,
            available=False,
            vector_provider_ref=request.vector_provider_ref,
            provider_adapter=self.provider_adapter,
            status="disabled",
            error_code="vector_provider_not_configured",
            error_message="No vector provider is configured for vector retrieval.",
            runtime_metadata={
                **request.runtime_options,
                "vector_provider_resolution": "disabled_default",
                "vector_provider_requested_mode": request.retrieval_mode,
                "vector_provider_embedding_enabled": request.embedding_enabled,
                "vector_provider_embedding_model_ref": request.embedding_model_ref,
                "vector_provider_embedding_provider_ref": request.embedding_provider_ref,
                "vector_provider_embedding_dimension": request.embedding_dimension,
            },
        )


def resolve_vector_provider(vector_provider_ref: str | None = None) -> VectorProvider:
    """Resolve vector provider implementation.

    Sprint 13.2 intentionally returns the disabled provider for every reference.
    Concrete vector adapters are introduced in later work packages.
    """

    return DisabledVectorProvider()
