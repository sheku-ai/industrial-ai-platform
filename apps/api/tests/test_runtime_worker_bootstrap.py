from datetime import timedelta

import pytest

from app.services.document_ingestion_runtime_adapter import DocumentIngestionRuntimeAdapter
from app.services.runtime_worker import RuntimeWorkerService
from app.services.runtime_worker_bootstrap import build_runtime_worker_service


def test_worker_bootstrap_registers_document_ingestion_adapter():
    worker = build_runtime_worker_service(
        session=object(),
        session_factory=lambda: object(),
        worker_id="worker-1",
        acquisition=object(),
        configuration=object(),
        pipeline=object(),
        lexical_repository_factory=lambda session: object(),
        lease_duration=timedelta(minutes=2),
        heartbeat_extension=timedelta(minutes=3),
    )

    assert isinstance(worker, RuntimeWorkerService)
    adapter = worker.registry.resolve("document.ingestion")
    assert isinstance(adapter, DocumentIngestionRuntimeAdapter)
    assert worker.worker_id == "worker-1"
    assert worker.lease_duration == timedelta(minutes=2)
    assert worker.heartbeat_extension == timedelta(minutes=3)


def test_worker_bootstrap_rejects_blank_worker_id():
    with pytest.raises(ValueError, match="worker_id is required"):
        build_runtime_worker_service(
            session=object(),
            session_factory=lambda: object(),
            worker_id="   ",
            acquisition=object(),
            configuration=object(),
            pipeline=object(),
            lexical_repository_factory=lambda session: object(),
        )
