import pytest

from app.services.runtime_worker import RuntimeAdapterRegistry, RuntimeAdapterResult
from app.workers import runtime_ingestion_worker
from app.workers.runtime_registry import build_runtime_adapter_registry


class Delegate:
    execution_type = "document.ingestion"

    def execute(self, item, heartbeat):
        return RuntimeAdapterResult(metrics={})


def test_runtime_registry_uses_default_production_factory(monkeypatch) -> None:
    monkeypatch.delenv("DOCUMENT_INGESTION_ADAPTER_FACTORY", raising=False)
    captured = {}

    def fake_loader(path):
        captured["path"] = path
        return lambda *, session_factory: Delegate()

    monkeypatch.setattr("app.workers.runtime_registry._load_adapter_factory", fake_loader)
    registry = build_runtime_adapter_registry(session_factory=lambda: None)

    assert captured["path"] == "app.workers.document_ingestion_factory:build_document_ingestion_adapter"
    assert registry.resolve("document.ingestion") is not None


def test_worker_rejects_registry_without_document_ingestion(monkeypatch) -> None:
    monkeypatch.setenv(
        "RUNTIME_ADAPTER_REGISTRY_FACTORY", "tests.test_runtime_ingestion_worker_entrypoint:empty_registry"
    )

    with pytest.raises(runtime_ingestion_worker.RuntimeWorkerConfigurationError, match="not registered"):
        runtime_ingestion_worker.build_registry()


def empty_registry(*, session_factory):
    del session_factory
    return RuntimeAdapterRegistry()
