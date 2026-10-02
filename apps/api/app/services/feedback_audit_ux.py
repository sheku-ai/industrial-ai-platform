from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.assistant_runtime import (
    AssistantRuntimeRun,
    AssistantSearchExecution,
    Conversation,
    ConversationTurn,
)
from app.models.audit import AuditEvent, AuditHistory
from app.models.documents import Artifact, DocumentRecord, DocumentVersion
from app.models.processing import ProcessingRevision
from app.models.runtime import RuntimeExecution, RuntimePersistenceRecord


def _iso(value: Any) -> str | None:
    return value.isoformat() if hasattr(value, "isoformat") else None


def _uuid(value: Any) -> str | None:
    return str(value) if value is not None else None


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _item(
    *,
    item_id: Any,
    item_type: str,
    created_at: Any = None,
    status: str | None = None,
    summary: dict[str, Any] | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": str(item_id),
        "type": item_type,
        "created_at": _iso(created_at),
        "status": status,
        "summary": summary or {},
        "payload": payload or {},
    }


def _issue(code: str, message: str, *, component: str = "feedback_audit_ux") -> dict[str, Any]:
    return {"code": code, "message": message, "component": component}


def build_feedback_audit_readiness(db: Session) -> dict[str, Any]:
    audit_events = int(db.scalar(select(func.count(AuditEvent.id))) or 0)
    audit_history = int(db.scalar(select(func.count(AuditHistory.id))) or 0)
    runtime_records = int(db.scalar(select(func.count(RuntimePersistenceRecord.id))) or 0)
    conversations = int(db.scalar(select(func.count(Conversation.conversation_id))) or 0)
    assistant_runs = int(db.scalar(select(func.count(AssistantRuntimeRun.assistant_run_id))) or 0)
    search_executions = int(db.scalar(select(func.count(AssistantSearchExecution.search_execution_id))) or 0)
    lifecycle_versions = int(
        db.scalar(select(func.count(DocumentVersion.id)).where(DocumentVersion.object_store_key.is_not(None))) or 0
    )
    warnings: list[dict[str, Any]] = []
    if audit_events == 0:
        warnings.append(_issue("audit_events_empty", "No audit events are currently persisted."))
    if runtime_records == 0:
        warnings.append(_issue("runtime_records_empty", "No runtime persistence records are currently persisted."))
    return {
        "feedback_center_ready": True,
        "audit_explorer_ready": True,
        "runtime_explorer_ready": True,
        "conversation_history_ready": True,
        "assistant_history_ready": True,
        "search_history_ready": True,
        "document_lifecycle_history_ready": True,
        "postgresql_source_of_truth": True,
        "llm_used": False,
        "qdrant_used": False,
        "warnings": warnings,
        "blocking_issues": [],
        "counts": {
            "audit_events": audit_events,
            "audit_history": audit_history,
            "runtime_records": runtime_records,
            "conversations": conversations,
            "assistant_runs": assistant_runs,
            "search_executions": search_executions,
            "document_lifecycle_versions": lifecycle_versions,
        },
    }


def create_feedback(db: Session, payload: Any) -> dict[str, Any]:
    from app.services.correlation_context import current_correlation_id

    metadata = {
        "correlation_id": current_correlation_id(),
        "feedback_center": True,
        "target_type": payload.target_type,
        "target_id": payload.target_id,
        "rating": payload.rating,
        "comment": payload.comment,
        "comment_recorded": bool(payload.comment),
        "feedback_metadata": dict(payload.metadata or {}),
        "feedback_persisted": True,
        "postgresql_source_of_truth": True,
        "llm_used": False,
        "qdrant_used": False,
    }
    event = AuditEvent(
        organization_id=payload.organization_id,
        actor_type=payload.actor_type,
        actor_id=payload.actor_id,
        resource_type="feedback",
        resource_id=payload.target_id,
        summary=f"feedback received for {payload.target_type}",
        metadata_json=metadata,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return _feedback_event(event)


def list_feedback(
    db: Session,
    *,
    organization_id: uuid.UUID | None = None,
    target_type: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    statement = select(AuditEvent).where(AuditEvent.resource_type == "feedback")
    if organization_id is not None:
        statement = statement.where(
            or_(AuditEvent.organization_id == organization_id, AuditEvent.organization_id.is_(None))
        )
    if target_type:
        statement = statement.where(AuditEvent.metadata_json["target_type"].astext == target_type)
    statement = statement.order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc()).limit(limit)
    return [_feedback_event(item) for item in db.scalars(statement).all()]


def _feedback_event(event: AuditEvent) -> dict[str, Any]:
    metadata = _dict(event.metadata_json)
    return {
        "id": event.id,
        "organization_id": event.organization_id,
        "target_type": metadata.get("target_type"),
        "target_id": metadata.get("target_id"),
        "rating": metadata.get("rating"),
        "comment_recorded": bool(metadata.get("comment_recorded")),
        "actor_type": event.actor_type,
        "actor_id": event.actor_id,
        "metadata": metadata,
        "created_at": event.created_at,
        "updated_at": event.updated_at,
        "feedback_persisted": True,
        "postgresql_source_of_truth": True,
    }


def list_audit_events(
    db: Session,
    *,
    organization_id: uuid.UUID | None = None,
    resource_type: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    statement = select(AuditEvent)
    if organization_id is not None:
        statement = statement.where(
            or_(AuditEvent.organization_id == organization_id, AuditEvent.organization_id.is_(None))
        )
    if resource_type:
        statement = statement.where(AuditEvent.resource_type == resource_type)
    statement = statement.order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc()).limit(limit)
    items = [
        _item(
            item_id=event.id,
            item_type="audit_event",
            created_at=event.created_at,
            status=None,
            summary={"summary": event.summary, "resource_type": event.resource_type, "resource_id": event.resource_id},
            payload={
                "organization_id": _uuid(event.organization_id),
                "action_id": _uuid(event.action_id),
                "actor_type": event.actor_type,
                "actor_id": event.actor_id,
                "metadata": _dict(event.metadata_json),
            },
        )
        for event in db.scalars(statement).all()
    ]
    return _list_response(items)


def list_audit_history(
    db: Session,
    *,
    organization_id: uuid.UUID | None = None,
    entity_type: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    statement = select(AuditHistory)
    if organization_id is not None:
        statement = statement.where(
            or_(AuditHistory.organization_id == organization_id, AuditHistory.organization_id.is_(None))
        )
    if entity_type:
        statement = statement.where(AuditHistory.entity_type == entity_type)
    statement = statement.order_by(AuditHistory.created_at.desc(), AuditHistory.id.desc()).limit(limit)
    items = [
        _item(
            item_id=history.id,
            item_type="audit_history",
            created_at=history.created_at,
            status=history.action,
            summary={"entity_type": history.entity_type, "entity_id": history.entity_id, "action": history.action},
            payload={
                "organization_id": _uuid(history.organization_id),
                "before_state": _dict(history.before_state),
                "after_state": _dict(history.after_state),
                "actor_type": history.actor_type,
                "actor_id": history.actor_id,
            },
        )
        for history in db.scalars(statement).all()
    ]
    return _list_response(items)


def list_runtime_records(
    db: Session,
    *,
    runtime_domain: str | None = None,
    execution_id: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    statement = select(RuntimePersistenceRecord)
    if runtime_domain:
        statement = statement.where(RuntimePersistenceRecord.runtime_domain == runtime_domain)
    if execution_id:
        statement = statement.where(RuntimePersistenceRecord.execution_id == execution_id)
    statement = statement.order_by(
        RuntimePersistenceRecord.occurred_at.desc(), RuntimePersistenceRecord.id.desc()
    ).limit(limit)
    items = [
        _item(
            item_id=record.id,
            item_type="runtime_record",
            created_at=record.occurred_at,
            status=record.persistence_status,
            summary={
                "execution_id": record.execution_id,
                "runtime_domain": record.runtime_domain,
                "record_type": record.record_type,
                "record_key": record.record_key,
                "execution_status": record.execution_status,
            },
            payload={
                "artifact_id": record.artifact_id,
                "correlation_id": record.correlation_id,
                "summary": _dict(record.summary),
                "validation": _dict(record.validation),
                "metrics": _dict(record.metrics),
                "payload": _dict(record.payload),
            },
        )
        for record in db.scalars(statement).all()
    ]
    return _list_response(items)


def list_runtime_executions(
    db: Session,
    *,
    organization_id: uuid.UUID | None = None,
    execution_type: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    statement = select(RuntimeExecution)
    if organization_id is not None:
        statement = statement.where(RuntimeExecution.organization_id == organization_id)
    if execution_type:
        statement = statement.where(RuntimeExecution.execution_type == execution_type)
    statement = statement.order_by(RuntimeExecution.created_at.desc(), RuntimeExecution.id.desc()).limit(limit)
    items = [
        _item(
            item_id=execution.id,
            item_type="runtime_execution",
            created_at=execution.created_at,
            status=execution.status,
            summary={
                "organization_id": _uuid(execution.organization_id),
                "execution_type": execution.execution_type,
                "subject_type": execution.subject_type,
                "subject_id": _uuid(execution.subject_id),
                "correlation_id": execution.correlation_id,
            },
            payload={
                "requested_by": execution.requested_by,
                "metrics": _dict(execution.metrics),
                "error_code": execution.error_code,
                "error_message": execution.error_message,
            },
        )
        for execution in db.scalars(statement).all()
    ]
    return _list_response(items)


def list_conversations(db: Session, *, assistant_id: uuid.UUID | None = None, limit: int = 100) -> dict[str, Any]:
    statement = select(Conversation)
    if assistant_id is not None:
        statement = statement.where(Conversation.assistant_id == assistant_id)
    statement = statement.order_by(Conversation.created_at.desc(), Conversation.conversation_id.desc()).limit(limit)
    items = [_conversation_item(conversation) for conversation in db.scalars(statement).all()]
    return _list_response(items)


def get_conversation_history(db: Session, conversation_id: uuid.UUID) -> dict[str, Any] | None:
    conversation = db.get(Conversation, conversation_id)
    if conversation is None:
        return None
    turns = list(
        db.scalars(
            select(ConversationTurn)
            .where(ConversationTurn.conversation_id == conversation_id)
            .order_by(ConversationTurn.turn_index.asc(), ConversationTurn.created_at.asc())
        ).all()
    )
    payload = _conversation_payload(conversation)
    payload["turns"] = [_turn_payload(turn) for turn in turns]
    payload["turn_count"] = len(turns)
    return _item(
        item_id=conversation.conversation_id,
        item_type="conversation_history",
        created_at=conversation.created_at,
        status=conversation.conversation_status,
        summary={"turn_count": len(turns), "assistant_id": _uuid(conversation.assistant_id)},
        payload=payload,
    )


def list_assistant_history(db: Session, *, assistant_id: uuid.UUID | None = None, limit: int = 100) -> dict[str, Any]:
    statement = select(AssistantRuntimeRun)
    if assistant_id is not None:
        statement = statement.where(AssistantRuntimeRun.assistant_id == assistant_id)
    statement = statement.order_by(
        AssistantRuntimeRun.created_at.desc(), AssistantRuntimeRun.assistant_run_id.desc()
    ).limit(limit)
    items = [
        _item(
            item_id=run.assistant_run_id,
            item_type="assistant_runtime_run",
            created_at=run.created_at,
            status=run.run_status,
            summary={
                "assistant_id": _uuid(run.assistant_id),
                "assistant_session_id": _uuid(run.assistant_session_id),
                "selected_runtime_domain": run.selected_runtime_domain,
                "selected_search_mode": run.selected_search_mode,
            },
            payload={
                "requested_query": run.requested_query,
                "execution_state": run.execution_state,
                "runtime_metadata": _dict(run.runtime_metadata),
            },
        )
        for run in db.scalars(statement).all()
    ]
    return _list_response(items)


def list_search_history(db: Session, *, assistant_id: uuid.UUID | None = None, limit: int = 100) -> dict[str, Any]:
    statement = select(AssistantSearchExecution)
    if assistant_id is not None:
        statement = statement.where(AssistantSearchExecution.assistant_id == assistant_id)
    statement = statement.order_by(
        AssistantSearchExecution.created_at.desc(), AssistantSearchExecution.search_execution_id.desc()
    ).limit(limit)
    items = [
        _item(
            item_id=search.search_execution_id,
            item_type="assistant_search_execution",
            created_at=search.created_at,
            status="completed" if search.search_completed else "prepared",
            summary={
                "assistant_id": _uuid(search.assistant_id),
                "search_mode": search.search_mode,
                "runtime_domain": search.runtime_domain,
                "result_count": search.result_count,
                "postgresql_fts_used": bool(search.postgresql_fts_used),
            },
            payload={
                "search_query": search.search_query,
                "search_duration_ms": search.search_duration_ms,
                "execution_metadata": _dict(search.execution_metadata),
                "semantic_search_used": bool(search.semantic_search_used),
                "qdrant_used": bool(search.qdrant_used),
                "llm_used": bool(search.llm_used),
            },
        )
        for search in db.scalars(statement).all()
    ]
    return _list_response(items)


def list_document_lifecycle_history(
    db: Session,
    *,
    organization_id: uuid.UUID | None = None,
    document_record_id: uuid.UUID | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    statement = select(DocumentVersion, DocumentRecord).join(
        DocumentRecord, DocumentRecord.id == DocumentVersion.document_record_id
    )
    if organization_id is not None:
        statement = statement.where(DocumentVersion.organization_id == organization_id)
    if document_record_id is not None:
        statement = statement.where(DocumentVersion.document_record_id == document_record_id)
    statement = statement.order_by(DocumentVersion.created_at.desc(), DocumentVersion.id.desc()).limit(limit)
    items: list[dict[str, Any]] = []
    for version, record in db.execute(statement).all():
        snapshot = _dict(version.source_snapshot)
        if not snapshot.get("document_lifecycle_orchestrator") and not version.object_store_key:
            continue
        artifact_count = int(
            db.scalar(select(func.count(Artifact.id)).where(Artifact.document_version_id == version.id)) or 0
        )
        revision_count = int(
            db.scalar(
                select(func.count(ProcessingRevision.id)).where(ProcessingRevision.document_version_id == version.id)
            )
            or 0
        )
        items.append(
            _item(
                item_id=version.id,
                item_type="document_lifecycle_history",
                created_at=version.created_at,
                status=version.status,
                summary={
                    "organization_id": _uuid(version.organization_id),
                    "document_record_id": _uuid(record.id),
                    "title": record.title,
                    "version_number": version.version_number,
                    "storage_verified": bool(snapshot.get("storage_verified")),
                    "artifact_count": artifact_count,
                    "processing_revision_count": revision_count,
                },
                payload={
                    "document": {
                        "document_record_id": _uuid(record.id),
                        "collection_id": _uuid(record.collection_id),
                        "document_type_id": _uuid(record.document_type_id),
                        "status": record.status,
                    },
                    "version": {
                        "document_version_id": _uuid(version.id),
                        "content_type": version.content_type,
                        "file_name": version.file_name,
                        "size_bytes": version.size_bytes,
                        "checksum_sha256": version.checksum_sha256,
                        "object_store_provider": version.object_store_provider,
                        "object_store_bucket": version.object_store_bucket,
                        "object_store_key": version.object_store_key,
                    },
                    "source_snapshot": snapshot,
                },
            )
        )
    return _list_response(items)


def _conversation_item(conversation: Conversation) -> dict[str, Any]:
    return _item(
        item_id=conversation.conversation_id,
        item_type="conversation",
        created_at=conversation.created_at,
        status=conversation.conversation_status,
        summary={
            "assistant_id": _uuid(conversation.assistant_id),
            "assistant_session_id": _uuid(conversation.assistant_session_id),
            "conversation_title": conversation.conversation_title,
            "conversation_reference": conversation.conversation_reference,
        },
        payload=_conversation_payload(conversation),
    )


def _conversation_payload(conversation: Conversation) -> dict[str, Any]:
    return {
        "conversation_id": _uuid(conversation.conversation_id),
        "assistant_id": _uuid(conversation.assistant_id),
        "assistant_session_id": _uuid(conversation.assistant_session_id),
        "conversation_status": conversation.conversation_status,
        "conversation_title": conversation.conversation_title,
        "conversation_reference": conversation.conversation_reference,
        "requested_by": conversation.requested_by,
        "runtime_context": _dict(conversation.runtime_context),
        "conversation_metadata": _dict(conversation.conversation_metadata),
    }


def _turn_payload(turn: ConversationTurn) -> dict[str, Any]:
    return {
        "conversation_turn_id": _uuid(turn.conversation_turn_id),
        "conversation_id": _uuid(turn.conversation_id),
        "assistant_id": _uuid(turn.assistant_id),
        "assistant_session_id": _uuid(turn.assistant_session_id),
        "assistant_run_id": _uuid(turn.assistant_run_id),
        "assistant_response_id": _uuid(turn.assistant_response_id),
        "turn_index": turn.turn_index,
        "turn_role": turn.turn_role,
        "turn_status": turn.turn_status,
        "input_text": turn.input_text,
        "output_text": turn.output_text,
        "response_format": turn.response_format,
        "citation_summary": _dict(turn.citation_summary),
        "ordered_citations": _list(turn.ordered_citations),
        "turn_metadata": _dict(turn.turn_metadata),
        "created_at": _iso(turn.created_at),
    }


def _list_response(items: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "items": items,
        "count": len(items),
        "postgresql_source_of_truth": True,
        "llm_used": False,
        "qdrant_used": False,
    }
