from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.platform_metadata import build_platform_info
from app.models.assistant_runtime import (
    AssistantContextPackage,
    AssistantDefinition,
    AssistantLlmExecution,
    AssistantPromptPackage,
    AssistantRuntimeRun,
    AssistantSearchExecution,
    Conversation,
    ConversationTurn,
)
from app.models.audit import AuditEvent, AuditHistory
from app.models.documents import Chunk, DocumentRecord, DocumentVersion, IndexingJob, IngestionJob
from app.models.knowledge_index import KnowledgeChunk, KnowledgeDocument
from app.models.runtime import RuntimeExecution, RuntimeExecutionAttempt, RuntimePersistenceRecord
from app.models.runtime_worker import RuntimeWorker
from app.services.reference_tenant import (
    build_reference_tenant_readiness,
    build_reference_tenant_status,
    validate_reference_tenant,
)

PLATFORM_OPERATIONS_RUNTIME_SCHEMA_VERSION = "1"
PLATFORM_OPERATIONS_RUNTIME_NAME = "platform_operations_runtime"

TERMINAL_RUNTIME_STATUSES = {"succeeded", "failed", "cancelled", "expired", "dead_lettered"}
ACTIVE_RUNTIME_STATUSES = {"pending", "scheduled", "leased", "running"}
FAILED_RUNTIME_STATUSES = {"failed", "expired", "dead_lettered"}
PROCESSING_COMPLETED_STATUSES = {"completed", "succeeded", "published", "indexed"}
PROCESSING_FAILED_STATUSES = {"failed", "dead_lettered"}
PROCESSING_PENDING_STATUSES = {"pending", "scheduled", "leased", "running", "processing"}


def _issue(
    code: str,
    message: str,
    *,
    component: str = "platform_operations",
    domain: str | None = None,
) -> dict[str, Any]:
    payload = {"code": code, "message": message, "component": component}
    if domain:
        payload["domain"] = domain
    return payload


def _primary_key(model: Any) -> Any:
    return model.id if hasattr(model, "id") else next(iter(model.__table__.primary_key.columns))


def _count(db: Session, model: Any, *criteria: Any) -> int:
    statement = select(func.count(_primary_key(model)))
    if criteria:
        statement = statement.where(*criteria)
    return int(db.scalar(statement) or 0)


def _count_by(db: Session, model: Any, column: Any, *criteria: Any) -> dict[str, int]:
    statement = select(column, func.count()).select_from(model)
    if criteria:
        statement = statement.where(*criteria)
    rows = db.execute(statement.group_by(column)).all()
    return {str(value or "unknown"): int(count or 0) for value, count in rows}


def _count_in(db: Session, model: Any, column: Any, values: set[str], *criteria: Any) -> int:
    return _count(db, model, column.in_(tuple(values)), *criteria)


def _avg(db: Session, column: Any, *criteria: Any) -> float:
    statement = select(func.avg(column))
    if criteria:
        statement = statement.where(*criteria)
    value = db.scalar(statement)
    return float(value or 0)


def _runtime_domain_records(db: Session, domain: str) -> int:
    return _count(db, RuntimePersistenceRecord, RuntimePersistenceRecord.runtime_domain == domain)


def _owned(model: Any, organization_id: uuid.UUID | None, platform_scope: bool) -> tuple[Any, ...]:
    return () if platform_scope else (model.organization_id == organization_id,)


def _operational_assistant_ids(
    db: Session,
    *,
    organization_id: uuid.UUID | None,
    platform_scope: bool,
) -> list[uuid.UUID]:
    statement = select(AssistantDefinition).where(
        AssistantDefinition.ownership_scope != "legacy_unscoped",
        AssistantDefinition.data_origin != "validation",
    )
    if not platform_scope:
        statement = statement.where(
            (AssistantDefinition.ownership_scope == "global")
            | (
                (AssistantDefinition.ownership_scope == "organization")
                & (AssistantDefinition.organization_id == organization_id)
            )
        )
    return [
        assistant.assistant_id
        for assistant in db.scalars(statement).all()
        if (assistant.runtime_metadata or {}).get("scenario") != "local_product_acceptance"
        and not (assistant.runtime_metadata or {}).get("execution_key")
        and not (assistant.runtime_metadata or {}).get("smoke_runtime")
    ]


def _platform_runtime_section(
    db: Session,
    *,
    organization_id: uuid.UUID | None,
    platform_scope: bool,
) -> dict[str, Any]:
    platform_info = build_platform_info(get_settings()).model_dump()
    execution_criteria = _owned(RuntimeExecution, organization_id, platform_scope)
    runtime_failures = _count_in(
        db, RuntimeExecution, RuntimeExecution.status, FAILED_RUNTIME_STATUSES, *execution_criteria
    )
    active_runtime_sessions = _count_in(
        db, RuntimeExecution, RuntimeExecution.status, ACTIVE_RUNTIME_STATUSES, *execution_criteria
    )
    workers_ready = _count(db, RuntimeWorker, RuntimeWorker.observed_state == "ready")
    workers_total = _count(db, RuntimeWorker)
    running_capabilities = {
        "runtime_executions": _count(db, RuntimeExecution, *execution_criteria),
        "runtime_persistence": _count(db, RuntimePersistenceRecord) if platform_scope else 0,
        "runtime_workers": workers_total,
        "ready_workers": workers_ready,
    }
    unavailable_capabilities = [
        key
        for key, available in {
            "runtime_persistence": running_capabilities["runtime_persistence"] >= 0,
            "runtime_execution_tracking": running_capabilities["runtime_executions"] >= 0,
            "worker_runtime": workers_total == 0 or workers_ready > 0,
        }.items()
        if not available
    ]
    ready = not unavailable_capabilities
    return {
        "overall_runtime_health": "ready" if ready else "degraded",
        "operational_status": "operational" if ready else "attention_required",
        "readiness": {
            "ready": ready,
            "runtime_failures": runtime_failures,
            "active_runtime_sessions": active_runtime_sessions,
            "unavailable_capabilities": unavailable_capabilities,
        },
        "current_version": platform_info.get("product_version"),
        "release_stage": platform_info.get("release_stage"),
        "running_capabilities": running_capabilities,
        "unavailable_capabilities": unavailable_capabilities,
        "feature_flags": platform_info.get("feature_flags") or {},
    }


def _documents_section(
    db: Session,
    *,
    organization_id: uuid.UUID | None,
    platform_scope: bool,
) -> dict[str, Any]:
    record_criteria = _owned(DocumentRecord, organization_id, platform_scope)
    version_criteria = _owned(DocumentVersion, organization_id, platform_scope)
    ingestion_criteria = _owned(IngestionJob, organization_id, platform_scope)
    chunk_criteria = _owned(Chunk, organization_id, platform_scope)
    record_ids = [
        str(item)
        for item in db.scalars(select(DocumentRecord.id).where(*record_criteria)).all()
    ]
    historical_persisted = _count(
        db,
        KnowledgeDocument,
        KnowledgeDocument.document_record_id.in_(record_ids),
        KnowledgeDocument.status.in_(("indexed", "ready")),
    ) if record_ids else 0
    ingestion_status = _count_by(db, IngestionJob, IngestionJob.status, *ingestion_criteria)
    lifecycle_status = _count_by(db, DocumentVersion, DocumentVersion.status, *version_criteria)
    return {
        "registered_documents": _count(db, DocumentRecord, *record_criteria),
        "document_versions": _count(db, DocumentVersion, *version_criteria),
        "processing_queue": _count_in(
            db, IngestionJob, IngestionJob.status, PROCESSING_PENDING_STATUSES, *ingestion_criteria
        ),
        "processing_completed": _count_in(
            db, IngestionJob, IngestionJob.status, PROCESSING_COMPLETED_STATUSES, *ingestion_criteria
        ),
        "historical_persisted_documents": historical_persisted,
        "failed_processing": _count_in(
            db, IngestionJob, IngestionJob.status, PROCESSING_FAILED_STATUSES, *ingestion_criteria
        ),
        "pending_processing": _count_in(
            db, IngestionJob, IngestionJob.status, PROCESSING_PENDING_STATUSES, *ingestion_criteria
        ),
        "lifecycle_statistics": {
            "versions_by_status": lifecycle_status,
            "ingestion_jobs_by_status": ingestion_status,
            "stored_versions": _count(
                db, DocumentVersion, *version_criteria, DocumentVersion.object_store_key.is_not(None)
            ),
            "source_chunks": _count(db, Chunk, *chunk_criteria),
            "indexed_source_chunks": _count(db, Chunk, *chunk_criteria, Chunk.status == "indexed"),
        },
        "ready": _count(db, DocumentRecord, *record_criteria) >= 0,
    }


def _knowledge_section(
    db: Session,
    *,
    organization_id: uuid.UUID | None,
    platform_scope: bool,
) -> dict[str, Any]:
    record_criteria = _owned(DocumentRecord, organization_id, platform_scope)
    record_ids = [str(item) for item in db.scalars(select(DocumentRecord.id).where(*record_criteria)).all()]
    document_criteria = () if platform_scope else (KnowledgeDocument.document_record_id.in_(record_ids),)
    document_ids = list(db.scalars(select(KnowledgeDocument.id).where(*document_criteria)).all())
    chunk_criteria = () if platform_scope else (KnowledgeChunk.knowledge_document_id.in_(document_ids),)
    indexing_criteria = _owned(IndexingJob, organization_id, platform_scope)
    indexed_documents = _count(
        db, KnowledgeDocument, *document_criteria, KnowledgeDocument.status.in_(("indexed", "ready"))
    )
    indexed_chunks = _count(
        db, KnowledgeChunk, *chunk_criteria, KnowledgeChunk.status.in_(("indexed", "ready"))
    )
    pending_indexing = _count_in(
        db,
        IndexingJob,
        IndexingJob.status,
        {"pending", "scheduled", "running", "processing"},
        *indexing_criteria,
    )
    failed_indexing = _count_in(
        db, IndexingJob, IndexingJob.status, {"failed", "dead_lettered"}, *indexing_criteria
    )
    publication_failures = (
        _count(
            db,
            RuntimePersistenceRecord,
            RuntimePersistenceRecord.runtime_domain == "knowledge_publication",
            RuntimePersistenceRecord.persistence_status == "failed",
        )
        if platform_scope
        else 0
    )
    ready = indexed_documents > 0 and indexed_chunks > 0
    return {
        "knowledge_documents": _count(db, KnowledgeDocument, *document_criteria),
        "knowledge_chunks": _count(db, KnowledgeChunk, *chunk_criteria),
        "indexed_documents": indexed_documents,
        "indexed_chunks": indexed_chunks,
        "pending_indexing": pending_indexing,
        "publication_failures": publication_failures,
        "knowledge_health": {
            "ready": ready,
            "documents_by_status": _count_by(db, KnowledgeDocument, KnowledgeDocument.status, *document_criteria),
            "chunks_by_status": _count_by(db, KnowledgeChunk, KnowledgeChunk.status, *chunk_criteria),
            "indexing_jobs_by_status": _count_by(db, IndexingJob, IndexingJob.status, *indexing_criteria),
            "failed_indexing": failed_indexing,
        },
        "ready": ready,
    }


def _enterprise_search_section(
    db: Session,
    knowledge: dict[str, Any],
    *,
    organization_id: uuid.UUID | None,
    platform_scope: bool,
) -> dict[str, Any]:
    operational_assistant_ids = _operational_assistant_ids(
        db, organization_id=organization_id, platform_scope=platform_scope
    )
    search_criteria = (
        *_owned(AssistantSearchExecution, organization_id, platform_scope),
        AssistantSearchExecution.data_origin != "validation",
        AssistantSearchExecution.assistant_id.in_(operational_assistant_ids),
    )
    search_requests = _count(db, AssistantSearchExecution, *search_criteria)
    successful_searches = _count(
        db,
        AssistantSearchExecution,
        *search_criteria,
        AssistantSearchExecution.search_completed.is_(True),
    )
    failed_searches = max(search_requests - successful_searches, 0)
    indexed_chunks = int(knowledge.get("indexed_chunks") or 0)
    searchable_chunks = indexed_chunks
    knowledge_coverage = float(indexed_chunks / searchable_chunks) if searchable_chunks else None
    ready = indexed_chunks > 0
    return {
        "search_requests": search_requests,
        "successful_searches": successful_searches,
        "failed_searches": failed_searches,
        "average_response_time_ms": _avg(db, AssistantSearchExecution.search_duration_ms, *search_criteria),
        "knowledge_coverage": knowledge_coverage,
        "knowledge_coverage_measurement": {
            "definition": "indexed governed knowledge chunks divided by searchable governed knowledge chunks",
            "numerator": indexed_chunks,
            "denominator": searchable_chunks,
            "source": "knowledge.chunks",
            "measurable": searchable_chunks > 0,
        },
        "fts_readiness": {
            "ready": ready,
            "postgresql_fts_source": True,
            "indexed_chunk_count": indexed_chunks,
        },
        "ready": ready,
    }


def _assistant_section(
    db: Session,
    *,
    organization_id: uuid.UUID | None,
    platform_scope: bool,
) -> dict[str, Any]:
    operational_assistant_ids = _operational_assistant_ids(
        db, organization_id=organization_id, platform_scope=platform_scope
    )
    llm_criteria = (
        *_owned(AssistantLlmExecution, organization_id, platform_scope),
        AssistantLlmExecution.data_origin != "validation",
        AssistantLlmExecution.assistant_id.in_(operational_assistant_ids),
    )
    run_criteria = (
        *_owned(AssistantRuntimeRun, organization_id, platform_scope),
        AssistantRuntimeRun.data_origin != "validation",
        AssistantRuntimeRun.assistant_id.in_(operational_assistant_ids),
    )
    conversation_criteria = (
        *_owned(Conversation, organization_id, platform_scope),
        Conversation.data_origin != "validation",
        func.coalesce(Conversation.conversation_metadata["scenario"].as_string(), "")
        != "local_product_acceptance",
        func.coalesce(Conversation.conversation_metadata["execution_key"].as_string(), "") == "",
    )
    turn_criteria = (
        *_owned(ConversationTurn, organization_id, platform_scope),
        ConversationTurn.data_origin != "validation",
        ConversationTurn.assistant_id.in_(operational_assistant_ids),
    )
    context_criteria = (
        *_owned(AssistantContextPackage, organization_id, platform_scope),
        AssistantContextPackage.data_origin != "validation",
        AssistantContextPackage.assistant_id.in_(operational_assistant_ids),
    )
    prompt_criteria = (
        *_owned(AssistantPromptPackage, organization_id, platform_scope),
        AssistantPromptPackage.data_origin != "validation",
        AssistantPromptPackage.assistant_id.in_(operational_assistant_ids),
    )
    llm_executions = _count(db, AssistantLlmExecution, *llm_criteria)
    provider_calls = _count(
        db, AssistantLlmExecution, *llm_criteria, AssistantLlmExecution.provider_called.is_(True)
    )
    assistant_executions = _count(db, AssistantRuntimeRun, *run_criteria)
    assistant_definitions = len(operational_assistant_ids)
    return {
        "assistant_definitions": assistant_definitions,
        "assistant_executions": assistant_executions,
        "conversation_count": _count(db, Conversation, *conversation_criteria),
        "messages": _count(db, ConversationTurn, *turn_criteria),
        "context_generations": _count(db, AssistantContextPackage, *context_criteria),
        "prompt_executions": _count(db, AssistantPromptPackage, *prompt_criteria),
        "llm_executions": llm_executions,
        "llm_disabled_indicator": provider_calls == 0,
        "assistant_runtime_by_status": _count_by(
            db, AssistantRuntimeRun, AssistantRuntimeRun.run_status, *run_criteria
        ),
        "conversation_by_status": _count_by(
            db, Conversation, Conversation.conversation_status, *conversation_criteria
        ),
        "ready": assistant_definitions > 0,
    }


def _runtime_section(
    db: Session,
    *,
    organization_id: uuid.UUID | None,
    platform_scope: bool,
) -> dict[str, Any]:
    execution_criteria = _owned(RuntimeExecution, organization_id, platform_scope)
    attempt_criteria = _owned(RuntimeExecutionAttempt, organization_id, platform_scope)
    active_sessions = _count_in(
        db, RuntimeExecution, RuntimeExecution.status, ACTIVE_RUNTIME_STATUSES, *execution_criteria
    )
    completed_sessions = _count(db, RuntimeExecution, *execution_criteria, RuntimeExecution.status == "succeeded")
    failures = _count_in(
        db, RuntimeExecution, RuntimeExecution.status, FAILED_RUNTIME_STATUSES, *execution_criteria
    )
    retries = _count(db, RuntimeExecutionAttempt, *attempt_criteria, RuntimeExecutionAttempt.attempt_number > 1)
    idempotent_resumptions = _count(
        db, RuntimeExecution, *execution_criteria, RuntimeExecution.idempotency_key.is_not(None)
    )
    storage_reuse = _count(
        db,
        RuntimePersistenceRecord,
        RuntimePersistenceRecord.runtime_domain == "storage",
        RuntimePersistenceRecord.record_type == "storage_reuse",
    ) if platform_scope else 0
    return {
        "active_runtime_sessions": active_sessions,
        "completed_runtime_sessions": completed_sessions,
        "runtime_failures": failures,
        "runtime_retries": retries,
        "idempotent_resumptions": idempotent_resumptions,
        "storage_reuse": storage_reuse,
        "runtime_records_by_domain": _count_by(db, RuntimePersistenceRecord, RuntimePersistenceRecord.runtime_domain)
        if platform_scope
        else {},
        "runtime_executions_by_status": _count_by(
            db, RuntimeExecution, RuntimeExecution.status, *execution_criteria
        ),
        "ready": True,
    }


def _feedback_section(
    db: Session,
    *,
    organization_id: uuid.UUID | None,
    platform_scope: bool,
) -> dict[str, Any]:
    event_criteria = _owned(AuditEvent, organization_id, platform_scope)
    feedback_received = _count(db, AuditEvent, *event_criteria, AuditEvent.resource_type == "feedback")
    feedback_pending = _count(
        db,
        AuditEvent,
        *event_criteria,
        AuditEvent.resource_type == "feedback",
        AuditEvent.metadata_json["status"].astext == "pending",
    )
    recent_events = db.scalars(
        select(AuditEvent)
        .where(*event_criteria)
        .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
        .limit(10)
    ).all()
    recent_activity = [
        {
            "id": item.id,
            "organization_id": item.organization_id,
            "resource_type": item.resource_type,
            "resource_id": item.resource_id,
            "summary": item.summary,
            "created_at": item.created_at,
        }
        for item in recent_events
    ]
    return {
        "feedback_received": feedback_received,
        "feedback_pending": feedback_pending,
        "audit_events": _count(db, AuditEvent, *event_criteria),
        "audit_history": _count(db, AuditHistory) if platform_scope else 0,
        "recent_activity": recent_activity,
        "ready": True,
    }


def _reference_tenant_section(
    db: Session,
    *,
    organization_id: uuid.UUID | None,
    platform_scope: bool,
) -> dict[str, Any]:
    if not platform_scope:
        return {
            "reference_tenant_health": {},
            "reference_tenant_diagnostics": {"status": "not_applicable", "blocking_issues": [], "warnings": []},
            "product_baseline": {"product_baseline_ready": False, "pending_capabilities": [], "blocking_issues": []},
            "pending_capabilities": [],
            "ready": False,
        }
    readiness = build_reference_tenant_readiness(db)
    validation = validate_reference_tenant(db)
    status = build_reference_tenant_status(db)
    return {
        "reference_tenant_health": readiness,
        "reference_tenant_diagnostics": {
            "status": status,
            "blocking_issues": readiness.get("blocking_issues") or [],
            "warnings": readiness.get("warnings") or [],
        },
        "product_baseline": {
            "product_baseline_ready": bool(validation.get("product_baseline_ready")),
            "pending_capabilities": validation.get("pending_capabilities") or [],
            "blocking_issues": validation.get("blocking_issues") or [],
        },
        "pending_capabilities": validation.get("pending_capabilities") or [],
        "ready": bool(validation.get("product_baseline_ready")),
    }


def _operational_readiness(
    sections: dict[str, dict[str, Any]],
    *,
    platform_scope: bool,
) -> dict[str, Any]:
    domain_ready = {
        "platform": bool(sections["platform_runtime"]["readiness"]["ready"]),
        "documents": bool(sections["documents"].get("ready")),
        "knowledge": bool(sections["knowledge"].get("ready")),
        "enterprise_search": bool(sections["enterprise_search"].get("ready")),
        "assistant": bool(sections["assistant"].get("ready")),
        "runtime": bool(sections["runtime"].get("ready")),
        "feedback": bool(sections["feedback"].get("ready")),
        "reference_tenant": bool(sections["reference_tenant"].get("ready")),
    }
    unavailable = sorted(
        domain
        for domain, ready in domain_ready.items()
        if not ready and (platform_scope or domain != "reference_tenant")
    )
    blocking_issues = [
        _issue(
            "mandatory_operational_domain_unavailable",
            f"Mandatory operational domain is unavailable: {domain}.",
            domain=domain,
        )
        for domain in unavailable
    ]
    return {
        "ready": not unavailable,
        "domain_ready": domain_ready,
        "unavailable_domains": unavailable,
        "blocking_issues": blocking_issues,
    }


def build_platform_operations_runtime(
    db: Session,
    *,
    organization_id: uuid.UUID | None = None,
    platform_scope: bool = True,
) -> dict[str, Any]:
    platform_runtime = _platform_runtime_section(
        db, organization_id=organization_id, platform_scope=platform_scope
    )
    documents = _documents_section(db, organization_id=organization_id, platform_scope=platform_scope)
    knowledge = _knowledge_section(db, organization_id=organization_id, platform_scope=platform_scope)
    enterprise_search = _enterprise_search_section(
        db,
        knowledge,
        organization_id=organization_id,
        platform_scope=platform_scope,
    )
    assistant = _assistant_section(db, organization_id=organization_id, platform_scope=platform_scope)
    runtime = _runtime_section(db, organization_id=organization_id, platform_scope=platform_scope)
    feedback = _feedback_section(db, organization_id=organization_id, platform_scope=platform_scope)
    reference_tenant = _reference_tenant_section(
        db, organization_id=organization_id, platform_scope=platform_scope
    )
    sections = {
        "platform_runtime": platform_runtime,
        "documents": documents,
        "knowledge": knowledge,
        "enterprise_search": enterprise_search,
        "assistant": assistant,
        "runtime": runtime,
        "feedback": feedback,
        "reference_tenant": reference_tenant,
    }
    readiness = _operational_readiness(sections, platform_scope=platform_scope)
    warnings = []
    runtime_failures = int(runtime.get("runtime_failures") or 0)
    if runtime_failures > 0:
        warnings.append(
            _issue(
                "historical_runtime_failures_observed",
                f"{runtime_failures} terminal runtime execution failure(s) are available for operational review.",
                domain="runtime",
            )
        )
    return {
        "platform_operations_runtime_schema_version": PLATFORM_OPERATIONS_RUNTIME_SCHEMA_VERSION,
        "runtime_name": PLATFORM_OPERATIONS_RUNTIME_NAME,
        "runtime_status": "ready" if readiness["ready"] else "degraded",
        "platform_runtime": platform_runtime,
        "documents": documents,
        "knowledge": knowledge,
        "enterprise_search": enterprise_search,
        "assistant": assistant,
        "runtime": runtime,
        "feedback": feedback,
        "reference_tenant": reference_tenant,
        "operational_readiness": readiness,
        "warnings": warnings,
        "blocking_issues": readiness["blocking_issues"],
        "postgresql_source_of_truth": True,
        "llm_required": False,
        "embeddings_required": False,
        "qdrant_required": False,
    }
