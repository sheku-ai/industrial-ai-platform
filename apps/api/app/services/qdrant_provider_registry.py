"""Descriptor-only Qdrant provider registry."""

from __future__ import annotations

from app.services.qdrant_provider_contracts import QdrantProviderDescriptor


class QdrantProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, QdrantProviderDescriptor] = {
            "qdrant-disabled": QdrantProviderDescriptor(),
            "future-qdrant-local": QdrantProviderDescriptor(
                provider_name="future-qdrant-local",
                provider_type="future",
                provider_version="future",
                collection_status="disabled",
            ),
            "future-qdrant-cloud": QdrantProviderDescriptor(
                provider_name="future-qdrant-cloud",
                provider_type="future",
                provider_version="future",
                collection_status="disabled",
            ),
        }

    def resolve(self, provider_name: str | None = None) -> tuple[QdrantProviderDescriptor, dict]:
        requested = provider_name or "qdrant-disabled"
        provider = self._providers.get(requested)
        if provider is None:
            return self._providers["qdrant-disabled"], {
                "provider_resolution_status": "fallback",
                "requested_provider_name": requested,
                "resolved_provider_name": "qdrant-disabled",
                "error": "qdrant_provider_not_registered",
            }
        return provider, {
            "provider_resolution_status": "resolved",
            "requested_provider_name": requested,
            "resolved_provider_name": provider.provider_name,
            "error": None,
        }

    def list_providers(self) -> list[dict]:
        return [provider.as_dict() for provider in self._providers.values()]

    def health(self) -> dict:
        return {
            "qdrant_provider_registry_schema_version": "1",
            "qdrant_provider_registry_loaded": True,
            "registered_provider_count": len(self._providers),
            "enabled_provider_count": len([provider for provider in self._providers.values() if provider.enabled]),
            "default_provider_name": "qdrant-disabled",
            "providers": self.list_providers(),
            "qdrant_called": False,
            "network_call_attempted": False,
            "semantic_search_enabled": False,
            "hybrid_search_enabled": False,
        }


default_qdrant_provider_registry = QdrantProviderRegistry()


def get_qdrant_provider_registry() -> QdrantProviderRegistry:
    return default_qdrant_provider_registry
