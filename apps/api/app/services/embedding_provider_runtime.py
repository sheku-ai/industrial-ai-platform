"""Runtime adapter for provider-neutral embedding provider calls."""

from __future__ import annotations

from typing import Any

from app.services.embedding_provider_contracts import EmbeddingProvider


class EmbeddingProviderRuntimeAdapter:
    def prepare_embedding(self, *, provider: EmbeddingProvider, request: dict[str, Any]) -> dict[str, Any]:
        return {
            "provider_runtime_adapter_schema_version": "1",
            "operation": "prepare_embedding",
            "provider_runtime_called": True,
            "provider_descriptor": provider.describe(),
            "result": provider.prepare_embedding(request),
        }

    def generate_embedding(self, *, provider: EmbeddingProvider, request: dict[str, Any]) -> dict[str, Any]:
        return {
            "provider_runtime_adapter_schema_version": "1",
            "operation": "generate_embedding",
            "provider_runtime_called": True,
            "provider_descriptor": provider.describe(),
            "result": provider.generate_embedding(request),
        }


default_embedding_provider_runtime_adapter = EmbeddingProviderRuntimeAdapter()


def get_embedding_provider_runtime_adapter() -> EmbeddingProviderRuntimeAdapter:
    return default_embedding_provider_runtime_adapter
