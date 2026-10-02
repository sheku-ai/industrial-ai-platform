"""Embedding provider registry."""

from __future__ import annotations

from app.services.embedding_provider_contracts import (
    EmbeddingProvider,
    FutureEmbeddingProvider,
    MetadataOnlyEmbeddingProvider,
)


class EmbeddingProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, EmbeddingProvider] = {}
        self.register(MetadataOnlyEmbeddingProvider())
        self.register(FutureEmbeddingProvider(provider_name="future-ollama", provider_type="future"))
        self.register(FutureEmbeddingProvider(provider_name="future-openai", provider_type="future"))
        self.register(FutureEmbeddingProvider(provider_name="future-sentence-transformers", provider_type="future"))
        self.register(FutureEmbeddingProvider(provider_name="future-onnx", provider_type="future"))
        self.register(FutureEmbeddingProvider(provider_name="future-huggingface", provider_type="future"))

    def register(self, provider: EmbeddingProvider) -> None:
        self._providers[provider.descriptor.provider_name] = provider

    def resolve(self, provider_name: str | None = None) -> EmbeddingProvider:
        return self._providers.get(provider_name or "metadata-only", self._providers["metadata-only"])

    def list_providers(self) -> list[dict]:
        return [provider.describe() for provider in self._providers.values()]

    def health(self) -> dict:
        provider_health = [provider.health() for provider in self._providers.values()]
        return {
            "embedding_provider_registry_schema_version": "1",
            "provider_registry_loaded": True,
            "registered_provider_count": len(provider_health),
            "enabled_provider_count": len([item for item in provider_health if item.get("enabled")]),
            "providers": provider_health,
        }


default_embedding_provider_registry = EmbeddingProviderRegistry()


def get_embedding_provider_registry() -> EmbeddingProviderRegistry:
    return default_embedding_provider_registry
