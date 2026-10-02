from app.services.document_ingestion_status import DocumentIngestionStatusAdapter
from app.services.ocr_transient_ingestion_pipeline import OcrTransientOptionIngestionPipelineCoordinator
from app.workers import document_ingestion_factory


class Stub:
    def __init__(self, *args, **kwargs):
        pass


def test_factory_builds_status_wrapped_runtime_adapter(monkeypatch):
    monkeypatch.setattr(document_ingestion_factory, "S3SourceAcquisitionService", Stub)
    monkeypatch.setattr(document_ingestion_factory, "SqlAlchemyIngestionProfileRepository", Stub)
    monkeypatch.setattr(document_ingestion_factory, "RuntimeDocumentContentRepository", Stub)
    monkeypatch.setattr(document_ingestion_factory, "RuntimeLexicalIndexRepository", Stub)
    monkeypatch.setattr(document_ingestion_factory, "ProcessingManifestPublicationService", Stub)
    monkeypatch.setattr(document_ingestion_factory, "VisualEnrichmentPublicationService", Stub)
    monkeypatch.setattr(document_ingestion_factory, "_build_object_storage_client", Stub)

    adapter = document_ingestion_factory.build_document_ingestion_adapter(
        session_factory=lambda: None
    )

    assert isinstance(adapter, DocumentIngestionStatusAdapter)
    runtime_adapter = adapter
    while hasattr(runtime_adapter, "_delegate"):
        runtime_adapter = runtime_adapter._delegate
    assert isinstance(runtime_adapter._pipeline, OcrTransientOptionIngestionPipelineCoordinator)
    assert runtime_adapter._pipeline._resolver.registered_adapter_keys() == (
        "platform.pdf.text_layer",
        "platform.text.plain",
    )
