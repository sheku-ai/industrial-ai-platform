from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.contracts.knowledge_publication import KnowledgePublicationEvidenceV1
from app.services.knowledge_publication_evidence_reader import read_knowledge_publication_evidence_v1

KNOWLEDGE_PUBLICATION_INDEX_GATE_VERSION = "v1"


@dataclass(frozen=True)
class KnowledgePublicationIndexGateV1:
    evidence_id: uuid.UUID
    organization_id: uuid.UUID
    artifact_id: str
    publication_evidence: KnowledgePublicationEvidenceV1 | None
    ready: bool
    blocking_issues: tuple[dict[str, Any], ...]
    gate_version: str = KNOWLEDGE_PUBLICATION_INDEX_GATE_VERSION


def _issue(code: str, message: str) -> dict[str, Any]:
    return {
        "code": code,
        "severity": "blocking",
        "component": "knowledge_publication_evidence",
        "message": message,
    }


def evaluate_knowledge_publication_index_gate_v1(
    session: Session,
    *,
    organization_id: uuid.UUID,
    evidence_id: uuid.UUID,
    artifact_id: str,
) -> KnowledgePublicationIndexGateV1:
    """Authorize Knowledge Index only from persisted publication evidence."""

    evidence = read_knowledge_publication_evidence_v1(
        session,
        organization_id=organization_id,
        evidence_id=evidence_id,
    )
    if evidence is None:
        return KnowledgePublicationIndexGateV1(
            evidence_id=evidence_id,
            organization_id=organization_id,
            artifact_id=artifact_id,
            publication_evidence=None,
            ready=False,
            blocking_issues=(
                _issue(
                    "knowledge_publication_evidence_missing",
                    "Knowledge Index requires persisted Knowledge Publication evidence.",
                ),
            ),
        )

    blocking_issues: list[dict[str, Any]] = []
    if evidence.artifact_id != artifact_id:
        blocking_issues.append(
            _issue(
                "knowledge_publication_artifact_mismatch",
                "Persisted Knowledge Publication evidence does not match the requested artifact.",
            )
        )
    if evidence.publication_status != "completed":
        blocking_issues.append(
            _issue(
                "knowledge_publication_not_completed",
                "Knowledge Index requires publication_status=completed.",
            )
        )
    if not evidence.publication_completed or not evidence.publication_succeeded:
        blocking_issues.append(
            _issue(
                "knowledge_publication_not_succeeded",
                "Knowledge Index requires a completed and successful persisted publication result.",
            )
        )
    if not evidence.knowledge_published:
        blocking_issues.append(
            _issue(
                "knowledge_not_published",
                "Knowledge Index requires persisted knowledge_published=true evidence.",
            )
        )
    if evidence.published_chunk_count < 1:
        blocking_issues.append(
            _issue(
                "knowledge_publication_chunk_count_empty",
                "Knowledge Index requires persisted published_chunk_count >= 1.",
            )
        )
    if evidence.record_persistence_status != "persisted":
        blocking_issues.append(
            _issue(
                "knowledge_publication_not_persisted",
                "Knowledge Index requires the publication evidence record to be persisted.",
            )
        )

    return KnowledgePublicationIndexGateV1(
        evidence_id=evidence_id,
        organization_id=organization_id,
        artifact_id=artifact_id,
        publication_evidence=evidence,
        ready=not blocking_issues,
        blocking_issues=tuple(blocking_issues),
    )


def serialize_knowledge_publication_index_gate_v1(gate: KnowledgePublicationIndexGateV1) -> dict[str, Any]:
    evidence = gate.publication_evidence
    return {
        "gate_version": gate.gate_version,
        "evidence_id": str(gate.evidence_id),
        "organization_id": str(gate.organization_id),
        "artifact_id": gate.artifact_id,
        "publication_id": evidence.publication_id if evidence is not None else None,
        "publication_status": evidence.publication_status if evidence is not None else None,
        "published_chunk_count": evidence.published_chunk_count if evidence is not None else None,
        "ready": gate.ready,
        "blocking_issues": [dict(item) for item in gate.blocking_issues],
        "authority": "postgresql",
        "contract": "KnowledgePublicationEvidenceV1",
    }
