from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts.processing import ProcessingEvidenceV1
from app.models.documents import Artifact
from app.models.processing import ProcessingRevision
from app.services.processing_evidence_reader import read_processing_evidence_v1

PROCESSING_PUBLICATION_GATE_VERSION = "v1"


@dataclass(frozen=True)
class ProcessingPublicationGateV1:
    artifact_id: uuid.UUID
    organization_id: uuid.UUID | None
    document_record_id: uuid.UUID | None
    document_version_id: uuid.UUID | None
    processing_evidence: ProcessingEvidenceV1 | None
    ready: bool
    blocking_issues: tuple[dict[str, Any], ...]
    gate_version: str = PROCESSING_PUBLICATION_GATE_VERSION


def _issue(code: str, message: str) -> dict[str, Any]:
    return {
        "code": code,
        "severity": "blocking",
        "component": "processing_evidence",
        "message": message,
    }


def evaluate_processing_publication_gate_v1(
    session: Session,
    *,
    artifact_id: uuid.UUID,
) -> ProcessingPublicationGateV1:
    """Resolve the publication gate from authoritative PostgreSQL evidence.

    Artifact lineage determines the organization/document boundary. The newest
    processing revision for that exact organization and document version is
    then read through the canonical ProcessingEvidenceV1 reader. Runtime flags
    and in-memory chunk results are not used to decide whether Processing has
    completed.
    """

    artifact = session.scalar(select(Artifact).where(Artifact.id == artifact_id))
    if artifact is None:
        return ProcessingPublicationGateV1(
            artifact_id=artifact_id,
            organization_id=None,
            document_record_id=None,
            document_version_id=None,
            processing_evidence=None,
            ready=False,
            blocking_issues=(
                _issue("processing_artifact_missing", "Publication requires a persisted artifact."),
            ),
        )

    revision_id = session.scalar(
        select(ProcessingRevision.id)
        .where(
            ProcessingRevision.organization_id == artifact.organization_id,
            ProcessingRevision.document_record_id == artifact.document_record_id,
            ProcessingRevision.document_version_id == artifact.document_version_id,
        )
        .order_by(
            ProcessingRevision.started_at.desc(),
            ProcessingRevision.created_at.desc(),
            ProcessingRevision.id.desc(),
        )
        .limit(1)
    )
    if revision_id is None:
        return ProcessingPublicationGateV1(
            artifact_id=artifact_id,
            organization_id=artifact.organization_id,
            document_record_id=artifact.document_record_id,
            document_version_id=artifact.document_version_id,
            processing_evidence=None,
            ready=False,
            blocking_issues=(
                _issue(
                    "processing_evidence_missing",
                    "Publication requires persisted processing evidence for the artifact document version.",
                ),
            ),
        )

    evidence = read_processing_evidence_v1(
        session,
        organization_id=artifact.organization_id,
        evidence_id=revision_id,
    )
    if evidence is None:
        return ProcessingPublicationGateV1(
            artifact_id=artifact_id,
            organization_id=artifact.organization_id,
            document_record_id=artifact.document_record_id,
            document_version_id=artifact.document_version_id,
            processing_evidence=None,
            ready=False,
            blocking_issues=(
                _issue(
                    "processing_evidence_scope_mismatch",
                    "Persisted processing evidence does not match the artifact organization scope.",
                ),
            ),
        )

    blocking_issues: list[dict[str, Any]] = []
    if evidence.status != "completed":
        blocking_issues.append(
            _issue("processing_not_completed", "Publication requires processing status=completed.")
        )
    if evidence.completed_at is None:
        blocking_issues.append(
            _issue("processing_completion_missing", "Publication requires persisted processing completion time.")
        )
    if evidence.chunk_count < 1:
        blocking_issues.append(
            _issue("processing_chunk_count_empty", "Publication requires persisted processing chunk_count >= 1.")
        )
    lineage_mismatch = (
        evidence.document_record_id != artifact.document_record_id
        or evidence.document_version_id != artifact.document_version_id
    )
    if lineage_mismatch:
        blocking_issues.append(
            _issue(
                "processing_lineage_mismatch",
                "Persisted processing evidence does not match the artifact document lineage.",
            )
        )

    return ProcessingPublicationGateV1(
        artifact_id=artifact_id,
        organization_id=artifact.organization_id,
        document_record_id=artifact.document_record_id,
        document_version_id=artifact.document_version_id,
        processing_evidence=evidence,
        ready=not blocking_issues,
        blocking_issues=tuple(blocking_issues),
    )


def serialize_processing_publication_gate_v1(gate: ProcessingPublicationGateV1) -> dict[str, Any]:
    evidence = gate.processing_evidence
    return {
        "gate_version": gate.gate_version,
        "artifact_id": str(gate.artifact_id),
        "organization_id": str(gate.organization_id) if gate.organization_id is not None else None,
        "document_record_id": str(gate.document_record_id) if gate.document_record_id is not None else None,
        "document_version_id": str(gate.document_version_id) if gate.document_version_id is not None else None,
        "processing_evidence_id": str(evidence.evidence_id) if evidence is not None else None,
        "processing_status": evidence.status if evidence is not None else None,
        "processing_completed_at": evidence.completed_at.isoformat() if evidence and evidence.completed_at else None,
        "processing_chunk_count": evidence.chunk_count if evidence is not None else None,
        "ready": gate.ready,
        "blocking_issues": [dict(item) for item in gate.blocking_issues],
        "authority": "postgresql",
        "contract": "ProcessingEvidenceV1",
    }
