from __future__ import annotations

import importlib
import os
from collections.abc import Callable

from app.services.protected_document_composition import compose_protected_document_adapter
from app.services.runtime_worker import RuntimeAdapterRegistry
from app.services.secret_store_runtime import get_secret_store


class RuntimeRegistryConfigurationError(RuntimeError):
    pass


def _load_adapter_factory(path: str) -> Callable:
    module_name, separator, attribute_name = path.partition(":")
    if not separator or not module_name or not attribute_name:
        raise RuntimeRegistryConfigurationError("DOCUMENT_INGESTION_ADAPTER_FACTORY must use module:function syntax")
    module = importlib.import_module(module_name)
    factory = getattr(module, attribute_name, None)
    if not callable(factory):
        raise RuntimeRegistryConfigurationError("document ingestion adapter factory is not callable")
    return factory


def build_runtime_adapter_registry(*, session_factory) -> RuntimeAdapterRegistry:
    default_factory = "app.workers.document_ingestion_factory:build_document_ingestion_adapter"
    factory_path = os.getenv("DOCUMENT_INGESTION_ADAPTER_FACTORY") or default_factory
    delegate = _load_adapter_factory(factory_path)(session_factory=session_factory)
    if getattr(delegate, "execution_type", None) != "document.ingestion":
        raise RuntimeRegistryConfigurationError("configured adapter does not implement document.ingestion")

    protected_adapter = compose_protected_document_adapter(
        delegate,
        secret_store=get_secret_store(),
        session_factory=session_factory,
    )
    registry = RuntimeAdapterRegistry()
    registry.register(protected_adapter)
    return registry
