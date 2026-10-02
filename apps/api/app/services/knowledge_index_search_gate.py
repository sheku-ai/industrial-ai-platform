from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import String, cast, select
from sqlalchemy.orm import Session

from app.contracts.knowledge_index import KnowledgeIndexEvidenceV1
from app.models.documents import DocumentVersion
from app.models.knowledge_index import KnowledgeChunk, KnowledgeDocument
from app.services.knowledge_index_evidence_reader import read_knowledge_index_evidence_v1

KNOWLEDGE_INDEX_SEARCH_GATE_VERSION = "v1"


@dataclass(frozen=True)
class KnowledgeIndexSearchGateV1:
    organization_id: uuid.UUID
    knowledge_index_evidence: KnowledgeIndexEvidenceV1 | None
    ready: bool
    blocking_issues: tuple[dict[str, Any], ...]
    gate_version: str = KNOWLEDGE_INDEX_SEARCH_GATE_VERSION


def _issue(code: str, message: str) -> dict[str, Any]:
    return {
        "code": code,
        "severity": "blocking",
        "component": "knowledge_index_evidence",
        "item_id": None,
        "message": message,
    }


def evaluate_knowledge_index_search_gate_v1(
    session: Session,
    *,
    organization_id: uuid.UUID,
    artifact_id: str | None = None,
    publication_id: str | None = None,
    knowledge_document_id: str | None = None,
) -> KnowledgeIndexSearchGateV1:
    """Authorize Enterprise Search from persisted Knowledge Index evidence."""

    statement = (
        select(KnowledgeDocument.id)
        .join(
            DocumentVersion,
            KnowledgeDocument.document_version_id == cast(DocumentVersion.id, String),
        )
        .join(KnowledgeChunk, KnowledgeChunk.knowledge_document_id == KnowledgeDocument.id)
        .where(
            DocumentVersion.organization_id == organization_id,
            KnowledgeDocument.status == "indexed",
            KnowledgeChunk.status == "indexed",
        )
    )
    if artifact_id:
        statement = statement.where(KnowledgeDocument.artifact_id == str(artifact_id))
    if publication_id:
        statement = statement.where(KnowledgeDocument.publication_id == str(publication_id))
    if knowledge_document_id:
        try:
            document_uuid = uuid.UUID(str(knowledge_document_id))
        except (TypeError, ValueError):
            return KnowledgeIndexSearchGateV1(
                organization_id=organization_id,
                knowledge_index_evidence=None,
                ready=False,
                blocking_issues=(
                    _issue(
                        "knowledge_document_scope_invalid",
                        "Enterprise Search knowledge_document_id must be a valid UUID.",
                    ),
                ),
            )
        statement = statement.where(KnowledgeDocument.id == document_uuid)

    evidence_id = session.scalar(
        statement.order_by(KnowledgeDocument.updated_at.desc(), KnowledgeDocument.id.desc()).limit(1)
    )
    if evidence_id is None:
        return KnowledgeIndexSearchGateV1(
            organization_id=organization_id,
            knowledge_index_evidence=None,
            ready=False,
            blocking_issues=(
                _issue(
                    "knowledge_index_evidence_missing",
                    "Enterprise Search requires persisted indexed knowledge for the requested organization scope.",
                ),
            ),
        )

    evidence = read_knowledge_index_evidence_v1(
        session,
        organization_id=organization_id,
        knowledge_document_id=evidence_id,
    )
    if evidence is None:
        return KnowledgeIndexSearchGateV1(
            organization_id=organization_id,
            knowledge_index_evidence=None,
            ready=False,
            blocking_issues=(
                _issue(
                    "knowledge_index_evidence_scope_mismatch",
                    "Persisted Knowledge Index evidence does not match the requested organization scope.",
                ),
            ),
        )

    blocking_issues: list[dict[str, Any]] = []
    if evidence.status != "indexed":
        blocking_issues.append(
            _issue(
                "knowledge_index_not_indexed",
                "Enterprise Search requires Knowledge Index status=indexed.",
            )
        )

    return KnowledgeIndexSearchGateV1(
        organization_id=organization_id,
        knowledge_index_evidence=evidence,
        ready=not blocking_issues,
        blocking_issues=tuple(blocking_issues),
    )


def serialize_knowledge_index_search_gate_v1(gate: KnowledgeIndexSearchGateV1) -> dict[str, Any]:
    evidence = gate.knowledge_index_evidence
    return {
        "gate_version": gate.gate_version,
        "organization_id": str(gate.organization_id),
        "knowledge_document_id": str(evidence.knowledge_document_id) if evidence is not None else None,
        "artifact_id": evidence.artifact_id if evidence is not None else None,
        "publication_id": evidence.publication_id if evidence is not None else None,
        "index_status": evidence.status if evidence is not None else None,
        "index_version": evidence.index_version if evidence is not None else None,
        "ready": gate.ready,
        "blocking_issues": [dict(item) for item in gate.blocking_issues],
        "authority": "postgresql",
        "contract": "KnowledgeIndexEvidenceV1",
    }
