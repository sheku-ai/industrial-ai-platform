from __future__ import annotations

from app.services.protected_document_detection_adapter import ProtectedDocumentDetectionAdapter
from app.services.runtime_worker import RuntimeAdapterRegistry
from app.workers.runtime_registry import build_runtime_adapter_registry as build_base_registry


def build_review_detection_registry(*, session_factory):
    base = build_base_registry(session_factory=session_factory)
    current = base.resolve("document.ingestion")
    if current is None:
        raise RuntimeError("document ingestion adapter is unavailable")
    registry = RuntimeAdapterRegistry()
    registry.register(ProtectedDocumentDetectionAdapter(current, session_factory=session_factory))
    return registry
