from pathlib import Path

from sqlalchemy.orm import Session

from app.repositories.document_ingestion import SqlAlchemyDocumentIngestionRepository
from app.repositories.ingestion_configuration import SqlAlchemyIngestionConfigurationRepository
from app.services.checkpoint_runtime_worker import CheckpointRuntimeWorker
from app.services.document_content_persistence import DocumentContentPersistenceService
from app.services.document_ingestion_runtime_adapter import DocumentIngestionRuntimeAdapter
from app.services.document_ingestion_status import (
    DocumentIngestionStatusAdapter,
    DocumentVersionStatusService,
)
from app.services.ingestion_adapter_resolver import IngestionAdapterResolver
from app.services.ingestion_adapters.ndjson import NdjsonIngestionAdapter
from app.services.ingestion_adapters.pdf import PdfIngestionAdapter
from app.services.ingestion_adapters.spreadsheet import SpreadsheetIngestionAdapter
from app.services.ingestion_adapters.text import PlainTextIngestionAdapter
from app.services.ingestion_configuration import IngestionConfigurationService
from app.services.ingestion_pipeline import IngestionPipelineCoordinator
from app.services.ingestion_post_processing import IngestionPostProcessingService
from app.services.lexical_indexing import LexicalIndexService
from app.services.runtime_worker import RuntimeAdapterRegistry, RuntimeWorkerService
from app.services.session_ingestion import SessionIngestionConfigurationService, SessionIngestionPostProcessingService
from app.services.source_acquisition import SourceObjectReader, WorkspaceSourceAcquisitionService


def _pipeline():
    return IngestionPipelineCoordinator(
        IngestionAdapterResolver(
            [
                PlainTextIngestionAdapter(),
                PdfIngestionAdapter(),
                SpreadsheetIngestionAdapter(),
                NdjsonIngestionAdapter(),
            ]
        )
    )


def build_registry(
    session: Session, reader: SourceObjectReader, workspace_root: Path, max_source_bytes: int = 1_000_000_000
) -> RuntimeAdapterRegistry:
    repository = SqlAlchemyDocumentIngestionRepository(session)
    adapter = DocumentIngestionRuntimeAdapter(
        WorkspaceSourceAcquisitionService(reader, workspace_root, max_source_bytes=max_source_bytes),
        IngestionConfigurationService(SqlAlchemyIngestionConfigurationRepository(session)),
        _pipeline(),
        IngestionPostProcessingService(DocumentContentPersistenceService(repository), LexicalIndexService(repository)),
    )
    registry = RuntimeAdapterRegistry()
    registry.register(adapter)
    return registry


def build_worker(
    session: Session,
    reader: SourceObjectReader,
    worker_id: str,
    workspace_root: Path,
    max_source_bytes: int = 1_000_000_000,
) -> RuntimeWorkerService:
    return RuntimeWorkerService(
        session, build_registry(session, reader, workspace_root, max_source_bytes), worker_id=worker_id
    )


def build_checkpoint_registry(
    session_factory, reader: SourceObjectReader, workspace_root: Path, max_source_bytes: int = 1_000_000_000
) -> RuntimeAdapterRegistry:
    ingestion_adapter = DocumentIngestionRuntimeAdapter(
        WorkspaceSourceAcquisitionService(reader, workspace_root, max_source_bytes=max_source_bytes),
        SessionIngestionConfigurationService(session_factory),
        _pipeline(),
        SessionIngestionPostProcessingService(session_factory),
    )
    adapter = DocumentIngestionStatusAdapter(
        ingestion_adapter,
        DocumentVersionStatusService(session_factory),
    )
    registry = RuntimeAdapterRegistry()
    registry.register(adapter)
    return registry


def build_checkpoint_worker(
    session_factory,
    reader: SourceObjectReader,
    worker_id: str,
    workspace_root: Path,
    max_source_bytes: int = 1_000_000_000,
) -> CheckpointRuntimeWorker:
    return CheckpointRuntimeWorker(
        session_factory,
        build_checkpoint_registry(session_factory, reader, workspace_root, max_source_bytes),
        worker_id=worker_id,
    )
