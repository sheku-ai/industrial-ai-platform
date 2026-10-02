from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.ai import KnowledgeSource
from app.models.assistant_runtime import (
    AssistantCitationVerification,
    AssistantContextPackage,
    AssistantDefinition,
    AssistantLlmExecution,
    AssistantLlmInvocationPlan,
    AssistantPromptPackage,
    AssistantResponse,
    AssistantRetrievalExecutionPlan,
    AssistantRetrievalPlan,
    AssistantRuntimeRun,
    AssistantSearchExecution,
    AssistantSession,
    Conversation,
)
from app.models.documents import Artifact, Chunk, Collection, DocumentRecord, DocumentVersion
from app.models.knowledge_index import KnowledgeChunk, KnowledgeDocument
from app.models.processing import ProcessingRevision
from app.models.runtime import RuntimePersistenceRecord

COMPLETED_STATES = ("completed", "succeeded", "success", "indexed", "published", "ready")
DOCUMENT_MANAGEMENT_VERTICAL_DOMAINS = (
    "storage",
    "processing",
    "chunk",
    "knowledge_publication",
    "knowledge_index",
    "enterprise_search",
)


def _count(db: Session, model: Any, *criteria: Any) -> int:
    primary_key = next(iter(model.__table__.primary_key.columns))
    statement = select(func.count(primary_key))
    if criteria:
        statement = statement.where(*criteria)
    return int(db.scalar(statement) or 0)


def _owned_count(db: Session, model: Any) -> int:
    return _count(db, model, model.ownership_scope != "legacy_unscoped")


def _positive_int(value: Any) -> bool:
    try:
        return int(value or 0) > 0
    except (TypeError, ValueError):
        return False


def _document_vertical_record_succeeded(record: RuntimePersistenceRecord) -> bool:
    summary = record.summary if isinstance(record.summary, dict) else {}
    if record.runtime_domain == "storage":
        return bool(
            record.record_type == "verification_result"
            and record.execution_status == "storage_verified"
            and summary.get("storage_verified") is True
            and summary.get("object_exists") is True
        )
    if record.runtime_domain == "processing":
        return bool(
            record.record_type == "processing_result"
            and record.execution_status == "completed"
            and summary.get("processing_completed") is True
            and summary.get("text_extracted") is True
        )
    if record.runtime_domain == "chunk":
        return bool(
            record.record_type == "chunk_result"
            and record.execution_status == "completed"
            and summary.get("chunks_created") is True
            and _positive_int(summary.get("chunk_count"))
        )
    if record.runtime_domain == "knowledge_publication":
        return bool(
            record.record_type == "publication_result"
            and record.execution_status == "completed"
            and summary.get("knowledge_published") is True
            and _positive_int(summary.get("published_chunk_count"))
        )
    if record.runtime_domain == "knowledge_index":
        return bool(
            record.record_type == "index_result"
            and record.execution_status == "completed"
            and summary.get("index_succeeded") is True
            and summary.get("document_indexed") is True
            and summary.get("metadata_persisted") is True
            and _positive_int(summary.get("chunks_indexed"))
        )
    if record.runtime_domain == "enterprise_search":
        return bool(
            record.record_type == "search_result_set"
            and record.execution_status == "completed"
            and summary.get("search_completed") is True
            and summary.get("search_uses_postgresql_fts") is True
            and _positive_int(summary.get("result_count"))
        )
    return False


def project_document_management_vertical_evidence(
    records: list[RuntimePersistenceRecord],
    *,
    stored_artifact_count: int,
    indexed_document_count: int,
    indexed_chunk_count: int,
) -> dict[str, Any]:
    successful_executions = {domain: set() for domain in DOCUMENT_MANAGEMENT_VERTICAL_DOMAINS}
    for record in records:
        if record.persistence_status == "persisted" and _document_vertical_record_succeeded(record):
            successful_executions[record.runtime_domain].add(record.execution_id)

    complete_executions = set.intersection(*successful_executions.values())
    stages = {
        domain: {
            "ready": bool(executions),
            "persisted_execution_count": len(executions),
            "source": "runtime.persistence_records",
        }
        for domain, executions in successful_executions.items()
    }
    materialized_state = {
        "stored_artifact_count": stored_artifact_count,
        "indexed_document_count": indexed_document_count,
        "indexed_chunk_count": indexed_chunk_count,
        "ready": bool(stored_artifact_count and indexed_document_count and indexed_chunk_count),
        "source": [
            "documents.artifacts",
            "knowledge.documents",
            "knowledge.chunks",
        ],
    }
    ready = bool(complete_executions and materialized_state["ready"])
    return {
        "ready": ready,
        "postgresql_source_of_truth": True,
        "complete_execution_count": len(complete_executions),
        "required_stages": list(DOCUMENT_MANAGEMENT_VERTICAL_DOMAINS),
        "stages": stages,
        "materialized_state": materialized_state,
    }


def build_document_management_vertical_evidence(db: Session) -> dict[str, Any]:
    records = list(
        db.scalars(
            select(RuntimePersistenceRecord).where(
                RuntimePersistenceRecord.persistence_status == "persisted",
                RuntimePersistenceRecord.runtime_domain.in_(DOCUMENT_MANAGEMENT_VERTICAL_DOMAINS),
            )
        ).all()
    )
    stored_artifact_count = _count(
        db,
        Artifact,
        Artifact.object_key.is_not(None),
        Artifact.checksum_sha256.is_not(None),
        Artifact.size_bytes.is_not(None),
    )
    indexed_document_count = _count(
        db,
        KnowledgeDocument,
        KnowledgeDocument.status.in_(COMPLETED_STATES),
    )
    indexed_chunk_count = _count(
        db,
        KnowledgeChunk,
        KnowledgeChunk.status.in_(COMPLETED_STATES),
    )
    return project_document_management_vertical_evidence(
        records,
        stored_artifact_count=stored_artifact_count,
        indexed_document_count=indexed_document_count,
        indexed_chunk_count=indexed_chunk_count,
    )


def build_platform_read_projections(db: Session) -> dict[str, dict[str, Any]]:
    document_count = _count(db, DocumentRecord)
    version_count = _count(db, DocumentVersion)
    artifact_count = _count(db, Artifact)
    source_chunk_count = _count(db, Chunk)
    processing_count = _count(db, ProcessingRevision, ProcessingRevision.status.in_(COMPLETED_STATES))
    knowledge_document_count = _count(db, KnowledgeDocument)
    indexed_document_count = _count(db, KnowledgeDocument, KnowledgeDocument.status.in_(COMPLETED_STATES))
    knowledge_chunk_count = _count(db, KnowledgeChunk)
    indexed_chunk_count = _count(db, KnowledgeChunk, KnowledgeChunk.status.in_(COMPLETED_STATES))
    collection_count = _count(db, Collection)
    knowledge_source_count = _count(db, KnowledgeSource)

    assistant_rows = db.execute(
        select(
            AssistantDefinition.assistant_id,
            AssistantDefinition.assistant_key,
            AssistantDefinition.assistant_name,
            AssistantDefinition.assistant_status,
            AssistantDefinition.ownership_scope,
            AssistantDefinition.organization_id,
            AssistantDefinition.data_origin,
        ).where(AssistantDefinition.ownership_scope != "legacy_unscoped")
    ).all()
    conversation_rows = db.execute(
        select(
            Conversation.conversation_id,
            Conversation.assistant_id,
            Conversation.conversation_status,
            Conversation.organization_id,
            Conversation.data_origin,
        ).where(Conversation.ownership_scope == "organization")
    ).all()
    assistant_definitions = [
        {
            "assistant_id": str(row.assistant_id),
            "assistant_key": row.assistant_key,
            "assistant_name": row.assistant_name,
            "assistant_status": row.assistant_status,
            "ownership_scope": row.ownership_scope,
            "organization_id": str(row.organization_id) if row.organization_id else None,
            "data_origin": row.data_origin,
        }
        for row in assistant_rows
    ]
    conversations = [
        {
            "conversation_id": str(row.conversation_id),
            "assistant_id": str(row.assistant_id) if row.assistant_id else None,
            "conversation_status": row.conversation_status,
            "organization_id": str(row.organization_id),
            "data_origin": row.data_origin,
        }
        for row in conversation_rows
    ]
    runtime_counts = {
        "assistant_sessions": _owned_count(db, AssistantSession),
        "assistant_runtime_executions": _owned_count(db, AssistantRuntimeRun),
        "retrieval_executions": _owned_count(db, AssistantRetrievalPlan),
        "retrieval_execution_readiness": _owned_count(db, AssistantRetrievalExecutionPlan),
        "enterprise_search_executions": _owned_count(db, AssistantSearchExecution),
        "context_builder_executions": _owned_count(db, AssistantContextPackage),
        "prompt_assembly_executions": _owned_count(db, AssistantPromptPackage),
        "llm_gateway_executions": _owned_count(db, AssistantLlmInvocationPlan),
        "llm_execution_records": _owned_count(db, AssistantLlmExecution),
        "citation_verification_executions": _owned_count(db, AssistantCitationVerification),
        "response_executions": _owned_count(db, AssistantResponse),
    }
    document_ready = document_count > 0
    knowledge_ready = indexed_document_count > 0 and indexed_chunk_count > 0
    assistant_ready = bool(assistant_definitions)

    documents = {
        "runtime_status": "ready" if document_ready else "degraded",
        "workspace_summary": {
            "documents_ready": document_ready,
            "processing_ready": processing_count > 0 or indexed_document_count > 0,
            "postgresql_source_of_truth": True,
        },
        "document_registry": [{"document_count": document_count}] if document_count else [],
        "versions": [{"version_count": version_count}] if version_count else [],
        "storage": {"storage_verification": artifact_count > 0},
        "processing": {
            "processing_state": "ready" if processing_count > 0 or indexed_document_count > 0 else "unknown"
        },
        "chunks": {"chunk_count": source_chunk_count},
        "knowledge": {"knowledge_publication": knowledge_document_count > 0},
        "enterprise_search": {
            "knowledge_index_readiness": indexed_document_count > 0,
            "fts_readiness": indexed_chunk_count > 0,
        },
        "diagnostics": {"blocking_issues": [], "warnings": [], "pending_capabilities": []},
    }
    knowledge = {
        "runtime_status": "ready" if knowledge_ready else "degraded",
        "workspace_summary": {
            "knowledge_ready": indexed_document_count > 0,
            "search_ready": indexed_chunk_count > 0,
            "postgresql_source_of_truth": True,
        },
        "collections": [{"collection_count": collection_count}] if collection_count else [],
        "knowledge_sources": [{"knowledge_source_count": knowledge_source_count}] if knowledge_source_count else [],
        "knowledge_documents": [{"knowledge_document_count": knowledge_document_count}]
        if knowledge_document_count
        else [],
        "chunk_overview": {
            "total_chunks": knowledge_chunk_count,
            "indexed_chunks": indexed_chunk_count,
        },
        "enterprise_search": {"search_ready": indexed_chunk_count > 0},
        "diagnostics": {"blocking_issues": [], "warnings": [], "pending_capabilities": []},
    }
    assistants = {
        "runtime_status": "ready" if assistant_ready else "degraded",
        "workspace_summary": {
            "assistants_ready": assistant_ready,
            "conversations_ready": bool(conversations),
            "citations_ready": runtime_counts["citation_verification_executions"] > 0,
            "postgresql_source_of_truth": True,
        },
        "assistant_definitions": assistant_definitions,
        "conversations": conversations,
        "conversation_turns": [],
        "runtime_executions": runtime_counts,
        "retrieval_and_citations": {
            "enterprise_search_ready": indexed_chunk_count > 0,
            "citation_count": runtime_counts["citation_verification_executions"],
        },
        "diagnostics": {"blocking_issues": [], "warnings": [], "pending_capabilities": []},
    }
    return {"documents": documents, "knowledge": knowledge, "assistants": assistants}
