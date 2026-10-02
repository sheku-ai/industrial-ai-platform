"""Provider-neutral embedding provider contracts."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class EmbeddingProviderDescriptor:
    provider_name: str
    provider_type: str
    provider_version: str
    capabilities: tuple[str, ...] = field(default_factory=tuple)
    dimensions_supported: tuple[int, ...] = field(default_factory=tuple)
    models_supported: tuple[str, ...] = field(default_factory=tuple)
    configurable: bool = False
    enabled: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider_name": self.provider_name,
            "provider_type": self.provider_type,
            "provider_version": self.provider_version,
            "capabilities": list(self.capabilities),
            "dimensions_supported": list(self.dimensions_supported),
            "models_supported": list(self.models_supported),
            "configurable": self.configurable,
            "enabled": self.enabled,
        }


class EmbeddingProvider(Protocol):
    @property
    def descriptor(self) -> EmbeddingProviderDescriptor: ...

    def prepare_embedding(self, request: dict[str, Any]) -> dict[str, Any]: ...

    def generate_embedding(self, request: dict[str, Any]) -> dict[str, Any]: ...

    def health(self) -> dict[str, Any]: ...

    def describe(self) -> dict[str, Any]: ...

    def supported_models(self) -> list[str]: ...

    def supported_dimensions(self) -> list[int]: ...


def metadata_embedding_hash(
    *, chunk: dict[str, Any], model_name: str, model_version: str, embedding_dimensions: int
) -> str:
    seed = "|".join(
        [
            str(chunk.get("knowledge_chunk_id")),
            str(chunk.get("content_hash")),
            str(chunk.get("semantic_hash")),
            model_name,
            model_version,
            str(embedding_dimensions),
            "metadata-only",
        ]
    )
    return f"sha256:{hashlib.sha256(seed.encode('utf-8')).hexdigest()}"


class MetadataOnlyEmbeddingProvider:
    descriptor = EmbeddingProviderDescriptor(
        provider_name="metadata-only",
        provider_type="reference",
        provider_version="metadata-only/1.0",
        capabilities=("prepare_embedding", "generate_embedding_metadata", "health", "describe"),
        dimensions_supported=(0,),
        models_supported=("metadata-only",),
        configurable=False,
        enabled=True,
    )

    def prepare_embedding(self, request: dict[str, Any]) -> dict[str, Any]:
        return {
            "provider_descriptor": self.describe(),
            "provider_prepared": True,
            "embedding_generated": False,
            "provider_called": False,
            "request": dict(request),
        }

    def generate_embedding(self, request: dict[str, Any]) -> dict[str, Any]:
        chunk = request.get("knowledge_chunk") if isinstance(request.get("knowledge_chunk"), dict) else {}
        model_name = str(request.get("model_name") or "metadata-only")
        model_version = str(request.get("model_version") or self.descriptor.provider_version)
        embedding_dimensions = int(request.get("embedding_dimensions") or 0)
        return {
            "provider_descriptor": self.describe(),
            "execution_state": "completed",
            "chunk_id": request.get("chunk_id"),
            "model_name": model_name,
            "model_version": model_version,
            "embedding_dimensions": embedding_dimensions,
            "embedding_hash": metadata_embedding_hash(
                chunk=chunk,
                model_name=model_name,
                model_version=model_version,
                embedding_dimensions=embedding_dimensions,
            ),
            "embedding_generated": False,
            "provider_generated_vector": False,
            "provider_called": False,
            "runtime_metadata": {
                **(request.get("runtime_metadata") if isinstance(request.get("runtime_metadata"), dict) else {}),
                "knowledge_chunk": chunk,
                "provider_name": self.descriptor.provider_name,
                "provider_type": self.descriptor.provider_type,
                "provider_version": self.descriptor.provider_version,
                "embedding_vector_generated": False,
                "embedding_provider_called": False,
                "semantic_search_used": False,
                "postgresql_source_of_truth": True,
            },
        }

    def health(self) -> dict[str, Any]:
        return {
            "provider_name": self.descriptor.provider_name,
            "provider_type": self.descriptor.provider_type,
            "provider_version": self.descriptor.provider_version,
            "healthy": True,
            "enabled": True,
            "embedding_generated": False,
            "provider_called": False,
        }

    def describe(self) -> dict[str, Any]:
        return self.descriptor.as_dict()

    def supported_models(self) -> list[str]:
        return list(self.descriptor.models_supported)

    def supported_dimensions(self) -> list[int]:
        return list(self.descriptor.dimensions_supported)


class FutureEmbeddingProvider:
    def __init__(self, *, provider_name: str, provider_type: str) -> None:
        self._descriptor = EmbeddingProviderDescriptor(
            provider_name=provider_name,
            provider_type=provider_type,
            provider_version="future",
            capabilities=("describe", "health"),
            dimensions_supported=(),
            models_supported=(),
            configurable=True,
            enabled=False,
        )

    @property
    def descriptor(self) -> EmbeddingProviderDescriptor:
        return self._descriptor

    def prepare_embedding(self, request: dict[str, Any]) -> dict[str, Any]:
        return {
            "provider_descriptor": self.describe(),
            "provider_prepared": False,
            "reason": "provider_not_implemented",
        }

    def generate_embedding(self, request: dict[str, Any]) -> dict[str, Any]:
        return {
            "provider_descriptor": self.describe(),
            "execution_state": "blocked",
            "reason": "provider_not_implemented",
        }

    def health(self) -> dict[str, Any]:
        return {
            "provider_name": self.descriptor.provider_name,
            "provider_type": self.descriptor.provider_type,
            "provider_version": self.descriptor.provider_version,
            "healthy": False,
            "enabled": False,
            "reason": "provider_not_implemented",
        }

    def describe(self) -> dict[str, Any]:
        return self.descriptor.as_dict()

    def supported_models(self) -> list[str]:
        return []

    def supported_dimensions(self) -> list[int]:
        return []
