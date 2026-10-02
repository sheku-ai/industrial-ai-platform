from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services.document_ingestion_status import DocumentIngestionStatusAdapter
from app.services.runtime_cancellation import RuntimeCancellationRequested
from app.services.runtime_lease import RuntimeLeaseLost
from app.services.runtime_worker import RuntimeAdapterResult


class StatusService:
    def __init__(self):
        self.calls = []

    def mark_processing(self, *args, **kwargs):
        self.calls.append("processing")

    def mark_indexed(self, *args, **kwargs):
        self.calls.append("indexed")

    def mark_failed(self, *args, **kwargs):
        self.calls.append("failed")

    def mark_cancelled(self, *args, **kwargs):
        self.calls.append("cancelled")


class Delegate:
    def __init__(self, calls):
        self.calls = calls

    def execute(self, item, heartbeat):
        self.calls.append("delegate")
        return RuntimeAdapterResult(metrics={"content_units": 2})


class Publisher:
    def __init__(self, calls):
        self.calls = calls

    def publish(self, **kwargs):
        self.calls.append("publish")
        return SimpleNamespace(
            artifact_id=uuid4(),
            storage_uri="object://artifacts/manifest.json",
            checksum_sha256="a" * 64,
            size_bytes=12,
        )


class Heartbeat:
    def __init__(self, outcomes=None):
        self.outcomes = list(outcomes or [])
        self.calls = 0

    def checkpoint(self):
        self.calls += 1
        if self.outcomes:
            outcome = self.outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome


@pytest.fixture
def item():
    document_id = uuid4()
    document_version_id = uuid4()
    return SimpleNamespace(
        organization_id=uuid4(),
        execution_id=uuid4(),
        attempt_id=uuid4(),
        attempt_number=1,
        subject_id=document_version_id,
        subject_type="document_version",
        execution_type="document.ingestion",
        input_payload={"document_id": document_id},
    )


def test_checkpoint_precedes_processing_publication_and_indexed_status(item):
    calls = []
    status = StatusService()
    heartbeat = Heartbeat()
    adapter = DocumentIngestionStatusAdapter(
        Delegate(calls),
        status,
        artifact_publisher=Publisher(calls),
    )

    result = adapter.execute(item, heartbeat)

    assert heartbeat.calls == 3
    assert calls == ["delegate", "publish"]
    assert status.calls == ["processing", "indexed"]
    assert result.metrics["artifact_publication_connected"] is True


def test_cancellation_before_artifact_publication_blocks_publish_and_marks_cancelled(item):
    calls = []
    status = StatusService()
    heartbeat = Heartbeat([None, RuntimeCancellationRequested("cancel")])
    adapter = DocumentIngestionStatusAdapter(
        Delegate(calls),
        status,
        artifact_publisher=Publisher(calls),
    )

    with pytest.raises(RuntimeCancellationRequested):
        adapter.execute(item, heartbeat)

    assert "publish" not in calls
    assert status.calls == ["processing", "cancelled"]


def test_lease_loss_before_artifact_publication_blocks_all_terminal_status_mutations(item):
    calls = []
    status = StatusService()
    heartbeat = Heartbeat([None, RuntimeLeaseLost("lost")])
    adapter = DocumentIngestionStatusAdapter(
        Delegate(calls),
        status,
        artifact_publisher=Publisher(calls),
    )

    with pytest.raises(RuntimeLeaseLost):
        adapter.execute(item, heartbeat)

    assert "publish" not in calls
    assert status.calls == ["processing"]
    assert "failed" not in status.calls
    assert "indexed" not in status.calls


def test_lease_loss_after_publication_prevents_indexed_status(item):
    calls = []
    status = StatusService()
    heartbeat = Heartbeat([None, None, RuntimeLeaseLost("lost after publish")])
    adapter = DocumentIngestionStatusAdapter(
        Delegate(calls),
        status,
        artifact_publisher=Publisher(calls),
    )

    with pytest.raises(RuntimeLeaseLost):
        adapter.execute(item, heartbeat)

    assert calls == ["delegate", "publish"]
    assert status.calls == ["processing"]
