from __future__ import annotations

import uuid

from sqlalchemy import String, cast, select
from sqlalchemy.orm import Session

from app.contracts.knowledge_index import KnowledgeIndexEvidenceV1
from app.models.documents import DocumentVersion
from app.models.knowledge_index import KnowledgeDocument
from app.services.knowledge_index_contract_projection import project_knowledge_index_evidence_v1


def read_knowledge_index_evidence_v1(
    session: Session,
    *,
    organization_id: uuid.UUID,
    knowledge_document_id: uuid.UUID,
) -> KnowledgeIndexEvidenceV1 | None:
    """Read organization-scoped knowledge-index evidence from PostgreSQL.

    Tenant scope is enforced in the SQL query through the persisted
    DocumentVersion referenced by KnowledgeDocument. Metadata and transient
    runtime state are not used to determine organization ownership.
    """

    row = session.execute(
        select(KnowledgeDocument, DocumentVersion)
        .join(
            DocumentVersion,
            KnowledgeDocument.document_version_id == cast(DocumentVersion.id, String),
        )
        .where(
            KnowledgeDocument.id == knowledge_document_id,
            DocumentVersion.organization_id == organization_id,
        )
    ).first()
    if row is None:
        return None

    document, document_version = row
    return project_knowledge_index_evidence_v1(
        document,
        document_version=document_version,
    )
