from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

from app.services.artifact_retention import ArtifactRetentionService
from app.services.artifact_retention_policy import (
    ArtifactRetentionPolicy,
    ArtifactRetentionPolicyService,
)


class FakeLifecycle:
    def __init__(self, publication):
        self.publication = publication
        self.reserved = []
        self.terminal = []

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
            metadata_=kwargs.get("metadata", {}),
            status="reserved",
        )
        self.reserved.append(item)
        return item

    def mark_terminal(self, organization_id, publication_id, *, status, error_code=None):
        item = self.get(organization_id, publication_id)
        item.status = status
        self.terminal.append((publication_id, status))
        return item


class FakeStore:
    def __init__(self, result=True):
        self.result = result
        self.removed = []

    def remove(self, storage_uri):
        self.removed.append(storage_uri)
        return self.result


class FakeAudit:
    def __init__(self):
        self.records = []

    def record(self, **kwargs):
        self.records.append(kwargs)


def _publication(status="verified", created_at=None):
    return SimpleNamespace(
        id=uuid4(),
        organization_id=uuid4(),
        execution_id=uuid4(),
        artifact_id=uuid4(),
        attempt_id=uuid4(),
        storage_uri="s3://bucket/object",
        media_type="application/json",
        checksum_sha256="a" * 64,
        size_bytes=10,
        status=status,
        created_at=created_at or datetime(2026, 6, 1, tzinfo=UTC),
    )


def test_policy_rejects_legal_hold_and_protected_status():
    service = ArtifactRetentionPolicyService()
    publication = _publication()
    now = datetime(2026, 6, 19, tzinfo=UTC)

    hold = service.evaluate(
        publication,
        ArtifactRetentionPolicy(timedelta(days=1), legal_hold=True),
        now=now,
    )
    assert hold.eligible is False
    assert hold.reason == "legal_hold"

    publication.status = "reconciliation_required"
    protected = service.evaluate(
        publication,
        ArtifactRetentionPolicy(timedelta(days=1)),
        now=now,
    )
    assert protected.reason == "protected_status"


def test_policy_reports_not_due_and_eligible():
    publication = _publication(created_at=datetime(2026, 6, 10, tzinfo=UTC))
    service = ArtifactRetentionPolicyService()
    policy = ArtifactRetentionPolicy(timedelta(days=10))

    not_due = service.evaluate(
        publication,
        policy,
        now=datetime(2026, 6, 19, tzinfo=UTC),
    )
    assert not_due.eligible is False
    assert not_due.reason == "not_due"

    eligible = service.evaluate(
        publication,
        policy,
        now=datetime(2026, 6, 20, tzinfo=UTC),
    )
    assert eligible.eligible is True
    assert eligible.reason == "eligible"


def test_retention_without_object_removal_creates_retained_evidence():
    publication = _publication()
    lifecycle = FakeLifecycle(publication)
    store = FakeStore()
    audit = FakeAudit()
    service = ArtifactRetentionService(lifecycle, store, audit)

    result = service.execute(
        publication.organization_id,
        publication.id,
        ArtifactRetentionPolicy(timedelta(days=1)),
        now=datetime(2026, 6, 19, tzinfo=UTC),
    )

    assert result.outcome == "retained"
    assert result.object_removed is False
    assert len(lifecycle.reserved) == 1
    assert lifecycle.terminal == [(result.evidence_publication_id, "retained")]
    assert store.removed == []
    assert audit.records[0]["outcome"] == "retained"


def test_retention_with_object_removal_creates_deleted_evidence():
    publication = _publication()
    lifecycle = FakeLifecycle(publication)
    store = FakeStore(result=True)
    audit = FakeAudit()
    service = ArtifactRetentionService(lifecycle, store, audit)

    result = service.execute(
        publication.organization_id,
        publication.id,
        ArtifactRetentionPolicy(timedelta(days=1), remove_object=True),
        now=datetime(2026, 6, 19, tzinfo=UTC),
    )

    assert result.outcome == "deleted"
    assert result.object_removed is True
    assert store.removed == [publication.storage_uri]
    assert lifecycle.terminal == [(result.evidence_publication_id, "deleted")]


def test_failed_object_removal_does_not_create_false_evidence():
    publication = _publication()
    lifecycle = FakeLifecycle(publication)
    store = FakeStore(result=False)
    audit = FakeAudit()
    service = ArtifactRetentionService(lifecycle, store, audit)

    result = service.execute(
        publication.organization_id,
        publication.id,
        ArtifactRetentionPolicy(timedelta(days=1), remove_object=True),
        now=datetime(2026, 6, 19, tzinfo=UTC),
    )

    assert result.outcome == "remove_failed"
    assert result.evidence_publication_id is None
    assert lifecycle.reserved == []
    assert audit.records[0]["outcome"] == "remove_failed"
