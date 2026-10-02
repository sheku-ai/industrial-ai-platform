from types import SimpleNamespace
from uuid import uuid4

from app.services.document_ingestion_status import DocumentIngestionStatusAdapter
from app.services.ingestion_artifact_publication import SessionIngestionArtifactPublisher
from app.services.runtime_worker import RuntimeAdapterResult


class Writer:
    def __init__(self):
        self.objects = []

    def put(self, **kwargs):
        self.objects.append(kwargs)


class Session:
    def __init__(self):
        self.artifact = None
        self.committed = False
        self.closed = False

    def scalar(self, statement):
        del statement
        return self.artifact

    def add(self, artifact):
        artifact.id = uuid4()
        self.artifact = artifact

    def commit(self):
        self.committed = True

    def rollback(self):
        raise AssertionError("rollback was not expected")

    def close(self):
        self.closed = True


class Status:
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
    def execute(self, item, heartbeat):
        return RuntimeAdapterResult(metrics={"content_units": 2})


class Publisher:
    def publish(self, **kwargs):
        return SimpleNamespace(
            artifact_id=uuid4(),
            storage_uri="s3://documents/runtime/manifest.json",
            checksum_sha256="a" * 64,
            size_bytes=120,
        )


def test_publisher_writes_manifest_and_registers_runtime_artifact():
    session = Session()
    writer = Writer()
    publisher = SessionIngestionArtifactPublisher(
        lambda: session,
        writer,
        bucket="documents",
    )

    result = publisher.publish(
        organization_id=uuid4(),
        execution_id=uuid4(),
        attempt_id=uuid4(),
        document_id=uuid4(),
        document_version_id=uuid4(),
        manifest={"metrics": {"content_units": 1}},
    )

    assert result.storage_uri.startswith("s3://documents/")
    assert len(result.checksum_sha256) == 64
    assert writer.objects[0]["media_type"] == "application/json"
    assert session.artifact.artifact_type == "ingestion.manifest"
    assert session.artifact.status == "published"
    assert session.committed is True
    assert session.closed is True


def test_status_adapter_publishes_before_marking_indexed():
    status = Status()
    adapter = DocumentIngestionStatusAdapter(
        Delegate(),
        status,
        artifact_publisher=Publisher(),
    )
    item = SimpleNamespace(
        organization_id=uuid4(),
        execution_id=uuid4(),
        attempt_id=uuid4(),
        attempt_number=1,
        execution_type="document.ingestion",
        subject_type="document_version",
        subject_id=uuid4(),
        input_payload={"document_id": str(uuid4())},
    )

    result = adapter.execute(item, object())

    assert status.calls == ["processing", "indexed"]
    assert result.metrics["artifact_publication_connected"] is True
    assert result.metrics["artifact_storage_uri"].startswith("s3://")
