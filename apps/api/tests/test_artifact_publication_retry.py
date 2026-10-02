from types import SimpleNamespace
from uuid import uuid4

from app.services.artifact_publication_retry import ArtifactPublicationRetryService


class SessionStub:
    def __init__(self, value=None):
        self.value = value

    def scalar(self, statement):
        return self.value


class LifecycleStub:
    def __init__(self, value=None):
        self.session = SessionStub(value)
        self.calls = []

    def reserve(self, **kwargs):
        item = SimpleNamespace(id=uuid4())
        self.calls.append(kwargs)
        return item


def make_args():
    return dict(
        organization_id=uuid4(),
        execution_id=uuid4(),
        artifact_id=uuid4(),
        attempt_id=None,
        storage_uri="s3://bucket/object.json",
        media_type="application/json",
        checksum_sha256="a" * 64,
        size_bytes=10,
        metadata={"retry": True},
    )


def test_reuses_matching_publication():
    existing = SimpleNamespace(id=uuid4())
    lifecycle = LifecycleStub(existing)
    result = ArtifactPublicationRetryService(lifecycle).resolve_or_reserve(**make_args())

    assert result.publication_id == existing.id
    assert result.reused is True
    assert lifecycle.calls == []


def test_reserves_when_no_matching_publication_exists():
    lifecycle = LifecycleStub()
    result = ArtifactPublicationRetryService(lifecycle).resolve_or_reserve(**make_args())

    assert result.reused is False
    assert len(lifecycle.calls) == 1
