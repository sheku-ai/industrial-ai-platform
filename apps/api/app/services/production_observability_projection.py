from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import String, cast, func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.assistant_runtime import AssistantRuntimeRun, AssistantSearchExecution, Conversation
from app.models.documents import Chunk, DocumentVersion
from app.models.knowledge_index import KnowledgeChunk, KnowledgeDocument
from app.models.processing import ProcessingRevision
from app.models.runtime import RuntimeExecution, RuntimeExecutionAttempt
from app.models.runtime_worker import RuntimeWorker
from app.services.dependency_health import evaluate_dependency_health
from app.services.operational_observability_runtime import build_lease_inventory, build_scheduler_inventory


def _count(db: Session, model: Any, *criteria: Any) -> int:
    primary_key = next(iter(model.__table__.primary_key.columns))
    statement = select(func.count(primary_key))
    if criteria:
        statement = statement.where(*criteria)
    return int(db.scalar(statement) or 0)


def _organization_criterion(model: Any, organization_id: uuid.UUID | None) -> tuple[Any, ...]:
    if organization_id is None or not hasattr(model, "organization_id"):
        return ()
    return (model.organization_id == organization_id,)


def build_production_observability_projection(
    db: Session,
    *,
    organization_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    now = datetime.now(UTC)
    settings = get_settings()
    dependencies = evaluate_dependency_health(db, settings)
    dependency_map = {item.name: item.model_dump(mode="json") for item in dependencies.dependencies}

    execution_scope = _organization_criterion(RuntimeExecution, organization_id)
    total_executions = _count(db, RuntimeExecution, *execution_scope)
    backlog = _count(
        db,
        RuntimeExecution,
        *execution_scope,
        RuntimeExecution.status.in_(("pending", "scheduled", "leased", "running")),
    )
    errors = _count(
        db,
        RuntimeExecution,
        *execution_scope,
        RuntimeExecution.status.in_(("failed", "expired", "dead_lettered")),
    )
    latency_statement = select(
        func.avg(func.extract("epoch", RuntimeExecution.finished_at - RuntimeExecution.started_at) * 1000)
    ).where(RuntimeExecution.started_at.is_not(None), RuntimeExecution.finished_at.is_not(None))
    if organization_id is not None:
        latency_statement = latency_statement.where(RuntimeExecution.organization_id == organization_id)
    average_latency_ms = float(db.scalar(latency_statement) or 0.0)

    document_scope = _organization_criterion(DocumentVersion, organization_id)
    chunk_scope = _organization_criterion(Chunk, organization_id)
    processing_scope = _organization_criterion(ProcessingRevision, organization_id)
    assistant_scope = _organization_criterion(AssistantRuntimeRun, organization_id)
    search_scope = _organization_criterion(AssistantSearchExecution, organization_id)
    conversation_scope = _organization_criterion(Conversation, organization_id)

    knowledge_document_statement = select(func.count(KnowledgeDocument.id))
    knowledge_chunk_statement = select(func.count(KnowledgeChunk.id))
    if organization_id is not None:
        knowledge_document_statement = knowledge_document_statement.join(
            DocumentVersion,
            KnowledgeDocument.document_version_id == cast(DocumentVersion.id, String),
        ).where(DocumentVersion.organization_id == organization_id)
        knowledge_chunk_statement = (
            knowledge_chunk_statement.join(
                KnowledgeDocument,
                KnowledgeChunk.knowledge_document_id == KnowledgeDocument.id,
            )
            .join(DocumentVersion, KnowledgeDocument.document_version_id == cast(DocumentVersion.id, String))
            .where(DocumentVersion.organization_id == organization_id)
        )

    scheduler = build_scheduler_inventory(db)
    leases = build_lease_inventory(db)
    metrics = {
        "api": {"available": True, "observed_at": now.isoformat(), "source": "active_http_request"},
        "postgresql": dependency_map.get("postgresql", {}),
        "redis": dependency_map.get("redis_secret_store", {}),
        "object_storage": dependency_map.get("object_storage", {}),
        "scheduler": scheduler,
        "workers": {
            "registered": _count(db, RuntimeWorker),
            "ready": _count(db, RuntimeWorker, RuntimeWorker.observed_state == "ready"),
        },
        "documents": _count(db, DocumentVersion, *document_scope),
        "processing": _count(db, ProcessingRevision, *processing_scope),
        "chunks": _count(db, Chunk, *chunk_scope),
        "knowledge_documents": int(db.scalar(knowledge_document_statement) or 0),
        "knowledge_chunks": int(db.scalar(knowledge_chunk_statement) or 0),
        "publication": int(db.scalar(knowledge_document_statement) or 0),
        "search_executions": _count(db, AssistantSearchExecution, *search_scope),
        "assistant_executions": _count(db, AssistantRuntimeRun, *assistant_scope),
        "conversations": _count(db, Conversation, *conversation_scope),
        "leases": leases,
        "backlog": backlog,
        "retries": _count(db, RuntimeExecutionAttempt, RuntimeExecutionAttempt.attempt_number > 1),
        "errors": errors,
        "executions": total_executions,
        "average_latency_ms": round(average_latency_ms, 3),
    }
    warnings: list[dict[str, Any]] = []
    alerts: list[dict[str, Any]] = []
    if backlog:
        warnings.append({"code": "runtime_backlog_present", "count": backlog})
    if errors:
        alerts.append({"code": "runtime_failures_present", "count": errors, "severity": "error"})
    if leases.get("expired_leases"):
        alerts.append({"code": "expired_leases_present", "count": leases["expired_leases"], "severity": "warning"})
    health = {
        "status": "degraded" if alerts else "healthy",
        "dependencies": dependency_map,
        "observed_at": now.isoformat(),
    }
    return {
        "dashboard_runtime": metrics,
        "health_runtime": health,
        "warning_runtime": {"count": len(warnings), "items": warnings},
        "alert_runtime": {"count": len(alerts), "items": alerts},
        "postgresql_source_of_truth": True,
        "simulated_metrics": False,
    }
