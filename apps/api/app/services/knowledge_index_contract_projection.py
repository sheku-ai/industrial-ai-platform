from __future__ import annotations

from app.contracts.knowledge_index import KnowledgeIndexEvidenceV1
from app.models.documents import DocumentVersion
from app.models.knowledge_index import KnowledgeDocument


def project_knowledge_index_evidence_v1(
    document: KnowledgeDocument,
    *,
    document_version: DocumentVersion,
) -> KnowledgeIndexEvidenceV1:
    """Project persisted knowledge-index evidence into the canonical v1 contract.

    Organization scope comes from the authoritative persisted DocumentVersion
    referenced by the indexed KnowledgeDocument. Metadata and transient runtime
    flags are never accepted as tenancy authority.
    """

    if document.document_version_id != str(document_version.id):
        raise ValueError("knowledge document version does not match persisted document lineage")
    if document.document_record_id and document.document_record_id != str(document_version.document_record_id):
        raise ValueError("knowledge document record does not match persisted document lineage")

    return KnowledgeIndexEvidenceV1(
        knowledge_document_id=document.id,
        organization_id=document_version.organization_id,
        artifact_id=document.artifact_id,
        publication_id=document.publication_id,
        document_record_id=document.document_record_id,
        document_version_id=document.document_version_id,
        status=document.status,
        index_version=document.version,
        content_signature=document.content_signature,
        created_at=document.created_at,
        updated_at=document.updated_at,
        metadata=dict(document.metadata_json or {}),
    )
