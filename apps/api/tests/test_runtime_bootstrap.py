from io import BytesIO

from app.services.source_acquisition import SourceObjectDescriptor
from app.workers.bootstrap_runtime import build_registry, build_worker


class Reader:
    def describe(self, organization_id, source_reference):
        return SourceObjectDescriptor(
            source_reference=source_reference,
            media_type="text/plain",
            content_length=0,
            checksum_sha256="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            file_name="source.txt",
        )

    def open_stream(self, organization_id, source_reference):
        return BytesIO(b"")


class Session:
    pass


def test_registry_contains_ingestion_adapter(tmp_path):
    registry = build_registry(Session(), Reader(), tmp_path)
    adapter = registry.resolve("document.ingestion")
    assert adapter is not None
    assert adapter.execution_type == "document.ingestion"


def test_worker_uses_registry(tmp_path):
    session = Session()
    worker = build_worker(session, Reader(), "worker-1", tmp_path)
    assert worker.session is session
    assert worker.worker_id == "worker-1"
    assert worker.registry.resolve("document.ingestion") is not None


def test_bootstrap_has_no_provider_state(tmp_path):
    adapter = build_registry(Session(), Reader(), tmp_path).resolve("document.ingestion")
    assert not hasattr(adapter, "provider")
    assert not hasattr(adapter, "embedding_model")
    assert not hasattr(adapter, "vector_store")
