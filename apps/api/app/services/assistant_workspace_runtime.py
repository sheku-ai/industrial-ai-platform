from __future__ import annotations

import uuid
from collections import defaultdict
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
    ConversationTurn,
)
from app.models.audit import AuditEvent
from app.models.runtime import RuntimePersistenceRecord
from app.repositories.knowledge_index import KnowledgeIndexRepository
from app.services.assistant_availability import (
    evaluate_assistant_availability,
    operational_knowledge_sources,
)
from app.services.platform_dashboard_runtime import build_platform_dashboard_runtime
from app.services.runtime_resolver import ASSISTED, RuntimeResolverService

ASSISTANT_WORKSPACE_RUNTIME_SCHEMA_VERSION = "1"
ASSISTANT_WORKSPACE_RUNTIME_NAME = "assistant_workspace_runtime"
RECENT_LIMIT = 10


def _count(db: Session, model: Any, *criteria: Any) -> int:
    primary_key = model.id if hasattr(model, "id") else next(iter(model.__table__.primary_key.columns))
    statement = select(func.count(primary_key))
    if criteria:
        statement = statement.where(*criteria)
    return int(db.scalar(statement) or 0)


def _count_by(db: Session, model: Any, column: Any) -> dict[str, int]:
    rows = db.execute(select(column, func.count()).select_from(model).group_by(column)).all()
    return {str(value or "unknown"): int(count or 0) for value, count in rows}


def _runtime_domain_count(db: Session, domain: str) -> int:
    return _count(db, RuntimePersistenceRecord, RuntimePersistenceRecord.runtime_domain == domain)


def _feedback_count_for(target_id: Any, feedback_events: list[AuditEvent]) -> int:
    target = str(target_id)
    return len(
        [
            event
            for event in feedback_events
            if event.resource_type == "feedback"
            and (
                str(event.resource_id or "") == target
                or str((event.metadata_json or {}).get("target_id") or "") == target
            )
        ]
    )


def _audit_count_for(target_id: Any, audit_events: list[AuditEvent]) -> int:
    target = str(target_id)
    return len([event for event in audit_events if str(event.resource_id or "") == target])


def _assistant_definitions(
    assistants: list[AssistantDefinition],
    knowledge_sources: list[KnowledgeSource],
    availability_by_assistant: dict[Any, dict[str, Any]],
    conversations_by_assistant: dict[Any, int],
    runs_by_assistant: dict[Any, int],
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for assistant in assistants:
        availability = availability_by_assistant.get(assistant.assistant_id, {})
        assigned_ids = set(availability.get("assigned_knowledge_source_ids") or [])
        assigned_sources = [
            {
                "source_id": source.id,
                "collection_id": source.collection_id,
                "source_type": source.source_type,
                "status": source.status,
                "configured": source.collection_id is not None,
            }
            for source in knowledge_sources
            if str(source.id) in assigned_ids
        ]
        items.append({
            "assistant_id": assistant.assistant_id,
            "assistant_key": assistant.assistant_key,
            "assistant_name": assistant.assistant_name,
            "assistant_status": assistant.assistant_status,
            "assistant_version": assistant.assistant_version,
            "assistant_type": assistant.assistant_type,
            "description": assistant.description,
            "default_search_mode": assistant.default_search_mode,
            "allowed_runtime_domains": assistant.allowed_runtime_domains or [],
            "guardrail_profile": assistant.guardrail_profile or {},
            "runtime_metadata": assistant.runtime_metadata or {},
            "prompt_profile": (assistant.runtime_metadata or {}).get("prompt_profile")
            or (assistant.runtime_metadata or {}).get("prompt")
            or {},
            "knowledge_sources": assigned_sources,
            "availability": availability,
            "readiness": {
                "status": availability.get("status", "not_configured"),
                "conversation_count": conversations_by_assistant.get(assistant.assistant_id, 0),
                "runtime_run_count": runs_by_assistant.get(assistant.assistant_id, 0),
                "knowledge_sources_ready": bool(availability.get("grounded_answers_available")),
            },
        })
    return items


def _assistant_explorer(assistant_definitions: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "assistant_count": len(assistant_definitions),
        "assistants": [
            {
                **assistant,
                "prompt_profile": assistant.get("prompt_profile") or {},
                "runtime_domains": assistant.get("allowed_runtime_domains") or [],
            }
            for assistant in assistant_definitions
        ],
    }


def _conversations(
    conversations: list[Conversation],
    turns_by_conversation: dict[Any, list[ConversationTurn]],
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for conversation in conversations:
        turns = turns_by_conversation.get(conversation.conversation_id, [])
        last_activity = max([turn.updated_at for turn in turns], default=conversation.updated_at)
        summary = conversation.conversation_title or (conversation.conversation_metadata or {}).get("summary")
        items.append(
            {
                "conversation_id": conversation.conversation_id,
                "assistant_id": conversation.assistant_id,
                "status": conversation.conversation_status,
                "title": summary,
                "turn_count": len(turns),
                "last_activity_at": last_activity,
                "readiness": {
                    "status": "ready" if conversation.conversation_status in {"active", "completed"} else "pending",
                    "has_turns": bool(turns),
                },
            }
        )
    return items


def _conversation_explorer(conversations: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "conversation_count": len(conversations),
        "active_count": len([item for item in conversations if item.get("status") == "active"]),
        "completed_count": len([item for item in conversations if item.get("status") == "completed"]),
        "conversations": conversations,
    }


def _conversation_turns(
    turns: list[ConversationTurn],
    feedback_events: list[AuditEvent],
    audit_events: list[AuditEvent],
) -> list[dict[str, Any]]:
    return [
        {
            "turn_id": turn.conversation_turn_id,
            "conversation_id": turn.conversation_id,
            "role": turn.turn_role,
            "status": turn.turn_status,
            "created_at": turn.created_at,
            "citation_count": len(turn.ordered_citations or []),
            "feedback_count": _feedback_count_for(turn.conversation_turn_id, feedback_events),
            "audit_event_count": _audit_count_for(turn.conversation_turn_id, audit_events),
        }
        for turn in turns
    ]


def _conversation_timeline(
    conversation_turns: list[dict[str, Any]],
    runtime_records: list[RuntimePersistenceRecord],
) -> dict[str, Any]:
    runtime_trace_available = bool(runtime_records)
    return {
        "turn_count": len(conversation_turns),
        "runtime_trace_available": runtime_trace_available,
        "turns": [
            {
                **turn,
                "timestamp": turn.get("created_at"),
                "execution_status": turn.get("status"),
                "runtime_trace_available": runtime_trace_available,
                "feedback_indicator": bool(turn.get("feedback_count")),
                "audit_indicator": bool(turn.get("audit_event_count")),
            }
            for turn in conversation_turns
        ],
    }


def _runtime_executions(
    db: Session,
    *,
    organization_id: uuid.UUID | None,
    platform_scope: bool,
) -> dict[str, Any]:
    def count(model: Any) -> int:
        criteria = () if platform_scope else (model.organization_id == organization_id,)
        return _count(db, model, *criteria)

    return {
        "assistant_sessions": count(AssistantSession),
        "assistant_runtime_executions": count(AssistantRuntimeRun),
        "retrieval_executions": count(AssistantRetrievalPlan),
        "retrieval_execution_readiness": count(AssistantRetrievalExecutionPlan),
        "enterprise_search_executions": count(AssistantSearchExecution),
        "context_builder_executions": count(AssistantContextPackage),
        "prompt_assembly_executions": count(AssistantPromptPackage),
        "llm_gateway_executions": count(AssistantLlmInvocationPlan),
        "llm_execution_records": count(AssistantLlmExecution),
        "citation_verification_executions": _count(db, AssistantCitationVerification) if platform_scope else 0,
        "response_executions": count(AssistantResponse),
        "chat_runtime_executions": _runtime_domain_count(db, "chat_runtime") if platform_scope else 0,
        "runtime_persistence_by_domain": _count_by(
            db,
            RuntimePersistenceRecord,
            RuntimePersistenceRecord.runtime_domain,
        ) if platform_scope else {},
    }


def _runtime_trace(runtime_records: list[RuntimePersistenceRecord]) -> dict[str, Any]:
    recent_records = sorted(runtime_records, key=lambda item: item.occurred_at, reverse=True)[:RECENT_LIMIT]
    return {
        "runtime_trace_available": bool(runtime_records),
        "record_count": len(runtime_records),
        "records_by_domain": {
            domain: len([record for record in runtime_records if record.runtime_domain == domain])
            for domain in sorted({record.runtime_domain for record in runtime_records})
        },
        "recent_records": [
            {
                "runtime_record_id": record.id,
                "runtime_domain": record.runtime_domain,
                "record_type": record.record_type,
                "record_key": record.record_key,
                "execution_status": record.execution_status,
                "persistence_status": record.persistence_status,
                "occurred_at": record.occurred_at,
            }
            for record in recent_records
        ],
    }


def _retrieval_and_citations(
    dashboard: dict[str, Any],
    knowledge_sources: list[KnowledgeSource],
    context_packages: list[AssistantContextPackage],
    citation_verifications: list[AssistantCitationVerification],
    responses: list[AssistantResponse],
) -> dict[str, Any]:
    readiness = dashboard.get("readiness_summary") if isinstance(dashboard.get("readiness_summary"), dict) else {}
    citation_count = sum(int(package.citation_count or 0) for package in context_packages)
    evidence_count = sum(int(package.chunk_count or 0) for package in context_packages)
    citation_verification_ready = any(item.verification_status == "completed" for item in citation_verifications)
    return {
        "enterprise_search_ready": bool(readiness.get("search_ready")),
        "knowledge_sources_ready": bool(knowledge_sources)
        and all(source.collection_id for source in knowledge_sources),
        "context_available": bool(context_packages),
        "citation_verification_ready": citation_verification_ready,
        "citation_count": citation_count,
        "evidence_count": evidence_count,
        "citation_diagnostics": {
            "context_packages": len(context_packages),
            "citation_verifications": len(citation_verifications),
            "responses_with_verified_citations": len(
                [response for response in responses if response.citation_verification_passed]
            ),
        },
    }


def _context_items(context_packages: list[AssistantContextPackage]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for package in context_packages:
        for context in package.ordered_context or []:
            if not isinstance(context, dict):
                continue
            items.append(
                {
                    "context_package_id": package.context_package_id,
                    "document_record_id": context.get("document_record_id"),
                    "document_version_id": context.get("document_version_id"),
                    "collection_id": context.get("collection_id"),
                    "chunk_id": context.get("chunk_id") or context.get("knowledge_chunk_id"),
                    "chunk_key": context.get("chunk_key"),
                    "citation_key": context.get("citation_key"),
                    "status": context.get("status") or package.package_status,
                }
            )
    return items


def _retrieval_explorer(
    knowledge_sources: list[KnowledgeSource],
    search_executions: list[AssistantSearchExecution],
    context_packages: list[AssistantContextPackage],
) -> dict[str, Any]:
    context_items = _context_items(context_packages)
    retrieved_documents = {
        str(item["document_record_id"]): item for item in context_items if item.get("document_record_id")
    }
    return {
        "knowledge_sources_used": [
            {
                "source_id": source.id,
                "collection_id": source.collection_id,
                "source_type": source.source_type,
                "source_status": source.status,
                "configured": source.collection_id is not None,
            }
            for source in knowledge_sources
        ],
        "retrieved_documents": list(retrieved_documents.values())[:RECENT_LIMIT],
        "retrieved_chunks": context_items[:RECENT_LIMIT],
        "context_packages": [
            {
                "context_package_id": package.context_package_id,
                "assistant_id": package.assistant_id,
                "status": package.package_status,
                "chunk_count": package.chunk_count,
                "citation_count": package.citation_count,
                "total_tokens_estimated": package.total_tokens_estimated,
                "context_size_bytes": package.context_size_bytes,
                "created_at": package.created_at,
            }
            for package in sorted(context_packages, key=lambda item: item.created_at, reverse=True)[:RECENT_LIMIT]
        ],
        "search_diagnostics": {
            "search_execution_count": len(search_executions),
            "completed_searches": len([item for item in search_executions if item.search_completed]),
            "result_count": sum(int(item.result_count or 0) for item in search_executions),
            "postgresql_fts_used": any(item.postgresql_fts_used for item in search_executions),
            "semantic_search_used": any(item.semantic_search_used for item in search_executions),
            "qdrant_used": any(item.qdrant_used for item in search_executions),
        },
    }


def _citation_explorer(
    citation_verifications: list[AssistantCitationVerification],
    responses: list[AssistantResponse],
    context_packages: list[AssistantContextPackage],
    retrieval_citations: dict[str, Any],
) -> dict[str, Any]:
    return {
        "verified_citations": sum(int(item.verified_citation_count or 0) for item in citation_verifications),
        "evidence_count": retrieval_citations.get("evidence_count", 0),
        "verification_status": "ready"
        if any(item.verification_status == "completed" for item in citation_verifications)
        else "pending",
        "citation_diagnostics": {
            "citation_verification_count": len(citation_verifications),
            "context_package_count": len(context_packages),
            "response_count": len(responses),
            "responses_with_verified_citations": len(
                [response for response in responses if response.citation_verification_passed]
            ),
            "missing_citation_count": sum(int(item.missing_citation_count or 0) for item in citation_verifications),
            "invalid_citation_count": sum(int(item.invalid_citation_count or 0) for item in citation_verifications),
        },
        "recent_verifications": [
            {
                "citation_verification_id": item.citation_verification_id,
                "verification_status": item.verification_status,
                "verified_citation_count": item.verified_citation_count,
                "missing_citation_count": item.missing_citation_count,
                "invalid_citation_count": item.invalid_citation_count,
                "created_at": item.created_at,
            }
            for item in sorted(citation_verifications, key=lambda row: row.created_at, reverse=True)[:RECENT_LIMIT]
        ],
    }


def _runtime_execution_experience(
    runtime_executions: dict[str, Any],
    context_packages: list[AssistantContextPackage],
    prompt_packages: list[AssistantPromptPackage],
    llm_gateway_plans: list[AssistantLlmInvocationPlan],
    llm_executions: list[AssistantLlmExecution],
    responses: list[AssistantResponse],
) -> dict[str, Any]:
    return {
        "prompt_assembly": {
            "execution_count": len(prompt_packages),
            "llm_ready_count": len([item for item in prompt_packages if item.llm_ready]),
            "llm_invoked_count": len([item for item in prompt_packages if item.llm_invoked]),
        },
        "context_builder": {
            "execution_count": len(context_packages),
            "context_available": bool(context_packages),
            "total_chunks": sum(int(item.chunk_count or 0) for item in context_packages),
        },
        "llm_gateway": {
            "execution_count": len(llm_gateway_plans),
            "provider_ready_count": len([item for item in llm_gateway_plans if item.provider_ready]),
            "execution_allowed_count": len([item for item in llm_gateway_plans if item.execution_allowed]),
            "llm_invoked_count": len([item for item in llm_gateway_plans if item.llm_invoked]),
        },
        "llm_executions": {
            "execution_count": len(llm_executions),
            "provider_called_count": len([item for item in llm_executions if item.provider_called]),
            "completed_count": len([item for item in llm_executions if item.execution_status == "completed"]),
            "total_tokens_estimated": sum(int(item.total_tokens_estimated or 0) for item in llm_executions),
        },
        "response_generation": {
            "response_count": len(responses),
            "completed_count": len([item for item in responses if item.response_status == "completed"]),
            "verified_response_count": len([item for item in responses if item.citation_verification_passed]),
        },
        "execution_metrics": runtime_executions,
    }


def _feedback_and_audit(audit_events: list[AuditEvent]) -> dict[str, Any]:
    feedback_events = [event for event in audit_events if event.resource_type == "feedback"]
    pending_feedback = [
        event for event in feedback_events if str((event.metadata_json or {}).get("status") or "").lower() == "pending"
    ]
    recent_feedback = sorted(feedback_events, key=lambda item: item.created_at, reverse=True)[:RECENT_LIMIT]
    recent_audit = sorted(audit_events, key=lambda item: item.created_at, reverse=True)[:RECENT_LIMIT]
    return {
        "feedback_count": len(feedback_events),
        "feedback_pending": len(pending_feedback),
        "feedback_recent": [
            {
                "feedback_id": item.id,
                "target_id": item.resource_id,
                "summary": item.summary,
                "created_at": item.created_at,
            }
            for item in recent_feedback
        ],
        "audit_event_count": len(audit_events),
        "audit_recent": [
            {
                "audit_event_id": item.id,
                "resource_type": item.resource_type,
                "resource_id": item.resource_id,
                "summary": item.summary,
                "created_at": item.created_at,
            }
            for item in recent_audit
        ],
        "runtime_trace_available": True,
    }


def _feedback_experience(feedback_audit: dict[str, Any]) -> dict[str, Any]:
    return {
        "conversation_feedback": feedback_audit.get("feedback_recent", []),
        "pending_feedback": feedback_audit.get("feedback_pending", 0),
        "recent_feedback": feedback_audit.get("feedback_recent", []),
        "feedback_count": feedback_audit.get("feedback_count", 0),
    }


def _audit_experience(feedback_audit: dict[str, Any], audit_events: list[AuditEvent]) -> dict[str, Any]:
    trace_event_types = {"conversation", "conversation_turn", "assistant_response", "assistant_runtime"}
    return {
        "audit_event_count": feedback_audit.get("audit_event_count", 0),
        "recent_audit_events": feedback_audit.get("audit_recent", []),
        "conversation_trace": [
            {
                "audit_event_id": event.id,
                "resource_type": event.resource_type,
                "resource_id": event.resource_id,
                "action": (event.metadata_json or {}).get("action") or event.action_id,
                "summary": event.summary,
                "created_at": event.created_at,
            }
            for event in audit_events
            if event.resource_type in trace_event_types
        ][:RECENT_LIMIT],
        "runtime_trace_available": bool(feedback_audit.get("runtime_trace_available")),
    }


def build_assistant_workspace_runtime(
    db: Session,
    *,
    organization_id: uuid.UUID | None = None,
    platform_scope: bool = False,
    source_runtimes: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    sources = source_runtimes or {}
    dashboard = sources.get("dashboard") or (
        build_platform_dashboard_runtime(
            db,
            organization_id=organization_id,
            platform_scope=True,
        )
        if platform_scope
        else {}
    )
    assistant_statement = select(AssistantDefinition)
    if platform_scope:
        assistant_statement = assistant_statement.where(
            AssistantDefinition.ownership_scope != "legacy_unscoped",
            AssistantDefinition.data_origin != "validation",
        )
    else:
        assistant_statement = assistant_statement.where(
            AssistantDefinition.data_origin != "validation",
            (AssistantDefinition.ownership_scope == "global")
            | (
                (AssistantDefinition.ownership_scope == "organization")
                & (AssistantDefinition.organization_id == organization_id)
            )
        )
    assistants = list(db.scalars(assistant_statement.order_by(AssistantDefinition.assistant_key.asc())).all())
    assistants = [
        item
        for item in assistants
        if (item.runtime_metadata or {}).get("scenario") != "local_product_acceptance"
        and not (item.runtime_metadata or {}).get("execution_key")
        and not (item.runtime_metadata or {}).get("smoke_runtime")
    ]
    assistant_ids = [item.assistant_id for item in assistants]

    def scoped_rows(model: Any) -> list[Any]:
        statement = select(model).where(model.assistant_id.in_(assistant_ids))
        if not platform_scope:
            statement = statement.where(model.organization_id == organization_id)
        return list(db.scalars(statement).all())

    runs = scoped_rows(AssistantRuntimeRun)
    context_packages = scoped_rows(AssistantContextPackage)
    assistant_run_ids = [item.assistant_run_id for item in runs]
    citation_verifications = list(
        db.scalars(
            select(AssistantCitationVerification).where(
                AssistantCitationVerification.assistant_runtime_id.in_(assistant_run_ids)
            )
        ).all()
    )
    responses = scoped_rows(AssistantResponse)
    search_executions = scoped_rows(AssistantSearchExecution)
    prompt_packages = scoped_rows(AssistantPromptPackage)
    llm_gateway_plans = scoped_rows(AssistantLlmInvocationPlan)
    llm_executions = scoped_rows(AssistantLlmExecution)
    conversation_statement = select(Conversation).where(
        Conversation.ownership_scope == "organization",
        Conversation.data_origin != "validation",
    )
    if not platform_scope:
        conversation_statement = conversation_statement.where(Conversation.organization_id == organization_id)
    conversations = list(db.scalars(conversation_statement.order_by(Conversation.updated_at.desc())).all())
    conversations = [
        item
        for item in conversations
        if (item.conversation_metadata or {}).get("scenario") != "local_product_acceptance"
        and not (item.conversation_metadata or {}).get("execution_key")
        and not (item.conversation_metadata or {}).get("smoke_runtime")
    ]
    conversation_ids = [item.conversation_id for item in conversations]
    turns = list(
        db.scalars(
            select(ConversationTurn)
            .where(ConversationTurn.conversation_id.in_(conversation_ids))
            .where(
                ConversationTurn.organization_id == organization_id
                if not platform_scope
                else ConversationTurn.organization_id.is_not(None)
            )
            .order_by(ConversationTurn.created_at.desc())
        ).all()
    )
    knowledge_source_statement = select(KnowledgeSource)
    if not platform_scope:
        knowledge_source_statement = knowledge_source_statement.where(
            KnowledgeSource.organization_id == organization_id
        )
    knowledge_sources = operational_knowledge_sources(
        list(db.scalars(knowledge_source_statement).all())
    )
    audit_statement = select(AuditEvent)
    if not platform_scope:
        audit_statement = audit_statement.where(AuditEvent.organization_id == organization_id)
    audit_events = list(db.scalars(audit_statement.order_by(AuditEvent.created_at.desc())).all())
    feedback_events = [event for event in audit_events if event.resource_type == "feedback"]
    runtime_records = list(db.scalars(select(RuntimePersistenceRecord)).all()) if platform_scope else []

    turns_by_conversation: dict[Any, list[ConversationTurn]] = defaultdict(list)
    for turn in turns:
        turns_by_conversation[turn.conversation_id].append(turn)
    conversations_by_assistant: dict[Any, int] = defaultdict(int)
    for conversation in conversations:
        if conversation.assistant_id:
            conversations_by_assistant[conversation.assistant_id] += 1
    runs_by_assistant: dict[Any, int] = defaultdict(int)
    for run in runs:
        runs_by_assistant[run.assistant_id] += 1

    readiness = dashboard.get("readiness_summary") if isinstance(dashboard.get("readiness_summary"), dict) else {}
    runtime_executions = _runtime_executions(
        db,
        organization_id=organization_id,
        platform_scope=platform_scope,
    )
    retrieval_citations = _retrieval_and_citations(
        dashboard,
        knowledge_sources,
        context_packages,
        citation_verifications,
        responses,
    )
    feedback_audit = _feedback_and_audit(audit_events)
    searchable_collection_ids = KnowledgeIndexRepository(db).indexed_collection_ids(
        organization_id=None if platform_scope else organization_id
    )
    search_ready = bool(searchable_collection_ids)
    runtime_resolution = RuntimeResolverService().resolve(
        db,
        organization_id=organization_id,
        requested_answer_mode=ASSISTED,
    )
    availability_by_assistant = {
        assistant.assistant_id: evaluate_assistant_availability(
            assistant,
            organization_sources=knowledge_sources,
            searchable_collection_ids=searchable_collection_ids,
            runtime_resolution=runtime_resolution,
            authorized=True,
        )
        for assistant in assistants
    }
    assistant_definitions = _assistant_definitions(
        assistants,
        knowledge_sources,
        availability_by_assistant,
        conversations_by_assistant,
        runs_by_assistant,
    )
    conversations_payload = _conversations(conversations, turns_by_conversation)
    conversation_turns_payload = _conversation_turns(turns, feedback_events, audit_events)
    runtime_trace = _runtime_trace(runtime_records)
    assistants_ready = bool(readiness.get("assistant_ready")) or bool(assistants)
    conversations_ready = bool(conversations) or bool(turns)
    citations_ready = bool(retrieval_citations["citation_verification_ready"]) or bool(
        retrieval_citations["citation_count"]
    )
    feedback_ready = bool(readiness.get("feedback_ready"))
    audit_ready = bool(readiness.get("audit_ready")) or bool(audit_events)
    runtime_status = "ready" if assistants_ready and search_ready and feedback_ready and audit_ready else "degraded"
    degraded_items = []
    for key, ready in {
        "assistants": assistants_ready,
        "conversations": conversations_ready,
        "search": search_ready,
        "citations": citations_ready,
        "feedback": feedback_ready,
        "audit": audit_ready,
    }.items():
        if not ready:
            degraded_items.append({"item_type": "domain", "item_id": key, "status": "pending"})
    return {
        "assistant_workspace_runtime_schema_version": ASSISTANT_WORKSPACE_RUNTIME_SCHEMA_VERSION,
        "runtime_name": ASSISTANT_WORKSPACE_RUNTIME_NAME,
        "runtime_status": runtime_status,
        "workspace_summary": {
            "runtime_status": runtime_status,
            "assistants_ready": assistants_ready,
            "conversations_ready": conversations_ready,
            "search_ready": search_ready,
            "citations_ready": citations_ready,
            "feedback_ready": feedback_ready,
            "audit_ready": audit_ready,
            "postgresql_source_of_truth": True,
            "ai_required": False,
            "llm_used": False,
            "qdrant_used": False,
        },
        "assistant_definitions": assistant_definitions,
        "conversations": conversations_payload,
        "conversation_turns": conversation_turns_payload,
        "runtime_executions": runtime_executions,
        "retrieval_and_citations": retrieval_citations,
        "feedback_and_audit": feedback_audit,
        "assistant_explorer": _assistant_explorer(assistant_definitions),
        "conversation_explorer": _conversation_explorer(conversations_payload),
        "conversation_timeline": _conversation_timeline(conversation_turns_payload, runtime_records),
        "retrieval_explorer": _retrieval_explorer(knowledge_sources, search_executions, context_packages),
        "citation_explorer": _citation_explorer(
            citation_verifications,
            responses,
            context_packages,
            retrieval_citations,
        ),
        "runtime_execution": _runtime_execution_experience(
            runtime_executions,
            context_packages,
            prompt_packages,
            llm_gateway_plans,
            llm_executions,
            responses,
        ),
        "feedback": _feedback_experience(feedback_audit),
        "audit": _audit_experience(feedback_audit, audit_events),
        "runtime_trace": runtime_trace,
        "diagnostics": {
            "blocking_issues": [],
            "warnings": [],
            "pending_capabilities": [],
            "degraded_items": degraded_items,
            "runtime_trace_available": runtime_trace["runtime_trace_available"],
        },
        "postgresql_source_of_truth": True,
        "ai_required": False,
        "llm_used": False,
        "qdrant_used": False,
    }
