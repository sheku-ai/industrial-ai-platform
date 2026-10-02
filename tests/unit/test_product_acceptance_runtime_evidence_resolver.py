from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

from sqlalchemy.orm import Session

from app.models.documents import Artifact, DocumentVersion
from app.models.knowledge_index import KnowledgeDocument
from app.models.processing import ProcessingRevision
from app.models.runtime import RuntimePersistenceRecord
from app.services.product_acceptance.runtime_evidence import (
    build_document_runtime_evidence,
    build_enterprise_search_runtime_evidence,
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


def _processing_revision(*, artifact: Artifact, evidence_id: uuid.UUID) -> ProcessingRevision:
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
        status="completed",
        started_at=now,
        completed_at=now,
        content_unit_count=1,
        chunk_count=2,
        manifest_artifact_id=None,
    )


def _publication_record(
    *,
    artifact: Artifact,
    evidence_id: uuid.UUID,
) -> RuntimePersistenceRecord:
    now = datetime.now(UTC)
    return RuntimePersistenceRecord(
        id=evidence_id,
        execution_id="processing-session:acceptance",
        runtime_domain="knowledge_publication",
        record_type="publication_result",
        record_key="knowledge-publication:acceptance",
        artifact_id=str(artifact.id),
        processing_session_id="processing-session:acceptance",
        execution_status="completed",
        summary={},
        payload={
            "organization_id": str(artifact.organization_id),
            "publication_id": "knowledge-publication:acceptance",
            "publication_status": "completed",
            "publication_completed": True,
            "publication_succeeded": True,
            "knowledge_published": True,
            "published_chunk_count": 2,
        },
        validation={},
        metrics={},
        persistence_status="persisted",
        occurred_at=now,
        persisted_at=now,
        created_at=now,
        updated_at=now,
    )


def _knowledge_index_lineage(*, artifact: Artifact, knowledge_document_id: uuid.UUID):
    now = datetime.now(UTC)
    document = KnowledgeDocument(
        id=knowledge_document_id,
        artifact_id=str(artifact.id),
        document_record_id=str(artifact.document_record_id),
        document_version_id=str(artifact.document_version_id),
        publication_id="knowledge-publication:acceptance",
        status="indexed",
        version=1,
        content_signature="a" * 64,
        metadata_json={},
        created_at=now,
        updated_at=now,
    )
    version = DocumentVersion(
        id=artifact.document_version_id,
        organization_id=artifact.organization_id,
        document_record_id=artifact.document_record_id,
        version_number=1,
        status="registered",
    )
    return document, version


def _enterprise_search_record(
    *,
    organization_id: uuid.UUID,
    evidence_id: uuid.UUID,
    artifact_id: uuid.UUID,
    knowledge_document_id: uuid.UUID,
) -> tuple[RuntimePersistenceRecord, list[RuntimePersistenceRecord]]:
    now = datetime.now(UTC)
    execution_id = "enterprise-search:0123456789abcdef01234567"
    search_result_id = "search-result:acceptance"
    citation_id = "citation:acceptance"
    content_hash = "a" * 64
    result_payload = {
        "search_result_id": search_result_id,
        "organization_id": str(organization_id),
        "artifact_id": str(artifact_id),
        "knowledge_document_id": str(knowledge_document_id),
        "knowledge_chunk_id": str(uuid.uuid4()),
        "published_chunk_id": "published-chunk:acceptance",
        "content_hash": content_hash,
        "rank": 1,
        "score": 1.0,
    }
    citation_payload = {
        "citation_id": citation_id,
        "organization_id": str(organization_id),
        "artifact_id": str(artifact_id),
        "knowledge_document_id": str(knowledge_document_id),
        "knowledge_chunk_id": result_payload["knowledge_chunk_id"],
        "published_chunk_id": result_payload["published_chunk_id"],
        "content_hash": content_hash,
        "source": "knowledge_chunk",
    }
    result_set = RuntimePersistenceRecord(
        id=evidence_id,
        execution_id=execution_id,
        runtime_domain="enterprise_search",
        record_type="search_result_set",
        record_key="search-session-acceptance",
        artifact_id=str(artifact_id),
        processing_session_id=None,
        execution_status="completed",
        summary={},
        payload={
            "organization_id": str(organization_id),
            "search_session_id": "search-session-acceptance",
            "query": "inspection",
            "normalized_query": "inspection",
            "search_status": "completed",
            "search_completed": True,
            "ranking_model": "postgres_ts_rank_cd_simple_v1",
            "total_count": 1,
            "result_count": 1,
            "offset": 0,
            "limit": 5,
            "has_more": False,
            "results": [result_payload],
            "citations": [citation_payload],
            "search_uses_postgresql": True,
            "search_uses_postgresql_fts": True,
            "semantic_search_used": False,
            "embeddings_required": False,
            "ai_required": False,
        },
        validation={"validation_status": "valid", "valid": True},
        metrics={},
        persistence_status="persisted",
        occurred_at=now,
        persisted_at=now,
        created_at=now,
        updated_at=now,
    )
    result_record = RuntimePersistenceRecord(
        execution_id=execution_id,
        runtime_domain="enterprise_search",
        record_type="search_result",
        record_key=search_result_id,
        artifact_id=str(artifact_id),
        processing_session_id=None,
        execution_status="completed",
        content_hash=content_hash,
        summary={},
        payload=result_payload,
        validation={},
        metrics={},
        persistence_status="persisted",
        occurred_at=now,
        persisted_at=now,
        created_at=now,
        updated_at=now,
    )
    citation_record = RuntimePersistenceRecord(
        execution_id=execution_id,
        runtime_domain="enterprise_search",
        record_type="citation",
        record_key=citation_id,
        artifact_id=str(artifact_id),
        processing_session_id=None,
        execution_status="completed",
        content_hash=content_hash,
        summary={},
        payload=citation_payload,
        validation={},
        metrics={},
        persistence_status="persisted",
        occurred_at=now,
        persisted_at=now,
        created_at=now,
        updated_at=now,
    )
    return result_set, [result_record, citation_record]


def test_runtime_evidence_resolver_uses_scoped_persisted_contracts() -> None:
    organization_id = uuid.uuid4()
    artifact_id = uuid.uuid4()
    processing_evidence_id = uuid.uuid4()
    publication_evidence_id = uuid.uuid4()
    knowledge_document_id = uuid.uuid4()
    artifact = _artifact(artifact_id=artifact_id, organization_id=organization_id)
    revision = _processing_revision(artifact=artifact, evidence_id=processing_evidence_id)
    publication = _publication_record(artifact=artifact, evidence_id=publication_evidence_id)
    knowledge_document, document_version = _knowledge_index_lineage(
        artifact=artifact,
        knowledge_document_id=knowledge_document_id,
    )
    session = MagicMock(spec=Session)
    session.scalar.side_effect = [
        artifact,
        artifact,
        processing_evidence_id,
        revision,
        publication_evidence_id,
        publication,
        knowledge_document_id,
    ]
    session.execute.return_value = SimpleNamespace(first=lambda: (knowledge_document, document_version))

    result = build_document_runtime_evidence(
        session,
        organization_id=organization_id,
        artifact_id=artifact_id,
    )

    assert result["authority"] == "postgresql"
    assert result["organization_id"] == str(organization_id)
    assert result["document_record_id"] == str(artifact.document_record_id)
    assert result["document_version_id"] == str(artifact.document_version_id)
    assert result["processing"]["ready"] is True
    assert result["processing"]["contract"] == "ProcessingEvidenceV1"
    assert result["chunking"]["ready"] is True
    assert result["chunking"]["chunk_count"] == 2
    assert result["knowledge_publication"]["ready"] is True
    assert result["knowledge_publication"]["evidence"]["contract"] == "KnowledgePublicationEvidenceV1"
    assert result["knowledge_index"]["ready"] is True
    assert result["knowledge_index"]["contract"] == "KnowledgeIndexEvidenceV1"
    assert result["knowledge_index"]["evidence"]["knowledge_document_id"] == str(knowledge_document_id)

    artifact_statement = session.scalar.call_args_list[0].args[0]
    artifact_sql = str(artifact_statement.compile(compile_kwargs={"literal_binds": True}))
    assert "artifacts.id" in artifact_sql
    assert "artifacts.organization_id" in artifact_sql

    publication_statement = session.scalar.call_args_list[4].args[0]
    publication_sql = str(publication_statement.compile(compile_kwargs={"literal_binds": True}))
    assert "knowledge_publication" in publication_sql
    assert "publication_result" in publication_sql
    assert "artifact_id" in publication_sql
    assert "organization_id" in publication_sql


def test_runtime_evidence_resolver_does_not_cross_organization_boundary() -> None:
    session = MagicMock(spec=Session)
    session.scalar.return_value = None

    result = build_document_runtime_evidence(
        session,
        organization_id=uuid.uuid4(),
        artifact_id=uuid.uuid4(),
    )

    assert result["authority"] == "postgresql"
    assert result["processing"]["ready"] is False
    assert result["chunking"]["ready"] is False
    assert result["knowledge_publication"]["ready"] is False
    assert result["knowledge_index"]["ready"] is False
    assert session.scalar.call_count == 1


def test_enterprise_search_runtime_evidence_requires_exact_persisted_lineage() -> None:
    organization_id = uuid.uuid4()
    artifact_id = uuid.uuid4()
    knowledge_document_id = uuid.uuid4()
    evidence_id = uuid.uuid4()
    record, child_records = _enterprise_search_record(
        organization_id=organization_id,
        evidence_id=evidence_id,
        artifact_id=artifact_id,
        knowledge_document_id=knowledge_document_id,
    )
    session = MagicMock(spec=Session)
    session.scalar.return_value = record
    session.scalars.return_value.all.return_value = child_records

    result = build_enterprise_search_runtime_evidence(
        session,
        organization_id=organization_id,
        evidence_id=evidence_id,
        expected_query="inspection",
        expected_artifact_id=str(artifact_id),
        expected_knowledge_document_id=str(knowledge_document_id),
    )

    assert result["authority"] == "postgresql"
    assert result["ready"] is True
    assert result["evidence"]["contract"] == "EnterpriseSearchEvidenceV1"
    assert result["evidence"]["evidence_id"] == str(evidence_id)
    assert result["evidence"]["persistence_status"] == "persisted"
    assert result["result_artifact_ids"] == [str(artifact_id)]
    assert result["result_knowledge_document_ids"] == [str(knowledge_document_id)]


def test_enterprise_search_runtime_evidence_rejects_other_knowledge_document() -> None:
    organization_id = uuid.uuid4()
    artifact_id = uuid.uuid4()
    knowledge_document_id = uuid.uuid4()
    evidence_id = uuid.uuid4()
    record, child_records = _enterprise_search_record(
        organization_id=organization_id,
        evidence_id=evidence_id,
        artifact_id=artifact_id,
        knowledge_document_id=knowledge_document_id,
    )
    session = MagicMock(spec=Session)
    session.scalar.return_value = record
    session.scalars.return_value.all.return_value = child_records

    result = build_enterprise_search_runtime_evidence(
        session,
        organization_id=organization_id,
        evidence_id=evidence_id,
        expected_query="inspection",
        expected_artifact_id=str(artifact_id),
        expected_knowledge_document_id=str(uuid.uuid4()),
    )

    assert result["ready"] is False
    assert "enterprise_search_knowledge_document_lineage_mismatch" in {
        item["code"] for item in result["blocking_issues"]
    }
