from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.models.documents import Chunk
from app.models.processing import ProcessingRevision
from app.services.processing_revision_lifecycle import (
    ProcessingRevisionConflictError,
    ProcessingRevisionLifecycleService,
)


class FakeSession:
    def __init__(self, scalar_result=None):
        self.scalar_result = scalar_result
        self.added = []
        self.flush_count = 0

    def scalar(self, statement):
        return self.scalar_result

    def add(self, value):
        self.added.append(value)

    def flush(self):
        self.flush_count += 1


def _identity():
    return {
        "organization_id": uuid4(),
        "document_record_id": uuid4(),
        "document_version_id": uuid4(),
        "runtime_execution_id": uuid4(),
        "runtime_attempt_id": uuid4(),
        "pipeline_profile_id": uuid4(),
        "pipeline_profile_revision": "7",
        "adapter_key": "text",
        "adapter_version": "1.0",
    }


def test_chunk_model_exposes_additive_processing_revision_identity():
    table = Chunk.__table__

    assert table.c.processing_revision_id.nullable is True
    assert (
        str(next(iter(table.c.processing_revision_id.foreign_keys)).target_fullname)
        == "documents.processing_revisions.id"
    )
    index_names = {index.name for index in table.indexes}
    assert "ix_chunks_processing_revision_id" in index_names
    assert "uq_chunks_revision_chunk_key" in index_names


def test_start_creates_one_processing_revision_without_committing():
    session = FakeSession()
    service = ProcessingRevisionLifecycleService(session)
    identity = _identity()
    started_at = datetime.now(UTC)

    revision = service.start(
        **identity,
        configuration_snapshot={"chunking": {"size": 500}},
        source_checksum_sha256="a" * 64,
        started_at=started_at,
    )

    assert session.added == [revision]
    assert session.flush_count == 1
    assert revision.status == "processing"
    assert revision.started_at == started_at
    assert revision.configuration_snapshot == {"chunking": {"size": 500}}


def test_start_is_idempotent_for_same_runtime_attempt_identity():
    identity = _identity()
    existing = ProcessingRevision(
        **identity,
        configuration_snapshot={},
        source_checksum_sha256=None,
        status="processing",
        started_at=datetime.now(UTC),
        completed_at=None,
        content_unit_count=0,
        chunk_count=0,
    )
    session = FakeSession(existing)

    result = ProcessingRevisionLifecycleService(session).start(**identity)

    assert result is existing
    assert session.added == []
    assert session.flush_count == 0


def test_start_rejects_conflicting_identity_for_same_runtime_attempt():
    identity = _identity()
    existing = ProcessingRevision(
        **identity,
        configuration_snapshot={},
        source_checksum_sha256=None,
        status="processing",
        started_at=datetime.now(UTC),
        completed_at=None,
        content_unit_count=0,
        chunk_count=0,
    )
    session = FakeSession(existing)

    with pytest.raises(ProcessingRevisionConflictError, match="different processing revision identity"):
        ProcessingRevisionLifecycleService(session).start(**{**identity, "adapter_version": "2.0"})


def test_complete_makes_revision_terminal_and_idempotent():
    now = datetime.now(UTC)
    identity = _identity()
    revision = ProcessingRevision(
        **identity,
        configuration_snapshot={},
        source_checksum_sha256=None,
        status="processing",
        started_at=now,
        completed_at=None,
        content_unit_count=0,
        chunk_count=0,
    )
    session = FakeSession(revision)
    service = ProcessingRevisionLifecycleService(session)

    result = service.complete(
        organization_id=identity["organization_id"],
        runtime_execution_id=identity["runtime_execution_id"],
        runtime_attempt_id=identity["runtime_attempt_id"],
        content_unit_count=4,
        chunk_count=4,
        completed_at=now + timedelta(seconds=1),
    )

    assert result.status == "completed"
    assert result.content_unit_count == 4
    assert result.chunk_count == 4
    assert session.flush_count == 1

    same = service.complete(
        organization_id=identity["organization_id"],
        runtime_execution_id=identity["runtime_execution_id"],
        runtime_attempt_id=identity["runtime_attempt_id"],
        content_unit_count=4,
        chunk_count=4,
    )
    assert same is revision
    assert session.flush_count == 1


def test_terminal_revision_cannot_change_outcome():
    now = datetime.now(UTC)
    identity = _identity()
    revision = ProcessingRevision(
        **identity,
        configuration_snapshot={},
        source_checksum_sha256=None,
        status="completed",
        started_at=now,
        completed_at=now,
        content_unit_count=1,
        chunk_count=1,
    )

    with pytest.raises(ProcessingRevisionConflictError, match="immutable"):
        ProcessingRevisionLifecycleService(FakeSession(revision)).fail(
            organization_id=identity["organization_id"],
            runtime_execution_id=identity["runtime_execution_id"],
            runtime_attempt_id=identity["runtime_attempt_id"],
        )
