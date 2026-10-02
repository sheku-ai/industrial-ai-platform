from __future__ import annotations

import uuid
from typing import Any

from app.contracts.knowledge_publication import KnowledgePublicationEvidenceV1
from app.models.runtime import RuntimePersistenceRecord


def _required_bool(payload: dict[str, Any], key: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        raise ValueError(f"knowledge publication evidence requires boolean {key}")
    return value


def _required_int(payload: dict[str, Any], key: str) -> int:
    value = payload.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"knowledge publication evidence requires integer {key}")
    return value


def project_knowledge_publication_evidence_v1(
    record: RuntimePersistenceRecord,
    *,
    organization_id: uuid.UUID,
) -> KnowledgePublicationEvidenceV1:
    """Project persisted Knowledge Publication result into the canonical contract."""

    if record.runtime_domain != "knowledge_publication":
        raise ValueError("knowledge publication evidence requires knowledge_publication runtime domain")
    if record.record_type != "publication_result":
        raise ValueError("knowledge publication evidence requires publication_result record type")

    payload = dict(record.payload or {})
    try:
        persisted_organization_id = uuid.UUID(str(payload.get("organization_id")))
    except (TypeError, ValueError) as exc:
        raise ValueError("knowledge publication evidence requires persisted organization_id") from exc
    if persisted_organization_id != organization_id:
        raise ValueError("knowledge publication evidence does not match requested organization scope")

    publication_status = payload.get("publication_status")
    if not isinstance(publication_status, str) or not publication_status:
        raise ValueError("knowledge publication evidence requires publication_status")

    return KnowledgePublicationEvidenceV1(
        evidence_id=record.id,
        organization_id=persisted_organization_id,
        execution_id=record.execution_id,
        artifact_id=record.artifact_id,
        processing_session_id=record.processing_session_id,
        publication_id=str(payload.get("publication_id")) if payload.get("publication_id") is not None else None,
        publication_status=publication_status,
        publication_completed=_required_bool(payload, "publication_completed"),
        publication_succeeded=_required_bool(payload, "publication_succeeded"),
        knowledge_published=_required_bool(payload, "knowledge_published"),
        published_chunk_count=_required_int(payload, "published_chunk_count"),
        record_persistence_status=record.persistence_status,
        occurred_at=record.occurred_at,
        persisted_at=record.persisted_at,
        payload=dict(payload),
    )
