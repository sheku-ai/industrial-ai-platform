from __future__ import annotations

from app.providers.base import ProviderAdapter
from app.providers.disabled import DisabledProviderAdapter


class ProviderAdapterRegistry:
    def __init__(self, disabled_adapter: ProviderAdapter | None = None) -> None:
        self._disabled_adapter = disabled_adapter or DisabledProviderAdapter()
        self._adapters: dict[str, ProviderAdapter] = {
            self._disabled_adapter.adapter_type: self._disabled_adapter,
        }

    def register(self, adapter: ProviderAdapter, *, replace: bool = False) -> None:
        adapter_type = adapter.adapter_type.strip()
        if not adapter_type:
            raise ValueError("adapter_type must not be empty")
        if adapter_type in self._adapters and not replace:
            raise ValueError(f"adapter already registered: {adapter_type}")
        self._adapters[adapter_type] = adapter

    def resolve(self, adapter_type: str | None) -> ProviderAdapter:
        if not adapter_type:
            return self._disabled_adapter
        return self._adapters.get(adapter_type.strip(), self._disabled_adapter)

    def registered_types(self) -> tuple[str, ...]:
        return tuple(sorted(self._adapters))
