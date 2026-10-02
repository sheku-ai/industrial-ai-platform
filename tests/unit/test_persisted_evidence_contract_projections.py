from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from app.contracts.knowledge_index import KNOWLEDGE_INDEX_EVIDENCE_CONTRACT_VERSION
from app.contracts.knowledge_publication import KNOWLEDGE_PUBLICATION_EVIDENCE_CONTRACT_VERSION
from app.contracts.processing import PROCESSING_EVIDENCE_CONTRACT_VERSION
from app.models.documents import DocumentVersion
from app.models.knowledge_index import KnowledgeDocument
from app.models.processing import ProcessingRevision
from app.models.runtime import RuntimePersistenceRecord
from app.services.knowledge_index_contract_projection import project_knowledge_index_evidence_v1
from app.services.knowledge_publication_contract_projection import project_knowledge_publication_evidence_v1
from app.services.processing_contract_projection import project_processing_evidence_v1


def test_processing_projection_preserves_persisted_evidence() -> None:
    now = datetime.now(UTC)
    revision = ProcessingRevision(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        document_record_id=uuid.uuid4(),
        document_version_id=uuid.uuid4(),
        runtime_execution_id=uuid.uuid4(),
        runtime_attempt_id=uuid.uuid4(),
        pipeline_profile_id=uuid.uuid4(),
        pipeline_profile_revision="7",
        adapter_key="builtin.text",
        adapter_version="1",
        configuration_snapshot={"mode": "deterministic"},
        source_checksum_sha256="a" * 64,
        status="completed",
        started_at=now,
        completed_at=now,
        content_unit_count=4,
        chunk_count=9,
        manifest_artifact_id=uuid.uuid4(),
    )

    evidence = project_processing_evidence_v1(revision)

    assert evidence.contract_version == PROCESSING_EVIDENCE_CONTRACT_VERSION
    assert evidence.evidence_id == revision.id
    assert evidence.organization_id == revision.organization_id
    assert evidence.document_record_id == revision.document_record_id
    assert evidence.document_version_id == revision.document_version_id
    assert evidence.runtime_execution_id == revision.runtime_execution_id
    assert evidence.runtime_attempt_id == revision.runtime_attempt_id
    assert evidence.status == revision.status
    assert evidence.source_checksum_sha256 == revision.source_checksum_sha256
    assert evidence.content_unit_count == revision.content_unit_count
    assert evidence.chunk_count == revision.chunk_count
    assert evidence.configuration_snapshot == revision.configuration_snapshot
    assert evidence.configuration_snapshot is not revision.configuration_snapshot


def test_knowledge_publication_projection_preserves_persisted_evidence() -> None:
    now = datetime.now(UTC)
    organization_id = uuid.uuid4()
    evidence_id = uuid.uuid4()
    artifact_id = str(uuid.uuid4())
    payload = {
        "organization_id": str(organization_id),
        "publication_id": "knowledge-publication:1",
        "publication_status": "completed",
        "publication_completed": True,
        "publication_succeeded": True,
        "knowledge_published": True,
        "published_chunk_count": 3,
    }
    record = RuntimePersistenceRecord(
        id=evidence_id,
        execution_id="processing-session:1",
        runtime_domain="knowledge_publication",
        record_type="publication_result",
        record_key="knowledge-publication:1",
        artifact_id=artifact_id,
        processing_session_id="processing-session:1",
        execution_status="completed",
        summary={},
        payload=payload,
        validation={},
        metrics={},
        persistence_status="persisted",
        occurred_at=now,
        persisted_at=now,
        created_at=now,
        updated_at=now,
    )

    evidence = project_knowledge_publication_evidence_v1(record, organization_id=organization_id)

    assert evidence.contract_version == KNOWLEDGE_PUBLICATION_EVIDENCE_CONTRACT_VERSION
    assert evidence.evidence_id == evidence_id
    assert evidence.organization_id == organization_id
    assert evidence.execution_id == record.execution_id
    assert evidence.artifact_id == artifact_id
    assert evidence.publication_id == payload["publication_id"]
    assert evidence.publication_status == "completed"
    assert evidence.publication_completed is True
    assert evidence.publication_succeeded is True
    assert evidence.knowledge_published is True
    assert evidence.published_chunk_count == 3
    assert evidence.record_persistence_status == "persisted"
    assert evidence.payload == payload
    assert evidence.payload is not record.payload


def test_knowledge_index_projection_uses_persisted_document_version_for_organization_scope() -> None:
    now = datetime.now(UTC)
    organization_id = uuid.uuid4()
    document_record_id = uuid.uuid4()
    document_version_id = uuid.uuid4()
    document_version = DocumentVersion(
        id=document_version_id,
        organization_id=organization_id,
        document_record_id=document_record_id,
        version_number=1,
        status="registered",
    )
    document = KnowledgeDocument(
        id=uuid.uuid4(),
        artifact_id=str(uuid.uuid4()),
        document_record_id=str(document_record_id),
        document_version_id=str(document_version_id),
        publication_id="publication-1",
        status="indexed",
        version=3,
        content_signature="c" * 64,
        metadata_json={"organization_id": str(uuid.uuid4()), "title": "evidence"},
        created_at=now,
        updated_at=now,
    )

    evidence = project_knowledge_index_evidence_v1(document, document_version=document_version)

    assert evidence.contract_version == KNOWLEDGE_INDEX_EVIDENCE_CONTRACT_VERSION
    assert evidence.knowledge_document_id == document.id
    assert evidence.organization_id == organization_id
    assert evidence.organization_id != uuid.UUID(document.metadata_json["organization_id"])
    assert evidence.artifact_id == document.artifact_id
    assert evidence.publication_id == document.publication_id
    assert evidence.index_version == document.version
    assert evidence.content_signature == document.content_signature
    assert evidence.metadata == document.metadata_json
    assert evidence.metadata is not document.metadata_json


def test_knowledge_index_projection_rejects_mismatched_document_lineage() -> None:
    now = datetime.now(UTC)
    document = KnowledgeDocument(
        id=uuid.uuid4(),
        artifact_id=str(uuid.uuid4()),
        document_record_id=str(uuid.uuid4()),
        document_version_id=str(uuid.uuid4()),
        publication_id="publication-1",
        status="indexed",
        version=1,
        content_signature="d" * 64,
        metadata_json={},
        created_at=now,
        updated_at=now,
    )
    document_version = DocumentVersion(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        document_record_id=uuid.uuid4(),
        version_number=1,
        status="registered",
    )

    with pytest.raises(ValueError, match="version does not match persisted document lineage"):
        project_knowledge_index_evidence_v1(document, document_version=document_version)
