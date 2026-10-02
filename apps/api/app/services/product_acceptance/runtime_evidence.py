from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.documents import Artifact
from app.models.runtime import RuntimePersistenceRecord
from app.services.enterprise_search_evidence_reader import read_enterprise_search_evidence_v1
from app.services.knowledge_index_search_gate import (
    evaluate_knowledge_index_search_gate_v1,
    serialize_knowledge_index_search_gate_v1,
)
from app.services.knowledge_publication_evidence_reader import (
    read_knowledge_publication_evidence_v1,
)
from app.services.processing_publication_gate import (
    evaluate_processing_publication_gate_v1,
    serialize_processing_publication_gate_v1,
)

PRODUCT_ACCEPTANCE_RUNTIME_EVIDENCE_SCHEMA_VERSION = "1"


def _issue(code: str, message: str, *, component: str) -> dict[str, Any]:
    return {
        "code": code,
        "severity": "blocking",
        "component": component,
        "message": message,
    }


def _publication_evidence_payload(evidence: Any) -> dict[str, Any] | None:
    if evidence is None:
        return None
    return {
        "contract": "KnowledgePublicationEvidenceV1",
        "contract_version": evidence.contract_version,
        "evidence_id": str(evidence.evidence_id),
        "organization_id": str(evidence.organization_id),
        "execution_id": evidence.execution_id,
        "artifact_id": evidence.artifact_id,
        "processing_session_id": evidence.processing_session_id,
        "publication_id": evidence.publication_id,
        "publication_status": evidence.publication_status,
        "publication_completed": evidence.publication_completed,
        "publication_succeeded": evidence.publication_succeeded,
        "knowledge_published": evidence.knowledge_published,
        "published_chunk_count": evidence.published_chunk_count,
        "record_persistence_status": evidence.record_persistence_status,
        "occurred_at": evidence.occurred_at.isoformat(),
        "persisted_at": evidence.persisted_at.isoformat() if evidence.persisted_at else None,
    }


def _knowledge_index_evidence_payload(evidence: Any) -> dict[str, Any] | None:
    if evidence is None:
        return None
    return {
        "contract": "KnowledgeIndexEvidenceV1",
        "knowledge_document_id": str(evidence.knowledge_document_id),
        "organization_id": str(evidence.organization_id),
        "artifact_id": evidence.artifact_id,
        "publication_id": evidence.publication_id,
        "document_record_id": evidence.document_record_id,
        "document_version_id": evidence.document_version_id,
        "status": evidence.status,
        "index_version": evidence.index_version,
        "content_signature": evidence.content_signature,
        "created_at": evidence.created_at.isoformat(),
        "updated_at": evidence.updated_at.isoformat(),
    }


def _enterprise_search_evidence_payload(evidence: Any) -> dict[str, Any] | None:
    if evidence is None:
        return None
    return {
        "contract": "EnterpriseSearchEvidenceV1",
        "evidence_id": str(evidence.evidence_id),
        "organization_id": str(evidence.organization_id),
        "execution_id": evidence.execution_id,
        "search_session_id": evidence.search_session_id,
        "query": evidence.query,
        "normalized_query": evidence.normalized_query,
        "search_status": evidence.search_status,
        "ranking_model": evidence.ranking_model,
        "total_count": evidence.total_count,
        "result_count": evidence.result_count,
        "offset": evidence.offset,
        "limit": evidence.limit,
        "has_more": evidence.has_more,
        "search_uses_postgresql": evidence.search_uses_postgresql,
        "search_uses_postgresql_fts": evidence.search_uses_postgresql_fts,
        "semantic_search_used": evidence.semantic_search_used,
        "embeddings_required": evidence.embeddings_required,
        "ai_required": evidence.ai_required,
        "persistence_status": evidence.persistence_status,
        "occurred_at": evidence.occurred_at.isoformat(),
        "persisted_at": evidence.persisted_at.isoformat() if evidence.persisted_at else None,
    }


def build_document_runtime_evidence(
    session: Session,
    *,
    organization_id: uuid.UUID,
    artifact_id: uuid.UUID,
) -> dict[str, Any]:
    """Resolve Product Acceptance evidence from authoritative persisted state.

    This resolver intentionally reuses the same evidence readers/gates that
    authorize runtime boundaries. Product Acceptance therefore observes the
    persisted contracts rather than deriving completion from lifecycle flags.
    """

    artifact = session.scalar(
        select(Artifact).where(
            Artifact.id == artifact_id,
            Artifact.organization_id == organization_id,
        )
    )
    if artifact is None:
        issue = _issue(
            "acceptance_artifact_not_found",
            "Product Acceptance requires an artifact in the active organization scope.",
            component="runtime_evidence",
        )
        return {
            "runtime_evidence_schema_version": PRODUCT_ACCEPTANCE_RUNTIME_EVIDENCE_SCHEMA_VERSION,
            "authority": "postgresql",
            "organization_id": str(organization_id),
            "artifact_id": str(artifact_id),
            "processing": {"ready": False, "blocking_issues": [issue]},
            "chunking": {"ready": False, "blocking_issues": [issue]},
            "knowledge_publication": {"ready": False, "blocking_issues": [issue]},
            "knowledge_index": {"ready": False, "blocking_issues": [issue]},
        }

    processing_gate = evaluate_processing_publication_gate_v1(session, artifact_id=artifact_id)
    processing_payload = serialize_processing_publication_gate_v1(processing_gate)
    processing_ready = bool(
        processing_gate.ready
        and processing_gate.organization_id == organization_id
        and processing_gate.document_record_id == artifact.document_record_id
        and processing_gate.document_version_id == artifact.document_version_id
    )
    processing_issues = [dict(item) for item in processing_gate.blocking_issues]
    if processing_gate.organization_id != organization_id:
        processing_issues.append(
            _issue(
                "processing_organization_mismatch",
                "Processing evidence does not match the active organization scope.",
                component="processing_evidence",
            )
        )
    if (
        processing_gate.document_record_id != artifact.document_record_id
        or processing_gate.document_version_id != artifact.document_version_id
    ):
        processing_issues.append(
            _issue(
                "processing_document_lineage_mismatch",
                "Processing evidence does not match the persisted artifact document lineage.",
                component="processing_evidence",
            )
        )

    processing_evidence = processing_gate.processing_evidence
    chunk_count = processing_evidence.chunk_count if processing_evidence is not None else 0
    chunking_issues = list(processing_issues)
    if chunk_count < 1:
        chunking_issues.append(
            _issue(
                "processing_chunk_count_empty",
                "Chunking requires persisted ProcessingEvidenceV1 chunk_count >= 1.",
                component="chunking_evidence",
            )
        )
    chunking_ready = bool(processing_ready and chunk_count >= 1)

    publication_record_id = session.scalar(
        select(RuntimePersistenceRecord.id)
        .where(
            RuntimePersistenceRecord.runtime_domain == "knowledge_publication",
            RuntimePersistenceRecord.record_type == "publication_result",
            RuntimePersistenceRecord.artifact_id == str(artifact_id),
            RuntimePersistenceRecord.payload["organization_id"].astext == str(organization_id),
        )
        .order_by(
            RuntimePersistenceRecord.persisted_at.desc(),
            RuntimePersistenceRecord.occurred_at.desc(),
            RuntimePersistenceRecord.id.desc(),
        )
        .limit(1)
    )
    publication_evidence = (
        read_knowledge_publication_evidence_v1(
            session,
            organization_id=organization_id,
            evidence_id=publication_record_id,
        )
        if publication_record_id is not None
        else None
    )
    publication_issues: list[dict[str, Any]] = []
    if publication_evidence is None:
        publication_issues.append(
            _issue(
                "knowledge_publication_evidence_missing",
                "Knowledge Publication requires persisted KnowledgePublicationEvidenceV1 for the artifact.",
                component="knowledge_publication_evidence",
            )
        )
    else:
        if publication_evidence.organization_id != organization_id:
            publication_issues.append(
                _issue(
                    "knowledge_publication_organization_mismatch",
                    "Knowledge Publication evidence does not match the active organization scope.",
                    component="knowledge_publication_evidence",
                )
            )
        if publication_evidence.artifact_id != str(artifact_id):
            publication_issues.append(
                _issue(
                    "knowledge_publication_artifact_mismatch",
                    "Knowledge Publication evidence does not match the Product Acceptance artifact.",
                    component="knowledge_publication_evidence",
                )
            )
        if publication_evidence.publication_status != "completed":
            publication_issues.append(
                _issue(
                    "knowledge_publication_not_completed",
                    "Knowledge Publication requires publication_status=completed.",
                    component="knowledge_publication_evidence",
                )
            )
        if not publication_evidence.publication_completed:
            publication_issues.append(
                _issue(
                    "knowledge_publication_completion_missing",
                    "Knowledge Publication requires persisted publication_completed=true.",
                    component="knowledge_publication_evidence",
                )
            )
        if not publication_evidence.publication_succeeded:
            publication_issues.append(
                _issue(
                    "knowledge_publication_not_succeeded",
                    "Knowledge Publication requires persisted publication_succeeded=true.",
                    component="knowledge_publication_evidence",
                )
            )
        if not publication_evidence.knowledge_published:
            publication_issues.append(
                _issue(
                    "knowledge_publication_not_published",
                    "Knowledge Publication requires persisted knowledge_published=true.",
                    component="knowledge_publication_evidence",
                )
            )
        if publication_evidence.published_chunk_count < 1:
            publication_issues.append(
                _issue(
                    "knowledge_publication_chunk_count_empty",
                    "Knowledge Publication requires persisted published_chunk_count >= 1.",
                    component="knowledge_publication_evidence",
                )
            )
        if publication_evidence.record_persistence_status != "persisted":
            publication_issues.append(
                _issue(
                    "knowledge_publication_persistence_invalid",
                    "Knowledge Publication evidence must have persistence_status=persisted.",
                    component="knowledge_publication_evidence",
                )
            )

    publication_ready = bool(processing_ready and publication_evidence is not None and not publication_issues)
    publication_id = publication_evidence.publication_id if publication_evidence is not None else None

    knowledge_index_gate = evaluate_knowledge_index_search_gate_v1(
        session,
        organization_id=organization_id,
        artifact_id=str(artifact_id),
        publication_id=publication_id,
    )
    knowledge_index_gate_payload = serialize_knowledge_index_search_gate_v1(knowledge_index_gate)
    knowledge_index_evidence = knowledge_index_gate.knowledge_index_evidence
    knowledge_index_issues = [dict(item) for item in knowledge_index_gate.blocking_issues]
    if knowledge_index_evidence is not None:
        if knowledge_index_evidence.organization_id != organization_id:
            knowledge_index_issues.append(
                _issue(
                    "knowledge_index_organization_mismatch",
                    "Knowledge Index evidence does not match the active organization scope.",
                    component="knowledge_index_evidence",
                )
            )
        if knowledge_index_evidence.artifact_id != str(artifact_id):
            knowledge_index_issues.append(
                _issue(
                    "knowledge_index_artifact_mismatch",
                    "Knowledge Index evidence does not match the Product Acceptance artifact.",
                    component="knowledge_index_evidence",
                )
            )
        if publication_id and knowledge_index_evidence.publication_id != publication_id:
            knowledge_index_issues.append(
                _issue(
                    "knowledge_index_publication_mismatch",
                    "Knowledge Index evidence does not match persisted Knowledge Publication evidence.",
                    component="knowledge_index_evidence",
                )
            )
        if str(knowledge_index_evidence.document_record_id or "") != str(artifact.document_record_id):
            knowledge_index_issues.append(
                _issue(
                    "knowledge_index_document_record_mismatch",
                    "Knowledge Index evidence does not match the artifact document record lineage.",
                    component="knowledge_index_evidence",
                )
            )
        if str(knowledge_index_evidence.document_version_id or "") != str(artifact.document_version_id):
            knowledge_index_issues.append(
                _issue(
                    "knowledge_index_document_version_mismatch",
                    "Knowledge Index evidence does not match the artifact document version lineage.",
                    component="knowledge_index_evidence",
                )
            )
        if knowledge_index_evidence.status != "indexed":
            knowledge_index_issues.append(
                _issue(
                    "knowledge_index_not_indexed",
                    "Knowledge Index evidence requires status=indexed.",
                    component="knowledge_index_evidence",
                )
            )

    knowledge_index_ready = bool(
        publication_ready
        and knowledge_index_gate.ready
        and knowledge_index_evidence is not None
        and not knowledge_index_issues
    )

    return {
        "runtime_evidence_schema_version": PRODUCT_ACCEPTANCE_RUNTIME_EVIDENCE_SCHEMA_VERSION,
        "authority": "postgresql",
        "organization_id": str(organization_id),
        "artifact_id": str(artifact_id),
        "document_record_id": str(artifact.document_record_id),
        "document_version_id": str(artifact.document_version_id),
        "processing": {
            **processing_payload,
            "ready": processing_ready,
            "blocking_issues": processing_issues,
        },
        "chunking": {
            "contract": "ProcessingEvidenceV1",
            "processing_evidence_id": processing_payload.get("processing_evidence_id"),
            "organization_id": processing_payload.get("organization_id"),
            "document_record_id": processing_payload.get("document_record_id"),
            "document_version_id": processing_payload.get("document_version_id"),
            "chunk_count": chunk_count,
            "ready": chunking_ready,
            "blocking_issues": chunking_issues,
            "authority": "postgresql",
        },
        "knowledge_publication": {
            "ready": publication_ready,
            "evidence": _publication_evidence_payload(publication_evidence),
            "blocking_issues": publication_issues,
            "authority": "postgresql",
        },
        "knowledge_index": {
            **knowledge_index_gate_payload,
            "ready": knowledge_index_ready,
            "evidence": _knowledge_index_evidence_payload(knowledge_index_evidence),
            "blocking_issues": knowledge_index_issues,
            "authority": "postgresql",
        },
    }


def build_enterprise_search_runtime_evidence(
    session: Session,
    *,
    organization_id: uuid.UUID,
    evidence_id: uuid.UUID,
    expected_query: str,
    expected_artifact_id: str,
    expected_knowledge_document_id: str,
) -> dict[str, Any]:
    """Verify the exact Enterprise Search evidence produced by Product Acceptance."""

    evidence = read_enterprise_search_evidence_v1(
        session,
        organization_id=organization_id,
        evidence_id=evidence_id,
    )
    issues: list[dict[str, Any]] = []
    result_artifact_ids: set[str] = set()
    result_knowledge_document_ids: set[str] = set()

    if evidence is None:
        issues.append(
            _issue(
                "enterprise_search_evidence_missing",
                "Enterprise Search requires persisted EnterpriseSearchEvidenceV1 in the active organization scope.",
                component="enterprise_search_evidence",
            )
        )
    else:
        results = evidence.payload.get("results") if isinstance(evidence.payload.get("results"), list) else []
        for result in results:
            if not isinstance(result, dict):
                continue
            if result.get("artifact_id"):
                result_artifact_ids.add(str(result["artifact_id"]))
            if result.get("knowledge_document_id"):
                result_knowledge_document_ids.add(str(result["knowledge_document_id"]))

        if evidence.organization_id != organization_id:
            issues.append(
                _issue(
                    "enterprise_search_organization_mismatch",
                    "Enterprise Search evidence does not match the active organization scope.",
                    component="enterprise_search_evidence",
                )
            )
        if evidence.query != expected_query:
            issues.append(
                _issue(
                    "enterprise_search_query_mismatch",
                    "Enterprise Search evidence does not match the Product Acceptance query.",
                    component="enterprise_search_evidence",
                )
            )
        if evidence.search_status != "completed":
            issues.append(
                _issue(
                    "enterprise_search_not_completed",
                    "Enterprise Search evidence requires search_status=completed.",
                    component="enterprise_search_evidence",
                )
            )
        if evidence.result_count < 1:
            issues.append(
                _issue(
                    "enterprise_search_result_count_empty",
                    "Enterprise Search evidence requires persisted result_count >= 1.",
                    component="enterprise_search_evidence",
                )
            )
        if not evidence.search_uses_postgresql or not evidence.search_uses_postgresql_fts:
            issues.append(
                _issue(
                    "enterprise_search_postgresql_fts_not_used",
                    "Enterprise Search evidence must prove PostgreSQL FTS execution.",
                    component="enterprise_search_evidence",
                )
            )
        if evidence.semantic_search_used or evidence.embeddings_required or evidence.ai_required:
            issues.append(
                _issue(
                    "enterprise_search_optional_ai_contract_invalid",
                    "Enterprise Search Product Acceptance must not require semantic search, embeddings, or AI.",
                    component="enterprise_search_evidence",
                )
            )
        if evidence.persistence_status != "persisted":
            issues.append(
                _issue(
                    "enterprise_search_persistence_invalid",
                    "Enterprise Search evidence must have persistence_status=persisted.",
                    component="enterprise_search_evidence",
                )
            )
        if expected_artifact_id not in result_artifact_ids:
            issues.append(
                _issue(
                    "enterprise_search_artifact_lineage_mismatch",
                    "Enterprise Search evidence does not contain the Product Acceptance artifact.",
                    component="enterprise_search_evidence",
                )
            )
        if expected_knowledge_document_id not in result_knowledge_document_ids:
            issues.append(
                _issue(
                    "enterprise_search_knowledge_document_lineage_mismatch",
                    "Enterprise Search evidence does not contain the authoritative Knowledge Index document.",
                    component="enterprise_search_evidence",
                )
            )

    return {
        "runtime_evidence_schema_version": PRODUCT_ACCEPTANCE_RUNTIME_EVIDENCE_SCHEMA_VERSION,
        "authority": "postgresql",
        "organization_id": str(organization_id),
        "evidence_id": str(evidence_id),
        "expected_query": expected_query,
        "expected_artifact_id": expected_artifact_id,
        "expected_knowledge_document_id": expected_knowledge_document_id,
        "result_artifact_ids": sorted(result_artifact_ids),
        "result_knowledge_document_ids": sorted(result_knowledge_document_ids),
        "evidence": _enterprise_search_evidence_payload(evidence),
        "ready": evidence is not None and not issues,
        "blocking_issues": issues,
    }
