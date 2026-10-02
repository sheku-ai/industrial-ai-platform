"""Storage provider registry for provider-neutral resolution."""

from __future__ import annotations

from typing import Any

from app.services.storage_provider_contracts import (
    ConfigurableStorageProvider,
    NullStorageProvider,
    StorageProvider,
    normalize_storage_provider_name,
    sanitize_storage_provider_configuration,
)
from app.services.storage_provider_filesystem import (
    FILESYSTEM_STORAGE_PROVIDER_NAME,
    FILESYSTEM_STORAGE_PROVIDER_TYPE,
    FilesystemStorageProvider,
)
from app.services.storage_provider_memory import InMemoryStorageProvider


class StorageProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, StorageProvider] = {}
        self.register(NullStorageProvider())
        self.register(InMemoryStorageProvider())
        self.register(FilesystemStorageProvider())
        self.register(ConfigurableStorageProvider())

    def register(self, provider: StorageProvider) -> None:
        provider_name = normalize_storage_provider_name(provider.descriptor.provider_name)
        if not provider_name:
            raise ValueError("storage provider name is required")
        self._providers[provider_name] = provider

    def resolve(
        self,
        provider_name: str | None = None,
        *,
        configuration: dict[str, Any] | None = None,
    ) -> StorageProvider:
        if isinstance(configuration, dict) and configuration:
            configured_name = configuration.get("provider_name") or configuration.get("name") or provider_name
            configured_type = configuration.get("provider_type") or configuration.get("type")
            normalized_configured_name = normalize_storage_provider_name(
                str(configured_name) if configured_name else None
            )
            normalized_configured_type = normalize_storage_provider_name(
                str(configured_type) if configured_type else None
            )
            if (
                normalized_configured_name == FILESYSTEM_STORAGE_PROVIDER_NAME
                or normalized_configured_type == FILESYSTEM_STORAGE_PROVIDER_TYPE
            ):
                return FilesystemStorageProvider(configuration)
            if normalized_configured_name in self._providers and normalized_configured_name != "configurable":
                return self._providers[normalized_configured_name]
            if normalized_configured_name != "null":
                return ConfigurableStorageProvider(configuration)
        resolved_name = normalize_storage_provider_name(provider_name)
        return self._providers.get(resolved_name, self._providers["null"])

    def resolve_with_trace(
        self,
        provider_name: str | None = None,
        *,
        configuration: dict[str, Any] | None = None,
    ) -> tuple[StorageProvider, dict[str, Any]]:
        requested_name = normalize_storage_provider_name(provider_name)
        provider = self.resolve(provider_name, configuration=configuration)
        resolved_name = provider.descriptor.provider_name
        dynamic_configuration_used = (
            isinstance(configuration, dict)
            and bool(configuration)
            and provider.descriptor.provider_type == "configurable"
        )
        registry_fallback_used = provider.descriptor.provider_type == "null" and requested_name != "null"
        trace = {
            "requested_provider_name": provider_name,
            "normalized_requested_provider_name": requested_name,
            "resolved_provider_name": resolved_name,
            "resolved_provider_type": provider.descriptor.provider_type,
            "provider_configured": provider.descriptor.configured,
            "provider_status": provider.descriptor.status,
            "registry_fallback_used": registry_fallback_used,
            "dynamic_configuration_used": dynamic_configuration_used,
            "configuration_supplied": isinstance(configuration, dict) and bool(configuration),
            "safe_configuration": sanitize_storage_provider_configuration(configuration or {}),
            "provider_descriptor": provider.descriptor.as_dict(),
        }
        return provider, trace


default_storage_provider_registry = StorageProviderRegistry()


def get_storage_provider_registry() -> StorageProviderRegistry:
    return default_storage_provider_registry
