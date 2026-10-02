from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.assistant_runtime import (
    AssistantRetrievalPlan,
    AssistantRuntimeRun,
    AssistantSearchExecution,
    AssistantSession,
    Conversation,
    ConversationTurn,
)
from app.models.audit import AuditEvent
from app.models.operational_observability import OperationalExecution
from app.models.production_acceptance import ProductionAcceptanceRun
from app.models.recovery import BackupExecution, RestoreExecution
from app.models.runtime import RuntimeExecution, RuntimePersistenceRecord


def _event(domain: str, record_type: str, identifier: Any, occurred_at: datetime, **details: Any) -> dict[str, Any]:
    return {
        "domain": domain,
        "record_type": record_type,
        "record_id": str(identifier),
        "occurred_at": occurred_at.isoformat(),
        "details": details,
    }


def build_correlation_trace(
    db: Session,
    correlation_id: str,
    *,
    scope: str,
    organization_id: uuid.UUID | None,
) -> dict[str, Any]:
    timeline: list[dict[str, Any]] = []

    runtime_statement = select(RuntimeExecution).where(RuntimeExecution.correlation_id == correlation_id)
    if scope == "organization":
        runtime_statement = runtime_statement.where(RuntimeExecution.organization_id == organization_id)
    for item in db.scalars(runtime_statement).all():
        timeline.append(
            _event(
                "runtime",
                "execution",
                item.id,
                item.requested_at,
                status=item.status,
                execution_type=item.execution_type,
                organization_id=str(item.organization_id),
            )
        )

    persistence_statement = select(RuntimePersistenceRecord).where(
        RuntimePersistenceRecord.correlation_id == correlation_id
    )
    if scope == "organization":
        organization_text = str(organization_id)
        persistence_statement = persistence_statement.where(
            or_(
                RuntimePersistenceRecord.payload["organization_id"].astext == organization_text,
                RuntimePersistenceRecord.summary["organization_id"].astext == organization_text,
            )
        )
    for item in db.scalars(persistence_statement).all():
        timeline.append(
            _event(
                item.runtime_domain,
                item.record_type,
                item.id,
                item.occurred_at,
                status=item.persistence_status,
                execution_id=item.execution_id,
                record_key=item.record_key,
            )
        )

    scoped_models = (
        (ProductionAcceptanceRun, ProductionAcceptanceRun.id, "production_acceptance", "status", "requested_at"),
        (OperationalExecution, OperationalExecution.id, "operations", "status", "requested_at"),
        (BackupExecution, BackupExecution.id, "backup", "status", "requested_at"),
        (RestoreExecution, RestoreExecution.id, "restore", "status", "requested_at"),
    )
    for model, identifier, domain, status_field, date_field in scoped_models:
        statement = select(model).where(model.correlation_id == correlation_id)
        if scope == "organization":
            statement = statement.where(model.organization_id == organization_id)
        for item in db.scalars(statement).all():
            timeline.append(
                _event(
                    domain,
                    model.__tablename__,
                    getattr(item, identifier.key),
                    getattr(item, date_field),
                    status=getattr(item, status_field),
                    organization_id=str(item.organization_id) if item.organization_id else None,
                )
            )

    assistant_models = (
        (AssistantSession, AssistantSession.assistant_session_id, AssistantSession.runtime_context, "session"),
        (AssistantRuntimeRun, AssistantRuntimeRun.assistant_run_id, AssistantRuntimeRun.runtime_metadata, "run"),
        (
            AssistantRetrievalPlan,
            AssistantRetrievalPlan.retrieval_plan_id,
            AssistantRetrievalPlan.runtime_metadata,
            "retrieval_plan",
        ),
        (
            AssistantSearchExecution,
            AssistantSearchExecution.search_execution_id,
            AssistantSearchExecution.execution_metadata,
            "search_execution",
        ),
    )
    for model, identifier, metadata, record_type in assistant_models:
        statement = select(model).where(metadata["correlation_id"].astext == correlation_id)
        if scope == "organization":
            statement = statement.where(model.organization_id == organization_id)
        else:
            statement = statement.where(model.ownership_scope != "legacy_unscoped")
        for item in db.scalars(statement).all():
            timeline.append(
                _event(
                    "assistant",
                    record_type,
                    getattr(item, identifier.key),
                    item.created_at,
                    ownership_scope=item.ownership_scope,
                    organization_id=str(item.organization_id) if item.organization_id else None,
                )
            )

    conversation_statement = select(Conversation).where(
        or_(
            Conversation.runtime_context["correlation_id"].astext == correlation_id,
            Conversation.conversation_metadata["correlation_id"].astext == correlation_id,
        )
    )
    turn_statement = select(ConversationTurn).where(
        ConversationTurn.turn_metadata["correlation_id"].astext == correlation_id
    )
    if scope == "organization":
        conversation_statement = conversation_statement.where(Conversation.organization_id == organization_id)
        turn_statement = turn_statement.where(ConversationTurn.organization_id == organization_id)
    for item in db.scalars(conversation_statement).all():
        timeline.append(
            _event(
                "conversation",
                "conversation",
                item.conversation_id,
                item.created_at,
                status=item.conversation_status,
            )
        )
    for item in db.scalars(turn_statement).all():
        timeline.append(
            _event("conversation", "turn", item.conversation_turn_id, item.created_at, status=item.turn_status)
        )

    audit_statement = select(AuditEvent).where(AuditEvent.metadata_json["correlation_id"].astext == correlation_id)
    if scope == "organization":
        audit_statement = audit_statement.where(AuditEvent.organization_id == organization_id)
    for item in db.scalars(audit_statement).all():
        timeline.append(_event("audit", "audit_event", item.id, item.created_at, resource_type=item.resource_type))

    timeline.sort(key=lambda item: (item["occurred_at"], item["domain"], item["record_id"]))
    return {
        "correlation_id": correlation_id,
        "scope": scope,
        "organization_id": str(organization_id) if organization_id else None,
        "found": bool(timeline),
        "record_count": len(timeline),
        "domains": sorted({item["domain"] for item in timeline}),
        "timeline": timeline,
        "postgresql_source_of_truth": True,
    }
