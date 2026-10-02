from types import SimpleNamespace

from app.db.session import SessionLocal
from app.services.platform_read_projections import (
    DOCUMENT_MANAGEMENT_VERTICAL_DOMAINS,
    build_platform_read_projections,
    project_document_management_vertical_evidence,
)


def test_platform_read_projections_preserve_governed_summary_contracts() -> None:
    db = SessionLocal()
    try:
        projections = build_platform_read_projections(db)
    finally:
        db.close()

    documents = projections["documents"]
    knowledge = projections["knowledge"]
    assistants = projections["assistants"]

    assert documents["workspace_summary"]["postgresql_source_of_truth"] is True
    assert knowledge["workspace_summary"]["postgresql_source_of_truth"] is True
    assert assistants["workspace_summary"]["postgresql_source_of_truth"] is True
    assert knowledge["chunk_overview"]["indexed_chunks"] <= knowledge["chunk_overview"]["total_chunks"]
    assert all(item["ownership_scope"] != "legacy_unscoped" for item in assistants["assistant_definitions"])
    assert all(item["organization_id"] for item in assistants["conversations"])


def test_platform_read_projection_counts_only_owned_assistant_artifacts() -> None:
    db = SessionLocal()
    try:
        assistants = build_platform_read_projections(db)["assistants"]
    finally:
        db.close()

    counts = assistants["runtime_executions"]
    assert counts["assistant_sessions"] >= counts["response_executions"]
    assert counts["retrieval_executions"] >= counts["citation_verification_executions"]


def _vertical_record(domain: str) -> SimpleNamespace:
    contract = {
        "storage": (
            "verification_result",
            "storage_verified",
            {"storage_verified": True, "object_exists": True},
        ),
        "processing": (
            "processing_result",
            "completed",
            {"processing_completed": True, "text_extracted": True},
        ),
        "chunk": (
            "chunk_result",
            "completed",
            {"chunks_created": True, "chunk_count": 1},
        ),
        "knowledge_publication": (
            "publication_result",
            "completed",
            {"knowledge_published": True, "published_chunk_count": 1},
        ),
        "knowledge_index": (
            "index_result",
            "completed",
            {
                "index_succeeded": True,
                "document_indexed": True,
                "metadata_persisted": True,
                "chunks_indexed": 1,
            },
        ),
        "enterprise_search": (
            "search_result_set",
            "completed",
            {
                "search_completed": True,
                "search_uses_postgresql_fts": True,
                "result_count": 1,
            },
        ),
    }
    record_type, execution_status, summary = contract[domain]
    return SimpleNamespace(
        runtime_domain=domain,
        record_type=record_type,
        execution_status=execution_status,
        execution_id="document-vertical-1",
        persistence_status="persisted",
        summary=summary,
    )


def test_document_management_vertical_requires_one_complete_persisted_execution() -> None:
    evidence = project_document_management_vertical_evidence(
        [_vertical_record(domain) for domain in DOCUMENT_MANAGEMENT_VERTICAL_DOMAINS],
        stored_artifact_count=1,
        indexed_document_count=1,
        indexed_chunk_count=1,
    )

    assert evidence["ready"] is True
    assert evidence["postgresql_source_of_truth"] is True
    assert evidence["complete_execution_count"] == 1
    assert all(stage["ready"] for stage in evidence["stages"].values())


def test_document_management_vertical_rejects_incomplete_persisted_execution() -> None:
    evidence = project_document_management_vertical_evidence(
        [
            _vertical_record(domain)
            for domain in DOCUMENT_MANAGEMENT_VERTICAL_DOMAINS
            if domain != "enterprise_search"
        ],
        stored_artifact_count=1,
        indexed_document_count=1,
        indexed_chunk_count=1,
    )

    assert evidence["ready"] is False
    assert evidence["complete_execution_count"] == 0
    assert evidence["stages"]["enterprise_search"]["ready"] is False
