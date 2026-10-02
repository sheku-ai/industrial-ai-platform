from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID, uuid4

import pytest

from app.models.artifact_publication import RuntimeArtifactPublication
from app.services.object_storage_publication import (
    ObjectChecksumConflictError,
    ObjectMissingError,
    ObjectStoragePublicationCoordinator,
    StoredObject,
)
from app.services.runtime_lifecycle import InvalidLeaseError


class InMemoryObjectStorage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.return_corrupt_metadata = False

    def put(self, storage_uri: str, payload: bytes, *, media_type: str | None = None) -> StoredObject:
        del media_type
        self.objects[storage_uri] = payload
        digest = sha256(payload).hexdigest()
        if self.return_corrupt_metadata:
            digest = "0" * 64
        return StoredObject(storage_uri, digest, len(payload))

    def stat(self, storage_uri: str) -> StoredObject | None:
        payload = self.objects.get(storage_uri)
        if payload is None:
            return None
        return StoredObject(storage_uri, sha256(payload).hexdigest(), len(payload))


def publication() -> RuntimeArtifactPublication:
    return RuntimeArtifactPublication(
        id=uuid4(),
        organization_id=uuid4(),
        execution_id=uuid4(),
        artifact_id=uuid4(),
        attempt_id=uuid4(),
        publication_number=1,
        storage_uri=f"memory://bucket/{uuid4()}",
        media_type="application/octet-stream",
        checksum_sha256=None,
        size_bytes=None,
        status="reserved",
        metadata_={},
    )


def build_coordinator(*, fault_hook=None):
    storage = InMemoryObjectStorage()
    valid_token = uuid4()
    checkpoints: list[str] = []

    def lease_guard(_organization_id: UUID, _execution_id: UUID, lease_token: UUID) -> None:
        if lease_token != valid_token:
            raise InvalidLeaseError("stale lease")

    def checkpoint(current: RuntimeArtifactPublication) -> None:
        checkpoints.append(current.status)

    coordinator = ObjectStoragePublicationCoordinator(
        storage,
        lease_guard,
        checkpoint,
        fault_hook=fault_hook,
    )
    return coordinator, storage, valid_token, checkpoints


def test_database_reservation_precedes_object_write():
    coordinator, storage, token, checkpoints = build_coordinator()
    current = publication()

    coordinator.reserve(current, lease_token=token)

    assert current.status == "reserved"
    assert checkpoints == ["reserved"]
    assert storage.objects == {}


def test_upload_before_database_checkpoint_is_reconciled_idempotently():
    current = publication()

    def crash_after_write(stage, _publication):
        if stage == "after_object_write":
            raise RuntimeError("simulated process crash")

    coordinator, storage, token, checkpoints = build_coordinator(fault_hook=crash_after_write)
    payload = b"published-before-checkpoint"

    with pytest.raises(RuntimeError, match="simulated process crash"):
        coordinator.publish(current, lease_token=token, payload=payload)

    assert storage.objects[current.storage_uri] == payload
    assert current.status == "publishing"
    assert checkpoints == ["publishing"]

    coordinator.fault_hook = lambda _stage, _publication: None
    first = coordinator.reconcile(current, lease_token=token)
    second = coordinator.reconcile(current, lease_token=token)

    assert first is second is current
    assert current.status == "verified"
    assert current.published_at is not None
    assert current.verified_at is not None
    assert checkpoints[-2:] == ["verified", "verified"]


def test_missing_object_is_explicitly_detected():
    coordinator, _storage, token, checkpoints = build_coordinator()
    current = publication()
    current.checksum_sha256 = "a" * 64
    current.size_bytes = 10
    current.status = "published"

    with pytest.raises(ObjectMissingError):
        coordinator.verify(current, lease_token=token)

    assert current.status == "missing"
    assert current.error_code == "object_missing"
    assert checkpoints[-1] == "missing"


def test_existing_object_with_different_checksum_is_rejected():
    coordinator, storage, token, checkpoints = build_coordinator()
    current = publication()
    current.checksum_sha256 = sha256(b"expected").hexdigest()
    current.size_bytes = len(b"expected")
    storage.objects[current.storage_uri] = b"different"

    reconciled = coordinator.reconcile(current, lease_token=token)

    assert reconciled.status == "checksum_conflict"
    assert reconciled.error_code == "object_checksum_conflict"
    assert checkpoints[-1] == "checksum_conflict"


def test_stale_worker_cannot_finalize_after_upload():
    coordinator, storage, valid_token, checkpoints = build_coordinator()
    current = publication()
    payload = b"payload"
    storage.objects[current.storage_uri] = payload
    current.checksum_sha256 = sha256(payload).hexdigest()
    current.size_bytes = len(payload)
    stale_token = uuid4()

    with pytest.raises(InvalidLeaseError):
        coordinator.verify(current, lease_token=stale_token)

    assert current.status == "reserved"
    assert checkpoints == []
    assert valid_token != stale_token


def test_storage_reported_checksum_conflict_prevents_publish():
    coordinator, storage, token, checkpoints = build_coordinator()
    current = publication()
    storage.return_corrupt_metadata = True

    with pytest.raises(ObjectChecksumConflictError):
        coordinator.publish(current, lease_token=token, payload=b"payload")

    assert current.status == "checksum_conflict"
    assert current.error_code == "object_checksum_conflict"
    assert checkpoints == ["publishing", "checksum_conflict"]


def test_cancellation_retains_or_marks_reconciliation_without_success():
    coordinator, _storage, _token, checkpoints = build_coordinator()
    current = publication()

    coordinator.retain_after_cancellation(current, reconciliation_required=True)
    assert current.status == "reconciliation_required"

    coordinator.retain_after_cancellation(current, reconciliation_required=False)
    assert current.status == "retained"
    assert "verified" not in checkpoints
    assert "published" not in checkpoints


def test_publication_uses_timezone_aware_timestamps():
    coordinator, _storage, token, _checkpoints = build_coordinator()
    current = publication()
    fixed = datetime(2026, 6, 20, 12, 0, tzinfo=UTC)

    coordinator.publish(current, lease_token=token, payload=b"payload", now=fixed)
    coordinator.verify(current, lease_token=token, now=fixed)

    assert current.published_at == fixed
    assert current.verified_at == fixed
