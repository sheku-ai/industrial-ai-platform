from types import SimpleNamespace
from uuid import uuid4

from app.services.artifact_reconciliation import ArtifactObjectMetadata
from app.services.artifact_unregistered_object import ArtifactUnregisteredObjectService


class SessionStub:
    def __init__(self, existing=None):
        self.existing = existing

    def scalar(self, statement):
        return self.existing


class LifecycleStub:
    def __init__(self, existing=None):
        self.session = SessionStub(existing)
        self.calls = []
        self.publication = None

    def reserve(self, **kwargs):
        self.calls.append(("reserve", kwargs))
        self.publication = SimpleNamespace(id=uuid4())
        return self.publication

    def mark_publishing(self, organization_id, publication_id):
        self.calls.append(("publishing", publication_id))

    def mark_published(self, organization_id, publication_id):
        self.calls.append(("published", publication_id))

    def mark_verified(self, organization_id, publication_id):
        self.calls.append(("verified", publication_id))


class StoreStub:
    def __init__(self, metadata):
        self.metadata = metadata

    def stat(self, storage_uri):
        return self.metadata


def test_existing_object_creates_verified_publication():
    lifecycle = LifecycleStub()
    service = ArtifactUnregisteredObjectService(
        lifecycle,
        StoreStub(ArtifactObjectMetadata(size_bytes=3, checksum_sha256="a" * 64, media_type="text/plain")),
    )

    result = service.register(
        organization_id=uuid4(),
        execution_id=uuid4(),
        artifact_id=uuid4(),
        attempt_id=None,
        storage_uri="s3://bucket/object.txt",
    )

    assert result.outcome == "verified"
    assert result.changed is True
    assert [name for name, _ in lifecycle.calls] == ["reserve", "publishing", "published", "verified"]
    reserve_payload = lifecycle.calls[0][1]
    assert reserve_payload["checksum_sha256"] == "a" * 64
    assert reserve_payload["size_bytes"] == 3
    assert reserve_payload["metadata"] == {"reconciled_from_object": True}


def test_matching_verified_publication_is_reused():
    existing = SimpleNamespace(id=uuid4())
    lifecycle = LifecycleStub(existing)
    service = ArtifactUnregisteredObjectService(
        lifecycle,
        StoreStub(ArtifactObjectMetadata(size_bytes=3, checksum_sha256="a" * 64)),
    )

    result = service.register(
        organization_id=uuid4(),
        execution_id=uuid4(),
        artifact_id=uuid4(),
        attempt_id=None,
        storage_uri="s3://bucket/object.txt",
    )

    assert result.publication_id == existing.id
    assert result.changed is False
    assert lifecycle.calls == []


def test_missing_object_does_not_create_publication():
    lifecycle = LifecycleStub()
    service = ArtifactUnregisteredObjectService(lifecycle, StoreStub(None))

    result = service.register(
        organization_id=uuid4(),
        execution_id=uuid4(),
        artifact_id=uuid4(),
        attempt_id=None,
        storage_uri="s3://bucket/missing.txt",
    )

    assert result.outcome == "object_missing"
    assert result.publication_id is None
    assert result.changed is False
    assert lifecycle.calls == []
