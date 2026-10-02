from types import SimpleNamespace
from uuid import uuid4

from app.services.artifact_reconciliation import (
    ArtifactObjectMetadata,
    ArtifactReconciliationService,
)


class FakeLifecycle:
    def __init__(self, publication):
        self.publication = publication
        self.reserved = []
        self.terminal = []
        self.verified = []
        self.published = []

    def get(self, organization_id, publication_id, for_update=False):
        if organization_id == self.publication.organization_id and publication_id == self.publication.id:
            return self.publication
        for item in self.reserved:
            if item.id == publication_id:
                return item
        return None

    def reserve(self, **kwargs):
        item = SimpleNamespace(
            id=uuid4(),
            organization_id=kwargs["organization_id"],
            execution_id=kwargs["execution_id"],
            artifact_id=kwargs["artifact_id"],
            attempt_id=kwargs["attempt_id"],
            storage_uri=kwargs["storage_uri"],
            media_type=kwargs.get("media_type"),
            checksum_sha256=kwargs.get("checksum_sha256"),
            size_bytes=kwargs.get("size_bytes"),
            status="reserved",
        )
        self.reserved.append(item)
        return item

    def mark_terminal(self, organization_id, publication_id, *, status, error_code=None):
        item = self.get(organization_id, publication_id)
        item.status = status
        self.terminal.append((publication_id, status))
        return item

    def mark_published(self, organization_id, publication_id):
        item = self.get(organization_id, publication_id)
        item.status = "published"
        self.published.append(publication_id)
        return item

    def mark_verified(self, organization_id, publication_id):
        item = self.get(organization_id, publication_id)
        item.status = "verified"
        self.verified.append(publication_id)
        return item


class FakeStore:
    def __init__(self, metadata):
        self.metadata = metadata
        self.uris = []

    def stat(self, storage_uri):
        self.uris.append(storage_uri)
        return self.metadata


def _publication(status="published", checksum="a" * 64, size=10):
    return SimpleNamespace(
        id=uuid4(),
        organization_id=uuid4(),
        execution_id=uuid4(),
        artifact_id=uuid4(),
        attempt_id=uuid4(),
        storage_uri="s3://bucket/object",
        media_type="application/json",
        checksum_sha256=checksum,
        size_bytes=size,
        status=status,
    )


def test_published_object_is_verified_when_metadata_matches():
    publication = _publication()
    lifecycle = FakeLifecycle(publication)
    service = ArtifactReconciliationService(
        lifecycle,
        FakeStore(ArtifactObjectMetadata(size_bytes=10, checksum_sha256="a" * 64)),
    )

    result = service.reconcile(publication.organization_id, publication.id)

    assert result.outcome == "verified"
    assert result.resulting_publication_id == publication.id
    assert result.changed is True
    assert lifecycle.verified == [publication.id]


def test_missing_terminal_publication_creates_reconciliation_attempt():
    publication = _publication(status="verified")
    lifecycle = FakeLifecycle(publication)
    service = ArtifactReconciliationService(lifecycle, FakeStore(None))

    result = service.reconcile(publication.organization_id, publication.id)

    assert result.outcome == "missing"
    assert result.changed is True
    assert result.resulting_publication_id != publication.id
    assert len(lifecycle.reserved) == 1
    assert lifecycle.terminal == [(result.resulting_publication_id, "missing")]


def test_active_missing_publication_is_closed_in_place():
    publication = _publication(status="publishing")
    lifecycle = FakeLifecycle(publication)
    service = ArtifactReconciliationService(lifecycle, FakeStore(None))

    result = service.reconcile(publication.organization_id, publication.id)

    assert result.resulting_publication_id == publication.id
    assert result.changed is True
    assert publication.status == "missing"


def test_checksum_conflict_creates_immutable_finding():
    publication = _publication(status="verified")
    lifecycle = FakeLifecycle(publication)
    service = ArtifactReconciliationService(
        lifecycle,
        FakeStore(ArtifactObjectMetadata(size_bytes=10, checksum_sha256="b" * 64)),
    )

    result = service.reconcile(publication.organization_id, publication.id)

    assert result.outcome == "checksum_conflict"
    assert result.resulting_publication_id != publication.id
    assert lifecycle.terminal == [(result.resulting_publication_id, "checksum_conflict")]


def test_verified_matching_publication_is_idempotent():
    publication = _publication(status="verified")
    lifecycle = FakeLifecycle(publication)
    service = ArtifactReconciliationService(
        lifecycle,
        FakeStore(ArtifactObjectMetadata(size_bytes=10, checksum_sha256="a" * 64)),
    )

    result = service.reconcile(publication.organization_id, publication.id)

    assert result.outcome == "verified"
    assert result.changed is False
    assert lifecycle.verified == []


def test_missing_finding_is_idempotent():
    publication = _publication(status="missing")
    lifecycle = FakeLifecycle(publication)
    service = ArtifactReconciliationService(lifecycle, FakeStore(None))

    result = service.reconcile(publication.organization_id, publication.id)

    assert result.outcome == "missing"
    assert result.changed is False
    assert result.resulting_publication_id == publication.id
    assert lifecycle.reserved == []


def test_checksum_conflict_finding_is_idempotent():
    publication = _publication(status="checksum_conflict")
    lifecycle = FakeLifecycle(publication)
    service = ArtifactReconciliationService(
        lifecycle,
        FakeStore(ArtifactObjectMetadata(size_bytes=10, checksum_sha256="b" * 64)),
    )

    result = service.reconcile(publication.organization_id, publication.id)

    assert result.outcome == "checksum_conflict"
    assert result.changed is False
    assert result.resulting_publication_id == publication.id
    assert lifecycle.reserved == []
