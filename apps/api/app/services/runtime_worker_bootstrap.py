from datetime import timedelta

from app.services.document_ingestion_bootstrap import build_document_ingestion_runtime_adapter
from app.services.runtime_worker import RuntimeAdapterRegistry, RuntimeWorkerService


def build_runtime_worker_service(
    session,
    session_factory,
    worker_id,
    acquisition,
    configuration,
    pipeline,
    lexical_repository_factory,
    lease_duration=timedelta(minutes=5),
    heartbeat_extension=timedelta(minutes=5),
):
    if not isinstance(worker_id, str) or not worker_id.strip():
        raise ValueError("worker_id is required")
    registry = RuntimeAdapterRegistry()
    registry.register(
        build_document_ingestion_runtime_adapter(
            acquisition=acquisition,
            configuration=configuration,
            pipeline=pipeline,
            session_factory=session_factory,
            lexical_repository_factory=lexical_repository_factory,
        )
    )
    return RuntimeWorkerService(
        session,
        registry,
        worker_id=worker_id.strip(),
        lease_duration=lease_duration,
        heartbeat_extension=heartbeat_extension,
    )
