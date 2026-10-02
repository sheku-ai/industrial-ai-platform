from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Protocol
from uuid import UUID

from app.models.artifact_publication import RuntimeArtifactPublication


class ObjectStoragePublicationError(RuntimeError):
    code = "object_storage_publication_error"


class ObjectMissingError(ObjectStoragePublicationError):
    code = "object_missing"


class ObjectChecksumConflictError(ObjectStoragePublicationError):
    code = "object_checksum_conflict"


class ObjectStorageWriteError(ObjectStoragePublicationError):
    code = "object_storage_write_failed"


@dataclass(frozen=True)
class StoredObject:
    storage_uri: str
    checksum_sha256: str
    size_bytes: int


class ObjectStoragePort(Protocol):
    def put(self, storage_uri: str, payload: bytes, *, media_type: str | None = None) -> StoredObject: ...

    def stat(self, storage_uri: str) -> StoredObject | None: ...


LeaseGuard = Callable[[UUID, UUID, UUID], None]
Checkpoint = Callable[[RuntimeArtifactPublication], None]
FaultHook = Callable[[str, RuntimeArtifactPublication], None]


class ObjectStoragePublicationCoordinator:
    """Coordinates binary publication while PostgreSQL remains authoritative.

    The caller owns transaction boundaries. ``checkpoint`` should flush/commit the
    publication state at durable boundaries. Object storage is intentionally
    outside the database transaction and is reconciled by checksum and size.
    """

    def __init__(
        self,
        storage: ObjectStoragePort,
        lease_guard: LeaseGuard,
        checkpoint: Checkpoint,
        *,
        fault_hook: FaultHook | None = None,
    ) -> None:
        self.storage = storage
        self.lease_guard = lease_guard
        self.checkpoint = checkpoint
        self.fault_hook = fault_hook or (lambda _stage, _publication: None)

    @staticmethod
    def _utcnow() -> datetime:
        return datetime.now(UTC)

    @staticmethod
    def describe_payload(storage_uri: str, payload: bytes) -> StoredObject:
        return StoredObject(
            storage_uri=storage_uri,
            checksum_sha256=sha256(payload).hexdigest(),
            size_bytes=len(payload),
        )

    def _guard(self, publication: RuntimeArtifactPublication, lease_token: UUID) -> None:
        self.lease_guard(publication.organization_id, publication.execution_id, lease_token)

    def reserve(
        self,
        publication: RuntimeArtifactPublication,
        *,
        lease_token: UUID,
    ) -> RuntimeArtifactPublication:
        self._guard(publication, lease_token)
        if publication.status not in {"reserved", "reconciliation_required", "failed", "missing"}:
            return publication
        publication.status = "reserved"
        publication.error_code = None
        self.checkpoint(publication)
        return publication

    def publish(
        self,
        publication: RuntimeArtifactPublication,
        *,
        lease_token: UUID,
        payload: bytes,
        now: datetime | None = None,
    ) -> RuntimeArtifactPublication:
        self._guard(publication, lease_token)
        expected = self.describe_payload(publication.storage_uri, payload)

        if publication.checksum_sha256 and publication.checksum_sha256 != expected.checksum_sha256:
            publication.status = "checksum_conflict"
            publication.error_code = ObjectChecksumConflictError.code
            self.checkpoint(publication)
            raise ObjectChecksumConflictError("payload checksum differs from reserved publication checksum")

        publication.checksum_sha256 = expected.checksum_sha256
        publication.size_bytes = expected.size_bytes
        publication.status = "publishing"
        publication.error_code = None
        self.checkpoint(publication)
        self.fault_hook("after_publishing_checkpoint", publication)

        try:
            stored = self.storage.put(
                publication.storage_uri,
                payload,
                media_type=publication.media_type,
            )
        except Exception as exc:
            publication.status = "failed"
            publication.error_code = ObjectStorageWriteError.code
            self.checkpoint(publication)
            raise ObjectStorageWriteError("object storage write failed") from exc

        self.fault_hook("after_object_write", publication)

        if stored.checksum_sha256 != expected.checksum_sha256 or stored.size_bytes != expected.size_bytes:
            publication.status = "checksum_conflict"
            publication.error_code = ObjectChecksumConflictError.code
            self.checkpoint(publication)
            raise ObjectChecksumConflictError("stored object does not match the publication payload")

        self._guard(publication, lease_token)
        publication.status = "published"
        publication.published_at = now or self._utcnow()
        publication.error_code = None
        self.checkpoint(publication)
        return publication

    def verify(
        self,
        publication: RuntimeArtifactPublication,
        *,
        lease_token: UUID,
        now: datetime | None = None,
    ) -> RuntimeArtifactPublication:
        self._guard(publication, lease_token)
        stored = self.storage.stat(publication.storage_uri)
        if stored is None:
            publication.status = "missing"
            publication.error_code = ObjectMissingError.code
            self.checkpoint(publication)
            raise ObjectMissingError("published object is missing")

        if publication.checksum_sha256 != stored.checksum_sha256 or publication.size_bytes != stored.size_bytes:
            publication.status = "checksum_conflict"
            publication.error_code = ObjectChecksumConflictError.code
            self.checkpoint(publication)
            raise ObjectChecksumConflictError("published object checksum or size differs from PostgreSQL")

        if publication.published_at is None:
            publication.published_at = now or self._utcnow()
        publication.status = "verified"
        publication.verified_at = now or self._utcnow()
        publication.error_code = None
        self.checkpoint(publication)
        return publication

    def reconcile(
        self,
        publication: RuntimeArtifactPublication,
        *,
        lease_token: UUID,
        now: datetime | None = None,
    ) -> RuntimeArtifactPublication:
        self._guard(publication, lease_token)
        stored = self.storage.stat(publication.storage_uri)
        if stored is None:
            publication.status = "missing"
            publication.error_code = ObjectMissingError.code
            self.checkpoint(publication)
            return publication

        if publication.checksum_sha256 is None:
            publication.checksum_sha256 = stored.checksum_sha256
            publication.size_bytes = stored.size_bytes
        elif publication.checksum_sha256 != stored.checksum_sha256 or publication.size_bytes != stored.size_bytes:
            publication.status = "checksum_conflict"
            publication.error_code = ObjectChecksumConflictError.code
            self.checkpoint(publication)
            return publication

        publication.status = "verified"
        publication.published_at = publication.published_at or now or self._utcnow()
        publication.verified_at = now or self._utcnow()
        publication.error_code = None
        self.checkpoint(publication)
        return publication

    def retain_after_cancellation(
        self,
        publication: RuntimeArtifactPublication,
        *,
        reconciliation_required: bool,
    ) -> RuntimeArtifactPublication:
        publication.status = "reconciliation_required" if reconciliation_required else "retained"
        publication.error_code = None
        self.checkpoint(publication)
        return publication
