from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts.knowledge_publication import KnowledgePublicationEvidenceV1
from app.models.runtime import RuntimePersistenceRecord
from app.services.knowledge_publication_contract_projection import (
    project_knowledge_publication_evidence_v1,
)


def read_knowledge_publication_evidence_v1(
    session: Session,
    *,
    organization_id: uuid.UUID,
    evidence_id: uuid.UUID,
) -> KnowledgePublicationEvidenceV1 | None:
    """Read organization-scoped Knowledge Publication evidence from PostgreSQL."""

    record = session.scalar(
        select(RuntimePersistenceRecord).where(
            RuntimePersistenceRecord.id == evidence_id,
            RuntimePersistenceRecord.runtime_domain == "knowledge_publication",
            RuntimePersistenceRecord.record_type == "publication_result",
            RuntimePersistenceRecord.payload["organization_id"].astext == str(organization_id),
        )
    )
    if record is None:
        return None
    return project_knowledge_publication_evidence_v1(record, organization_id=organization_id)
