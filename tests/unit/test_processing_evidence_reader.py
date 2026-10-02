from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock

from sqlalchemy.orm import Session

from app.models.processing import ProcessingRevision
from app.services.processing_evidence_reader import read_processing_evidence_v1


def _revision(*, organization_id: uuid.UUID, evidence_id: uuid.UUID) -> ProcessingRevision:
    now = datetime.now(UTC)
    return ProcessingRevision(
        id=evidence_id,
        organization_id=organization_id,
        document_record_id=uuid.uuid4(),
        document_version_id=uuid.uuid4(),
        runtime_execution_id=uuid.uuid4(),
        runtime_attempt_id=uuid.uuid4(),
        pipeline_profile_id=None,
        pipeline_profile_revision="1",
        adapter_key="builtin.text",
        adapter_version="1",
        configuration_snapshot={},
        source_checksum_sha256=None,
        status="completed",
        started_at=now,
        completed_at=now,
        content_unit_count=1,
        chunk_count=1,
        manifest_artifact_id=None,
    )


def test_processing_evidence_reader_projects_scoped_persisted_revision() -> None:
    organization_id = uuid.uuid4()
    evidence_id = uuid.uuid4()
    revision = _revision(organization_id=organization_id, evidence_id=evidence_id)
    session = MagicMock(spec=Session)
    session.scalar.return_value = revision

    evidence = read_processing_evidence_v1(
        session,
        organization_id=organization_id,
        evidence_id=evidence_id,
    )

    assert evidence is not None
    assert evidence.evidence_id == evidence_id
    assert evidence.organization_id == organization_id

    statement = session.scalar.call_args.args[0]
    compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))
    assert "processing_revisions.id" in compiled
    assert "processing_revisions.organization_id" in compiled
    assert evidence_id.hex in compiled
    assert organization_id.hex in compiled


def test_processing_evidence_reader_returns_none_when_scoped_revision_is_absent() -> None:
    session = MagicMock(spec=Session)
    session.scalar.return_value = None

    evidence = read_processing_evidence_v1(
        session,
        organization_id=uuid.uuid4(),
        evidence_id=uuid.uuid4(),
    )

    assert evidence is None
