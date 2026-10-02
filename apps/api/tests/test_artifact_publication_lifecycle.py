from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.models.artifact_publication import RuntimeArtifactPublication
from app.services.artifact_publication_lifecycle import (
    ArtifactPublicationConflictError,
    ArtifactPublicationLifecycleService,
    ArtifactPublicationNotFoundError,
)


class FakeSession:
    def __init__(self, artifact=None, publications=None, next_number=1):
        self.artifact = artifact
        self.publications = {item.id: item for item in publications or []}
        self.next_number = next_number
        self.added = []
        self.flush_count = 0
        self.scalar_calls = 0

    def scalar(self, statement):
        self.scalar_calls += 1
        if self.scalar_calls == 1 and self.artifact is not None:
            return self.artifact
        if self.scalar_calls == 2 and self.artifact is not None:
            return self.next_number
        for publication in self.publications.values():
            return publication
        return None

    def add(self, value):
        self.added.append(value)
        if isinstance(value, RuntimeArtifactPublication):
            value.id = value.id or uuid4()
            self.publications[value.id] = value

    def flush(self):
        self.flush_count += 1


def test_reserve_creates_new_immutable_publication_attempt():
    organization_id = uuid4()
    execution_id = uuid4()
    artifact_id = uuid4()
    attempt_id = uuid4()
    session = FakeSession(
        artifact=SimpleNamespace(id=artifact_id),
        next_number=3,
    )
    service = ArtifactPublicationLifecycleService(session)

    publication = service.reserve(
        organization_id=organization_id,
        execution_id=execution_id,
        artifact_id=artifact_id,
        attempt_id=attempt_id,
        storage_uri="s3://bucket/object",
        media_type="application/json",
        checksum_sha256="a" * 64,
        size_bytes=12,
        metadata={"logical_name": "manifest"},
    )

    assert publication.publication_number == 3
    assert publication.status == "reserved"
    assert publication.storage_uri == "s3://bucket/object"
    assert publication.metadata_ == {"logical_name": "manifest"}
    assert session.flush_count == 1


def test_reserve_rejects_missing_logical_artifact():
    service = ArtifactPublicationLifecycleService(FakeSession())

    with pytest.raises(ArtifactPublicationNotFoundError):
        service.reserve(
            organization_id=uuid4(),
            execution_id=uuid4(),
            artifact_id=uuid4(),
            attempt_id=None,
            storage_uri="s3://bucket/object",
        )


def test_publication_transitions_to_verified():
    publication = RuntimeArtifactPublication(
        organization_id=uuid4(),
        execution_id=uuid4(),
        artifact_id=uuid4(),
        attempt_id=uuid4(),
        publication_number=1,
        storage_uri="s3://bucket/object",
        status="reserved",
        metadata_={},
    )
    publication.id = uuid4()
    session = FakeSession(publications=[publication])
    service = ArtifactPublicationLifecycleService(session)

    service.mark_publishing(publication.organization_id, publication.id)
    assert publication.status == "publishing"

    published_at = datetime(2026, 6, 19, 12, 0, tzinfo=UTC)
    service.mark_published(
        publication.organization_id,
        publication.id,
        published_at=published_at,
    )
    assert publication.status == "published"
    assert publication.published_at == published_at

    verified_at = datetime(2026, 6, 19, 12, 1, tzinfo=UTC)
    service.mark_verified(
        publication.organization_id,
        publication.id,
        verified_at=verified_at,
    )
    assert publication.status == "verified"
    assert publication.verified_at == verified_at


def test_terminal_publication_cannot_be_rewritten():
    publication = RuntimeArtifactPublication(
        organization_id=uuid4(),
        execution_id=uuid4(),
        artifact_id=uuid4(),
        attempt_id=None,
        publication_number=1,
        storage_uri="s3://bucket/object",
        status="failed",
        metadata_={},
    )
    publication.id = uuid4()
    service = ArtifactPublicationLifecycleService(FakeSession(publications=[publication]))

    with pytest.raises(ArtifactPublicationConflictError, match="immutable"):
        service.mark_publishing(publication.organization_id, publication.id)


def test_verification_cannot_precede_publication():
    published_at = datetime(2026, 6, 19, 12, 0, tzinfo=UTC)
    publication = RuntimeArtifactPublication(
        organization_id=uuid4(),
        execution_id=uuid4(),
        artifact_id=uuid4(),
        attempt_id=None,
        publication_number=1,
        storage_uri="s3://bucket/object",
        status="published",
        published_at=published_at,
        metadata_={},
    )
    publication.id = uuid4()
    service = ArtifactPublicationLifecycleService(FakeSession(publications=[publication]))

    with pytest.raises(ArtifactPublicationConflictError, match="cannot precede"):
        service.mark_verified(
            publication.organization_id,
            publication.id,
            verified_at=datetime(2026, 6, 19, 11, 59, tzinfo=UTC),
        )
