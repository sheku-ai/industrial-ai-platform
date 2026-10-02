from pathlib import Path

from app.services.checkpoint_runtime_worker import CheckpointRuntimeWorker
from app.services.document_ingestion_runtime_adapter import DocumentIngestionRuntimeAdapter
from app.services.document_ingestion_status import DocumentIngestionStatusAdapter, DocumentVersionStatusService
from app.services.ingestion_adapter_resolver import IngestionAdapterResolver
from app.services.ingestion_adapters.ndjson import NdjsonIngestionAdapter
from app.services.ingestion_adapters.pdf import PdfIngestionAdapter
from app.services.ingestion_adapters.spreadsheet import SpreadsheetIngestionAdapter
from app.services.ingestion_adapters.text import PlainTextIngestionAdapter
from app.services.ingestion_pipeline import IngestionPipelineCoordinator
from app.services.runtime_worker import RuntimeAdapterRegistry
from app.services.session_ingestion import SessionIngestionConfigurationService, SessionIngestionPostProcessingService
from app.services.source_acquisition import SourceObjectReader, WorkspaceSourceAcquisitionService


def build_artifact_checkpoint_worker(
    session_factory,
    reader: SourceObjectReader,
    artifact_publisher,
    *,
    worker_id: str,
    workspace_root: Path,
    max_source_bytes: int = 1_000_000_000,
) -> CheckpointRuntimeWorker:
    pipeline = IngestionPipelineCoordinator(
        IngestionAdapterResolver(
            [
                PlainTextIngestionAdapter(),
                PdfIngestionAdapter(),
                SpreadsheetIngestionAdapter(),
                NdjsonIngestionAdapter(),
            ]
        )
    )
    ingestion = DocumentIngestionRuntimeAdapter(
        WorkspaceSourceAcquisitionService(
            reader,
            workspace_root,
            max_source_bytes=max_source_bytes,
        ),
        SessionIngestionConfigurationService(session_factory),
        pipeline,
        SessionIngestionPostProcessingService(session_factory),
    )
    adapter = DocumentIngestionStatusAdapter(
        ingestion,
        DocumentVersionStatusService(session_factory),
        artifact_publisher=artifact_publisher,
    )
    registry = RuntimeAdapterRegistry()
    registry.register(adapter)
    return CheckpointRuntimeWorker(
        session_factory,
        registry,
        worker_id=worker_id,
    )
