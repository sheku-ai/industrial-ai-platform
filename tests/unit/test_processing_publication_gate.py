from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock

from sqlalchemy.orm import Session

from app.models.documents import Artifact
from app.models.processing import ProcessingRevision
from app.services.processing_publication_gate import (
    evaluate_processing_publication_gate_v1,
    serialize_processing_publication_gate_v1,
)


def _artifact(*, artifact_id: uuid.UUID, organization_id: uuid.UUID) -> Artifact:
    return Artifact(
        id=artifact_id,
        organization_id=organization_id,
        document_record_id=uuid.uuid4(),
        document_version_id=uuid.uuid4(),
        ingestion_job_id=None,
        artifact_type="source",
        media_type="text/plain",
        object_store_provider="filesystem",
        bucket="documents",
        object_key=f"documents/{artifact_id}",
        checksum_sha256=None,
        size_bytes=1,
        metadata_json={},
        status="verified",
    )


def _revision(
    *,
    artifact: Artifact,
    evidence_id: uuid.UUID,
    status: str = "completed",
    completed_at: datetime | None = None,
    chunk_count: int = 1,
) -> ProcessingRevision:
    now = datetime.now(UTC)
    return ProcessingRevision(
        id=evidence_id,
        organization_id=artifact.organization_id,
        document_record_id=artifact.document_record_id,
        document_version_id=artifact.document_version_id,
        runtime_execution_id=uuid.uuid4(),
        runtime_attempt_id=uuid.uuid4(),
        pipeline_profile_id=None,
        pipeline_profile_revision="1",
        adapter_key="builtin.text",
        adapter_version="1",
        configuration_snapshot={},
        source_checksum_sha256=None,
        status=status,
        started_at=now,
        completed_at=completed_at if completed_at is not None else (now if status == "completed" else None),
        content_unit_count=1,
        chunk_count=chunk_count,
        manifest_artifact_id=None,
    )


def test_processing_publication_gate_uses_persisted_processing_evidence() -> None:
    artifact_id = uuid.uuid4()
    organization_id = uuid.uuid4()
    evidence_id = uuid.uuid4()
    artifact = _artifact(artifact_id=artifact_id, organization_id=organization_id)
    revision = _revision(artifact=artifact, evidence_id=evidence_id)
    session = MagicMock(spec=Session)
    session.scalar.side_effect = [artifact, evidence_id, revision]

    gate = evaluate_processing_publication_gate_v1(session, artifact_id=artifact_id)

    assert gate.ready is True
    assert gate.processing_evidence is not None
    assert gate.processing_evidence.evidence_id == evidence_id
    assert gate.organization_id == organization_id
    assert gate.blocking_issues == ()

    revision_statement = session.scalar.call_args_list[1].args[0]
    compiled = str(revision_statement.compile(compile_kwargs={"literal_binds": True}))
    assert "processing_revisions.organization_id" in compiled
    assert "processing_revisions.document_record_id" in compiled
    assert "processing_revisions.document_version_id" in compiled
    assert "ORDER BY" in compiled

    payload = serialize_processing_publication_gate_v1(gate)
    assert payload["authority"] == "postgresql"
    assert payload["contract"] == "ProcessingEvidenceV1"
    assert payload["processing_evidence_id"] == str(evidence_id)
    assert payload["ready"] is True


def test_processing_publication_gate_blocks_when_latest_revision_is_not_completed() -> None:
    artifact_id = uuid.uuid4()
    artifact = _artifact(artifact_id=artifact_id, organization_id=uuid.uuid4())
    evidence_id = uuid.uuid4()
    revision = _revision(artifact=artifact, evidence_id=evidence_id, status="processing")
    session = MagicMock(spec=Session)
    session.scalar.side_effect = [artifact, evidence_id, revision]

    gate = evaluate_processing_publication_gate_v1(session, artifact_id=artifact_id)

    assert gate.ready is False
    codes = {item["code"] for item in gate.blocking_issues}
    assert "processing_not_completed" in codes
    assert "processing_completion_missing" in codes


def test_processing_publication_gate_blocks_when_processing_evidence_is_missing() -> None:
    artifact_id = uuid.uuid4()
    artifact = _artifact(artifact_id=artifact_id, organization_id=uuid.uuid4())
    session = MagicMock(spec=Session)
    session.scalar.side_effect = [artifact, None]

    gate = evaluate_processing_publication_gate_v1(session, artifact_id=artifact_id)

    assert gate.ready is False
    assert gate.processing_evidence is None
    assert gate.blocking_issues[0]["code"] == "processing_evidence_missing"
