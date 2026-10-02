from __future__ import annotations

from dataclasses import dataclass, field

from app.services.ingestion.adapters.contracts import ExtractionProfile, IngestionSourceRef
from app.services.ingestion.adapters.interfaces import ExtractionAdapter


@dataclass
class AdapterRegistry:
    """Runtime registry for extraction adapters.

    This registry is intentionally simple and dependency-free. In later Sprint 9
    work packages, adapter registrations should be loaded from PostgreSQL-backed
    platform configuration instead of hardcoded module initialization.
    """

    _adapters: dict[str, ExtractionAdapter] = field(default_factory=dict)

    def register(self, adapter: ExtractionAdapter) -> None:
        if not adapter.name:
            raise ValueError("adapter name is required")
        self._adapters[adapter.name] = adapter

    def get(self, name: str) -> ExtractionAdapter | None:
        return self._adapters.get(name)

    def list(self) -> tuple[ExtractionAdapter, ...]:
        return tuple(self._adapters.values())

    def resolve(self, source: IngestionSourceRef, profile: ExtractionProfile) -> ExtractionAdapter:
        if profile.adapter_name:
            adapter = self.get(profile.adapter_name)
            if adapter is None:
                raise LookupError(f"adapter not registered: {profile.adapter_name}")
            if not adapter.supports(source, profile):
                raise LookupError(f"adapter does not support source: {profile.adapter_name}")
            return adapter

        for adapter in self._adapters.values():
            if adapter.supports(source, profile):
                return adapter

        raise LookupError("no adapter supports source")
