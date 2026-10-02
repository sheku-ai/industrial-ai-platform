from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

import pytest

from app.services.document_ingestion_status import DocumentIngestionStatusAdapter
from app.services.runtime_cancellation import RuntimeCancellationRequested
from app.services.runtime_lease import RuntimeLeaseLost
from app.services.runtime_worker import RuntimeAdapterResult, RuntimeWorkItem
from tests.integration_support.fault_injection import FaultInjectingHeartbeat


class RecordingStatusService:
    def __init__(self) -> None:
        self.transitions: list[str] = []

    def mark_processing(self, *args, **kwargs):
        self.transitions.append("processing")

    def mark_indexed(self, *args, **kwargs):
        self.transitions.append("indexed")

    def mark_failed(self, *args, **kwargs):
        self.transitions.append("failed")

    def mark_cancelled(self, *args, **kwargs):
        self.transitions.append("cancelled")


class SuccessfulDelegate:
    def __init__(self) -> None:
        self.calls = 0

    def execute(self, item, heartbeat):
        self.calls += 1
        return RuntimeAdapterResult(metrics={"chunks": 2})


@dataclass
class PublishedArtifact:
    artifact_id: object
    storage_uri: str
    checksum_sha256: str
    size_bytes: int


class RecordingPublisher:
    def __init__(self) -> None:
        self.calls = 0

    def publish(self, **kwargs):
        self.calls += 1
        return PublishedArtifact(
            artifact_id=uuid4(),
            storage_uri="s3://integration/manifest.json",
            checksum_sha256="a" * 64,
            size_bytes=42,
        )


def build_item() -> RuntimeWorkItem:
    return RuntimeWorkItem(
        organization_id=uuid4(),
        execution_id=uuid4(),
        execution_type="document.ingestion",
        subject_type="document.version",
        subject_id=uuid4(),
        attempt_id=uuid4(),
        attempt_number=1,
        lease_token=uuid4(),
        input_payload={"document_id": str(uuid4())},
        policy_snapshot={},
    )


def test_cancellation_before_publication_prevents_object_write_and_marks_cancelled():
    status = RecordingStatusService()
    delegate = SuccessfulDelegate()
    publisher = RecordingPublisher()
    heartbeat = FaultInjectingHeartbeat(
        fail_at=2,
        exception=RuntimeCancellationRequested("cancel before publication"),
    )
    adapter = DocumentIngestionStatusAdapter(delegate, status, publisher)

    with pytest.raises(RuntimeCancellationRequested):
        adapter.execute(build_item(), heartbeat)

    assert delegate.calls == 1
    assert publisher.calls == 0
    assert status.transitions == ["processing", "cancelled"]


def test_lease_loss_before_publication_prevents_object_write_without_false_terminal_status():
    status = RecordingStatusService()
    delegate = SuccessfulDelegate()
    publisher = RecordingPublisher()
    heartbeat = FaultInjectingHeartbeat(
        fail_at=2,
        exception=RuntimeLeaseLost("lease lost before publication"),
    )
    adapter = DocumentIngestionStatusAdapter(delegate, status, publisher)

    with pytest.raises(RuntimeLeaseLost):
        adapter.execute(build_item(), heartbeat)

    assert delegate.calls == 1
    assert publisher.calls == 0
    assert status.transitions == ["processing"]


def test_cancellation_after_object_write_prevents_indexed_projection():
    status = RecordingStatusService()
    delegate = SuccessfulDelegate()
    publisher = RecordingPublisher()
    heartbeat = FaultInjectingHeartbeat(
        fail_at=3,
        exception=RuntimeCancellationRequested("cancel after publication"),
    )
    adapter = DocumentIngestionStatusAdapter(delegate, status, publisher)

    with pytest.raises(RuntimeCancellationRequested):
        adapter.execute(build_item(), heartbeat)

    assert publisher.calls == 1
    assert status.transitions == ["processing", "cancelled"]


def test_lease_loss_after_object_write_prevents_indexed_and_failed_projection():
    status = RecordingStatusService()
    delegate = SuccessfulDelegate()
    publisher = RecordingPublisher()
    heartbeat = FaultInjectingHeartbeat(
        fail_at=3,
        exception=RuntimeLeaseLost("lease lost after publication"),
    )
    adapter = DocumentIngestionStatusAdapter(delegate, status, publisher)

    with pytest.raises(RuntimeLeaseLost):
        adapter.execute(build_item(), heartbeat)

    assert publisher.calls == 1
    assert status.transitions == ["processing"]
