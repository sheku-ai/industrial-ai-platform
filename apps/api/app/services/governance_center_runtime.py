from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.assistant_runtime import (
    AssistantCitationVerification,
    AssistantDefinition,
    AssistantResponse,
    AssistantRuntimeRun,
    Conversation,
    ConversationTurn,
)
from app.models.audit import AuditAction, AuditEvent, AuditHistory
from app.models.documents import (
    Artifact,
    Chunk,
    ClassificationRule,
    DocumentRecord,
    DocumentVersion,
    RetentionPolicy,
)
from app.models.knowledge_index import KnowledgeChunk, KnowledgeDocument
from app.models.runtime import RuntimeExecution, RuntimePersistenceRecord
from app.models.security import Permission, Policy, Role, RoleAssignment, RolePermission
from app.services.assistant_availability import has_validation_marker
from app.services.document_workspace_runtime import _is_validation_document

GOVERNANCE_CENTER_RUNTIME_SCHEMA_VERSION = "1"
GOVERNANCE_CENTER_RUNTIME_NAME = "governance_center_runtime"
RECENT_LIMIT = 10
SECRET_KEY_FRAGMENTS = ("secret", "password", "token", "api_key", "apikey", "credential")
READY_STATUSES = {"active", "ready", "prepared", "indexed", "completed", "succeeded", "published"}
RELEASE_AUDIT_RESOURCE_FRAGMENTS = (
    "portal_acceptance",
    "capacity_acceptance",
    "observability_health_acceptance",
    "product_acceptance",
    "release",
)


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


def _organization_criteria(model: Any, organization_id: UUID | None, platform_scope: bool) -> tuple[Any, ...]:
    if platform_scope:
        return ()
    if organization_id is None or not hasattr(model, "organization_id"):
        return (False,)
    return (model.organization_id == organization_id,)


def _operational_document_records(
    db: Session, organization_id: UUID | None, platform_scope: bool
) -> list[DocumentRecord]:
    records = list(
        db.scalars(
            select(DocumentRecord).where(
                *_organization_criteria(DocumentRecord, organization_id, platform_scope)
            )
        ).all()
    )
    return records if platform_scope else [record for record in records if not _is_validation_document(record)]


def _operational_assistants(
    db: Session, organization_id: UUID | None, platform_scope: bool
) -> list[AssistantDefinition]:
    statement = select(AssistantDefinition)
    if not platform_scope:
        statement = statement.where(
            AssistantDefinition.organization_id == organization_id,
            AssistantDefinition.ownership_scope == "organization",
            AssistantDefinition.data_origin.in_(("operational", "reference")),
        )
    rows = list(db.scalars(statement).all())
    return [row for row in rows if not has_validation_marker(row.runtime_metadata)]


def _operational_conversations(
    db: Session, organization_id: UUID | None, platform_scope: bool
) -> list[Conversation]:
    statement = select(Conversation)
    if not platform_scope:
        statement = statement.where(
            Conversation.organization_id == organization_id,
            Conversation.ownership_scope == "organization",
            Conversation.data_origin.in_(("operational", "reference")),
        )
    rows = list(db.scalars(statement).all())
    return [row for row in rows if not has_validation_marker(row.conversation_metadata)]


def _is_operational_audit_event(event: AuditEvent) -> bool:
    resource_type = str(event.resource_type or "").lower()
    return not has_validation_marker(event.metadata_json) and not any(
        fragment in resource_type for fragment in RELEASE_AUDIT_RESOURCE_FRAGMENTS
    )


def _is_operational_audit_history(item: AuditHistory) -> bool:
    entity_type = str(item.entity_type or "").lower()
    return (
        not has_validation_marker(item.before_state)
        and not has_validation_marker(item.after_state)
        and not any(fragment in entity_type for fragment in RELEASE_AUDIT_RESOURCE_FRAGMENTS)
    )


def _safe_metadata_summary(metadata: dict[str, Any] | None) -> dict[str, Any]:
    payload = metadata if isinstance(metadata, dict) else {}
    safe_keys = [
        key
        for key in sorted(payload.keys())
        if not any(fragment in str(key).lower() for fragment in SECRET_KEY_FRAGMENTS)
    ]
    return {
        "metadata_keys": safe_keys[:25],
        "metadata_key_count": len(safe_keys),
        "has_trace": any(key in payload for key in ("trace_id", "correlation_id", "runtime_id")),
    }


def _status_ready(status: str | None) -> bool:
    return str(status or "").lower() in READY_STATUSES


def _classification_key(record: DocumentRecord) -> str:
    classification = record.classification or {}
    for key in ("classification", "classification_code", "security_classification", "level", "code"):
        if classification.get(key):
            return str(classification[key])
    return "unclassified"


def _has_retention_policy(record: DocumentRecord) -> bool:
    metadata = record.metadata_json or {}
    classification = record.classification or {}
    return any(
        value
        for value in (
            metadata.get("retention_policy_id"),
            metadata.get("retention_policy"),
            metadata.get("retention"),
            classification.get("retention_policy_id"),
            classification.get("retention_policy"),
        )
    )


def _audit_governance(db: Session, organization_id: UUID | None, platform_scope: bool) -> dict[str, Any]:
    events = list(
        db.scalars(
            select(AuditEvent)
            .where(*_organization_criteria(AuditEvent, organization_id, platform_scope))
            .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
        ).all()
    )
    histories = list(
        db.scalars(
            select(AuditHistory).where(*_organization_criteria(AuditHistory, organization_id, platform_scope))
        ).all()
    )
    if not platform_scope:
        events = [event for event in events if _is_operational_audit_event(event)]
        histories = [item for item in histories if _is_operational_audit_history(item)]
    recent = events[:RECENT_LIMIT]
    return {
        "audit_event_count": len(events),
        "audit_actions_count": _count(db, AuditAction) if platform_scope else 0,
        "audit_history_count": len(histories),
        "audit_events_by_action": dict(Counter(str(event.action_id or "unknown") for event in events)),
        "audit_events_by_resource_type": dict(Counter(str(event.resource_type or "unknown") for event in events)),
        "recent_audit_events": [
            {
                "audit_event_id": event.id,
                "action_id": event.action_id,
                "resource_type": event.resource_type,
                "resource_id": event.resource_id,
                "summary": event.summary,
                "actor_id": event.actor_id,
                "created_at": event.created_at,
                "trace_id": (event.metadata_json or {}).get("trace_id"),
                "correlation_id": (event.metadata_json or {}).get("correlation_id"),
                "safe_metadata_summary": _safe_metadata_summary(event.metadata_json),
            }
            for event in recent
        ],
    }


def _feedback_governance(db: Session, organization_id: UUID | None, platform_scope: bool) -> dict[str, Any]:
    criteria = _organization_criteria(AuditEvent, organization_id, platform_scope)
    feedback_events = list(
        db.scalars(
            select(AuditEvent)
            .where(AuditEvent.resource_type == "feedback", *criteria)
            .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
        ).all()
    )
    if not platform_scope:
        feedback_events = [event for event in feedback_events if _is_operational_audit_event(event)]
    return {
        "feedback_count": len(feedback_events),
        "feedback_by_status": dict(
            Counter(str((event.metadata_json or {}).get("status") or "recorded") for event in feedback_events)
        ),
        "feedback_by_rating": dict(
            Counter(str((event.metadata_json or {}).get("rating") or "unrated") for event in feedback_events)
        ),
        "feedback_pending": len(
            [
                event
                for event in feedback_events
                if str((event.metadata_json or {}).get("status") or "").lower() == "pending"
            ]
        ),
        "feedback_reviewed": len(
            [
                event
                for event in feedback_events
                if str((event.metadata_json or {}).get("status") or "").lower() == "reviewed"
            ]
        ),
        "recent_feedback": [
            {
                "feedback_id": event.id,
                "resource_type": (event.metadata_json or {}).get("target_type") or event.resource_type,
                "resource_id": event.resource_id,
                "rating": (event.metadata_json or {}).get("rating"),
                "status": (event.metadata_json or {}).get("status") or "recorded",
                "summary": event.summary,
                "created_at": event.created_at,
                "readiness": {"status": "ready"},
            }
            for event in feedback_events[:RECENT_LIMIT]
        ],
    }


def _classification_governance(db: Session, organization_id: UUID | None, platform_scope: bool) -> dict[str, Any]:
    rule_criteria = _organization_criteria(ClassificationRule, organization_id, platform_scope)
    records = _operational_document_records(db, organization_id, platform_scope)
    docs_by_classification = Counter(_classification_key(record) for record in records)
    unclassified = docs_by_classification.get("unclassified", 0)
    rules_count = _count(db, ClassificationRule, *rule_criteria)
    return {
        "classification_rules_count": rules_count,
        "classification_rules_by_status": _count_by(db, ClassificationRule, ClassificationRule.status, *rule_criteria),
        "documents_by_classification": dict(docs_by_classification),
        "unclassified_documents": unclassified,
        "classification_readiness": {
            "status": "ready" if rules_count > 0 and unclassified == 0 else "degraded",
            "rules_configured": rules_count > 0,
            "all_documents_classified": unclassified == 0,
        },
        "classification_diagnostics": [] if rules_count > 0 else [{"code": "classification_rules_missing"}],
    }


def _retention_governance(db: Session, organization_id: UUID | None, platform_scope: bool) -> dict[str, Any]:
    policy_criteria = _organization_criteria(RetentionPolicy, organization_id, platform_scope)
    records = _operational_document_records(db, organization_id, platform_scope)
    with_policy = len([record for record in records if _has_retention_policy(record)])
    missing_policy = max(len(records) - with_policy, 0)
    policies_count = _count(db, RetentionPolicy, *policy_criteria)
    return {
        "retention_policies_count": policies_count,
        "retention_policies_by_status": _count_by(db, RetentionPolicy, RetentionPolicy.status, *policy_criteria),
        "documents_with_retention_policy": with_policy,
        "documents_missing_retention_policy": missing_policy,
        "retention_readiness": {
            "status": "ready" if policies_count > 0 and missing_policy == 0 else "degraded",
            "policies_configured": policies_count > 0,
            "all_documents_have_policy": missing_policy == 0,
        },
        "retention_diagnostics": [] if policies_count > 0 else [{"code": "retention_policies_missing"}],
    }


def _policy_governance(db: Session, organization_id: UUID | None, platform_scope: bool) -> dict[str, Any]:
    role_criteria = _organization_criteria(Role, organization_id, platform_scope)
    policy_criteria = _organization_criteria(Policy, organization_id, platform_scope)
    assignment_criteria = _organization_criteria(RoleAssignment, organization_id, platform_scope)
    roles = _count(db, Role, *role_criteria)
    if platform_scope:
        permissions = _count(db, Permission)
    elif organization_id is not None:
        permissions = int(db.scalar(
            select(func.count(func.distinct(RolePermission.permission_id)))
            .join(Role, Role.id == RolePermission.role_id)
            .where(Role.organization_id == organization_id)
        ) or 0)
    else:
        permissions = 0
    policies = _count(db, Policy, *policy_criteria)
    assignments = _count(db, RoleAssignment, *assignment_criteria)
    ready = roles > 0 and permissions > 0 and policies >= 0
    return {
        "roles_count": roles,
        "permissions_count": permissions,
        "policies_count": policies,
        "role_assignments_count": assignments,
        "policy_readiness": {
            "status": "ready" if ready else "degraded",
            "roles_configured": roles > 0,
            "permissions_configured": permissions > 0,
            "assignments_configured": assignments > 0,
        },
        "security_governance_diagnostics": [] if ready else [{"code": "security_governance_incomplete"}],
    }


def _runtime_evidence(db: Session, organization_id: UUID | None, platform_scope: bool) -> dict[str, Any]:
    base = select(RuntimePersistenceRecord)
    if not platform_scope:
        if organization_id is None:
            base = base.where(False)
        else:
            executions = list(
                db.scalars(
                    select(RuntimeExecution).where(RuntimeExecution.organization_id == organization_id)
                ).all()
            )
            execution_ids = [
                str(execution.id)
                for execution in executions
                if not has_validation_marker(execution.input_payload)
                and "acceptance" not in str(execution.execution_type or "").lower()
                and "release" not in str(execution.execution_type or "").lower()
                and "validation" not in str(execution.execution_type or "").lower()
                and "acceptance" not in str(execution.subject_type or "").lower()
                and "release" not in str(execution.subject_type or "").lower()
                and "validation" not in str(execution.subject_type or "").lower()
            ]
            base = base.where(RuntimePersistenceRecord.execution_id.in_(execution_ids))
    scoped = base.subquery()
    total_records = int(db.scalar(select(func.count()).select_from(scoped)) or 0)
    recent = list(
        db.scalars(
            base
            .order_by(RuntimePersistenceRecord.occurred_at.desc(), RuntimePersistenceRecord.id.desc())
            .limit(RECENT_LIMIT)
        ).all()
    )
    domain_rows = db.execute(select(scoped.c.runtime_domain, func.count()).group_by(scoped.c.runtime_domain)).all()
    status_rows = db.execute(select(scoped.c.persistence_status, func.count()).group_by(scoped.c.persistence_status)).all()
    evidence_domains = {str(value or "unknown"): int(count or 0) for value, count in domain_rows}
    expected_domains = {"storage", "processing", "knowledge_publication", "knowledge_index", "enterprise_search"}
    covered_domains = len(expected_domains.intersection(evidence_domains.keys()))
    return {
        "runtime_records_count": total_records,
        "runtime_records_by_domain": evidence_domains,
        "runtime_records_by_status": {str(value or "unknown"): int(count or 0) for value, count in status_rows},
        "recent_runtime_records": [
            {
                "runtime_record_id": record.id,
                "runtime_domain": record.runtime_domain,
                "record_type": record.record_type,
                "record_key": record.record_key,
                "persistence_status": record.persistence_status,
                "occurred_at": record.occurred_at,
                "safe_metadata_summary": _safe_metadata_summary(record.summary or record.validation or {}),
            }
            for record in recent
        ],
        "evidence_coverage": float(covered_domains / len(expected_domains)) if expected_domains else 0.0,
        "evidence_readiness": {"status": "ready" if total_records > 0 else "degraded"},
    }


def _document_lineage(db: Session, organization_id: UUID | None, platform_scope: bool) -> dict[str, Any]:
    records = _operational_document_records(db, organization_id, platform_scope)
    record_uuid_ids = [record.id for record in records]
    record_ids = [str(value) for value in record_uuid_ids]
    versions = list(db.scalars(select(DocumentVersion).where(DocumentVersion.document_record_id.in_(record_uuid_ids)).order_by(DocumentVersion.updated_at.desc())).all())
    version_ids = [version.id for version in versions]
    artifacts = list(db.scalars(select(Artifact).where(Artifact.document_version_id.in_(version_ids))).all())
    chunks = list(db.scalars(select(Chunk).where(Chunk.document_version_id.in_(version_ids))).all())
    knowledge_statement = select(KnowledgeDocument)
    if not platform_scope:
        knowledge_statement = knowledge_statement.where(KnowledgeDocument.document_record_id.in_(record_ids))
    knowledge_documents = list(db.scalars(knowledge_statement).all())
    knowledge_document_ids = [document.id for document in knowledge_documents]
    knowledge_chunks = list(
        db.scalars(select(KnowledgeChunk).where(KnowledgeChunk.knowledge_document_id.in_(knowledge_document_ids))).all()
    )
    artifacts_by_version: dict[str, list[Artifact]] = defaultdict(list)
    for artifact in artifacts:
        artifacts_by_version[str(artifact.document_version_id)].append(artifact)
    chunks_by_version = Counter(str(chunk.document_version_id) for chunk in chunks)
    knowledge_by_version: dict[str, list[KnowledgeDocument]] = defaultdict(list)
    for doc in knowledge_documents:
        if doc.document_version_id:
            knowledge_by_version[str(doc.document_version_id)].append(doc)
    knowledge_chunks_by_doc = Counter(str(chunk.knowledge_document_id) for chunk in knowledge_chunks)
    recent = []
    for version in versions[:RECENT_LIMIT]:
        version_artifacts = artifacts_by_version.get(str(version.id), [])
        artifact = version_artifacts[0] if version_artifacts else None
        knowledge_doc = (knowledge_by_version.get(str(version.id)) or [None])[0]
        knowledge_chunk_count = knowledge_chunks_by_doc.get(str(knowledge_doc.id), 0) if knowledge_doc else 0
        enterprise_ready = bool(knowledge_doc and _status_ready(knowledge_doc.status))
        recent.append(
            {
                "document_record_id": version.document_record_id,
                "document_version_id": version.id,
                "artifact_id": artifact.id if artifact else None,
                "chunk_count": chunks_by_version.get(str(version.id), 0),
                "knowledge_document_id": knowledge_doc.id if knowledge_doc else None,
                "knowledge_chunk_count": knowledge_chunk_count,
                "enterprise_search_ready": enterprise_ready,
                "assistant_ready": enterprise_ready,
                "traceability_status": "ready" if artifact and knowledge_doc else "pending",
            }
        )
    version_count = len(versions)
    knowledge_linked_versions = len({doc.document_version_id for doc in knowledge_documents if doc.document_version_id})
    return {
        "document_records_count": len(record_ids),
        "document_versions_count": version_count,
        "artifacts_count": len(artifacts),
        "chunks_count": len(chunks),
        "knowledge_documents_count": len(knowledge_documents),
        "document_to_knowledge_coverage": float(knowledge_linked_versions / version_count) if version_count else 0.0,
        "document_lineage_ready": bool(version_count and knowledge_linked_versions),
        "recent_document_lineage": recent,
    }


def _knowledge_lineage(db: Session, organization_id: UUID | None, platform_scope: bool) -> dict[str, Any]:
    docs_statement = select(KnowledgeDocument)
    if not platform_scope:
        record_ids = [
            str(value)
            for value in [record.id for record in _operational_document_records(db, organization_id, False)]
        ]
        docs_statement = docs_statement.where(KnowledgeDocument.document_record_id.in_(record_ids))
    docs = list(db.scalars(docs_statement).all())
    doc_ids = [document.id for document in docs]
    chunks = list(db.scalars(select(KnowledgeChunk).where(KnowledgeChunk.knowledge_document_id.in_(doc_ids))).all())
    ready_chunks = len([chunk for chunk in chunks if _status_ready(chunk.status)])
    return {
        "knowledge_documents_count": len(docs),
        "knowledge_chunks_count": len(chunks),
        "knowledge_documents_by_status": dict(Counter(str(doc.status or "unknown") for doc in docs)),
        "knowledge_chunks_by_status": dict(Counter(str(chunk.status or "unknown") for chunk in chunks)),
        "knowledge_to_search_ready": ready_chunks > 0,
        "knowledge_lineage_ready": bool(docs and chunks),
    }


def _assistant_traceability(db: Session, organization_id: UUID | None, platform_scope: bool) -> dict[str, Any]:
    audit_criteria = _organization_criteria(AuditEvent, organization_id, platform_scope)
    trace_events = list(
        db.scalars(
            select(AuditEvent).where(
                AuditEvent.resource_type.in_(
                    ("feedback", "assistant", "conversation", "conversation_turn", "assistant_response")
                ),
                *audit_criteria,
            )
        ).all()
    )
    if not platform_scope:
        trace_events = [event for event in trace_events if _is_operational_audit_event(event)]
    feedback_count = len([event for event in trace_events if event.resource_type == "feedback"])
    audit_linked = len([event for event in trace_events if event.resource_type != "feedback"])
    assistants = _operational_assistants(db, organization_id, platform_scope)
    conversations = _operational_conversations(db, organization_id, platform_scope)
    assistant_ids = [assistant.assistant_id for assistant in assistants]
    conversation_ids = [conversation.conversation_id for conversation in conversations]
    artifact_criteria = () if platform_scope else (
        AssistantRuntimeRun.organization_id == organization_id,
        AssistantRuntimeRun.data_origin.in_(("operational", "reference")),
        AssistantRuntimeRun.assistant_id.in_(assistant_ids),
    )
    return {
        "assistant_count": len(assistants),
        "conversation_count": len(conversations),
        "conversation_turn_count": _count(db, ConversationTurn, ConversationTurn.conversation_id.in_(conversation_ids)),
        "assistant_runtime_execution_count": _count(db, AssistantRuntimeRun, *artifact_criteria),
        "citation_verification_count": _count(db, AssistantCitationVerification, *_organization_criteria(AssistantCitationVerification, organization_id, platform_scope), AssistantCitationVerification.data_origin.in_(("operational", "reference")) if not platform_scope else True),
        "assistant_response_count": _count(db, AssistantResponse, *_organization_criteria(AssistantResponse, organization_id, platform_scope), AssistantResponse.data_origin.in_(("operational", "reference")) if not platform_scope else True),
        "feedback_linked_count": feedback_count,
        "audit_linked_count": audit_linked,
        "assistant_traceability_ready": audit_linked > 0 or feedback_count > 0,
    }


def _compliance_readiness(sections: dict[str, Any]) -> dict[str, Any]:
    readiness_by_domain = {
        "audit": sections["audit_governance"]["audit_event_count"] > 0,
        "feedback": sections["feedback_governance"]["feedback_count"] >= 0,
        "classification": sections["classification_governance"]["classification_readiness"]["status"] == "ready",
        "retention": sections["retention_governance"]["retention_readiness"]["status"] == "ready",
        "policy": sections["policy_governance"]["policy_readiness"]["status"] == "ready",
        "runtime_evidence": sections["runtime_evidence"]["runtime_records_count"] > 0,
        "document_lineage": bool(sections["document_lineage"]["document_lineage_ready"]),
        "knowledge_lineage": bool(sections["knowledge_lineage"]["knowledge_lineage_ready"]),
        "assistant_traceability": bool(sections["assistant_traceability"]["assistant_traceability_ready"]),
    }
    missing = [domain for domain, ready in readiness_by_domain.items() if not ready]
    score = (
        int((len(readiness_by_domain) - len(missing)) / len(readiness_by_domain) * 100) if readiness_by_domain else 0
    )
    return {
        "compliance_ready": not missing,
        "required_domains_ready": len(readiness_by_domain) - len(missing),
        "missing_domains": missing,
        "degraded_domains": missing,
        "governance_score": score,
        "readiness_by_domain": readiness_by_domain,
    }


def _diagnostics(compliance: dict[str, Any], sections: dict[str, Any]) -> dict[str, Any]:
    domain_evidence = {
        "audit": {
            "name": "Audit coverage",
            "component": "Audit trail",
            "impact": "Governance activity cannot be verified from persisted audit events.",
            "recommended_action": "Review audit event capture.",
        },
        "classification": {
            "name": "Document classification",
            "component": "Classification controls",
            "impact": "One or more operational documents may lack an applied classification.",
            "recommended_action": "Configure classification rules and classify outstanding documents.",
        },
        "retention": {
            "name": "Document retention",
            "component": "Retention controls",
            "impact": "One or more operational documents may not have a retention policy.",
            "recommended_action": "Configure retention policies and assign outstanding documents.",
        },
        "policy": {
            "name": "Access policy readiness",
            "component": "Roles and policies",
            "impact": "Persisted role, permission, policy or assignment evidence is incomplete.",
            "recommended_action": "Review organization roles, policies and active assignments.",
        },
        "runtime_evidence": {
            "name": "Runtime evidence coverage",
            "component": "Runtime persistence",
            "impact": "The operational runtime chain is not fully represented by persisted evidence.",
            "recommended_action": "Review runtime persistence coverage.",
        },
        "document_lineage": {
            "name": "Document lineage",
            "component": "Document lifecycle",
            "impact": "Document versions cannot be fully traced to published knowledge.",
            "recommended_action": "Review document processing and knowledge publication evidence.",
        },
        "knowledge_lineage": {
            "name": "Knowledge lineage",
            "component": "Knowledge index",
            "impact": "Published knowledge cannot be fully traced to searchable passages.",
            "recommended_action": "Review knowledge publication and indexing evidence.",
        },
        "assistant_traceability": {
            "name": "Assistant traceability",
            "component": "Assistant and conversation audit",
            "impact": "Assistant activity lacks linked audit or feedback evidence.",
            "recommended_action": "Review assistant audit and feedback capture.",
        },
        "feedback": {
            "name": "Feedback governance",
            "component": "Feedback evidence",
            "impact": "Impact not classified.",
            "recommended_action": "Review persisted feedback evidence.",
        },
    }
    degraded = []
    for domain in compliance["missing_domains"]:
        evidence = domain_evidence.get(domain, {})
        degraded.append(
            {
                "item_type": "domain",
                "item_id": domain,
                "domain": domain,
                "name": evidence.get("name") or domain.replace("_", " ").title(),
                "component": evidence.get("component") or domain,
                "impact": evidence.get("impact") or "Impact not classified.",
                "status": "needs_attention",
                "recommended_action": evidence.get("recommended_action"),
            }
        )
    recommendations = []
    if "classification" in compliance["missing_domains"]:
        recommendations.append(
            {"code": "configure_classification_rules", "label": "Configure classification rules and classify documents"}
        )
    if "retention" in compliance["missing_domains"]:
        recommendations.append(
            {
                "code": "configure_retention_policies",
                "label": "Configure retention policies and assign them to documents",
            }
        )
    if "runtime_evidence" in compliance["missing_domains"]:
        recommendations.append({"code": "review_runtime_evidence", "label": "Review runtime persistence coverage"})
    if "audit" in compliance["missing_domains"]:
        recommendations.append({"code": "review_audit_capture", "label": "Review audit event capture"})
    pending = []
    pending.extend(sections["classification_governance"].get("classification_diagnostics") or [])
    pending.extend(sections["retention_governance"].get("retention_diagnostics") or [])
    pending.extend(sections["policy_governance"].get("security_governance_diagnostics") or [])
    return {
        "blocking_issues": [],
        "warnings": [],
        "pending_capabilities": pending,
        "degraded_items": degraded,
        "governance_recommendations": recommendations,
    }


def _scope_classification(
    db: Session, organization_id: UUID | None, platform_scope: bool
) -> dict[str, Any]:
    if platform_scope or organization_id is None:
        return {"scope": "platform", "classification": "platform_evidence"}
    all_documents = list(
        db.scalars(select(DocumentRecord).where(DocumentRecord.organization_id == organization_id)).all()
    )
    included_documents = _operational_document_records(db, organization_id, False)
    all_assistants = list(
        db.scalars(select(AssistantDefinition).where(AssistantDefinition.organization_id == organization_id)).all()
    )
    included_assistants = _operational_assistants(db, organization_id, False)
    all_conversations = list(
        db.scalars(select(Conversation).where(Conversation.organization_id == organization_id)).all()
    )
    included_conversations = _operational_conversations(db, organization_id, False)
    return {
        "scope": "active_organization",
        "included_classifications": ["operational", "reference_operational"],
        "excluded_classifications": ["validation", "release", "legacy", "platform_global"],
        "documents": {
            "included": len(included_documents),
            "excluded_validation": len(all_documents) - len(included_documents),
        },
        "assistants": {
            "included": len(included_assistants),
            "excluded_non_operational": len(all_assistants) - len(included_assistants),
            "included_by_origin": dict(Counter(item.data_origin for item in included_assistants)),
        },
        "conversations": {
            "included": len(included_conversations),
            "excluded_non_operational": len(all_conversations) - len(included_conversations),
            "included_by_origin": dict(Counter(item.data_origin for item in included_conversations)),
        },
    }


def build_governance_center_runtime(
    db: Session,
    *,
    organization_id: UUID | None = None,
    platform_scope: bool = True,
) -> dict[str, Any]:
    sections = {
        "audit_governance": _audit_governance(db, organization_id, platform_scope),
        "feedback_governance": _feedback_governance(db, organization_id, platform_scope),
        "classification_governance": _classification_governance(db, organization_id, platform_scope),
        "retention_governance": _retention_governance(db, organization_id, platform_scope),
        "policy_governance": _policy_governance(db, organization_id, platform_scope),
        "runtime_evidence": _runtime_evidence(db, organization_id, platform_scope),
        "document_lineage": _document_lineage(db, organization_id, platform_scope),
        "knowledge_lineage": _knowledge_lineage(db, organization_id, platform_scope),
        "assistant_traceability": _assistant_traceability(db, organization_id, platform_scope),
    }
    compliance = _compliance_readiness(sections)
    diagnostics = _diagnostics(compliance, sections)
    scope_classification = _scope_classification(db, organization_id, platform_scope)
    runtime_status = "ready" if compliance["compliance_ready"] else "degraded"
    return {
        "governance_center_runtime_schema_version": GOVERNANCE_CENTER_RUNTIME_SCHEMA_VERSION,
        "runtime_name": GOVERNANCE_CENTER_RUNTIME_NAME,
        "runtime_status": runtime_status,
        "workspace_summary": {
            "metric_scope": "platform" if platform_scope else "selected_organization",
            "organization_id": None if platform_scope else organization_id,
            "included_data_origins": ["platform"] if platform_scope else ["operational", "reference_operational"],
            "scope_classification": scope_classification,
            "runtime_status": runtime_status,
            "governance_ready": compliance["compliance_ready"],
            "audit_ready": sections["audit_governance"]["audit_event_count"] > 0,
            "feedback_ready": sections["feedback_governance"]["feedback_count"] >= 0,
            "classification_ready": sections["classification_governance"]["classification_readiness"]["status"]
            == "ready",
            "retention_ready": sections["retention_governance"]["retention_readiness"]["status"] == "ready",
            "policy_ready": sections["policy_governance"]["policy_readiness"]["status"] == "ready",
            "traceability_ready": sections["assistant_traceability"]["assistant_traceability_ready"],
            "lineage_ready": sections["document_lineage"]["document_lineage_ready"]
            and sections["knowledge_lineage"]["knowledge_lineage_ready"],
            "evidence_ready": sections["runtime_evidence"]["runtime_records_count"] > 0,
            "compliance_ready": compliance["compliance_ready"],
            "postgresql_source_of_truth": True,
            "side_effects_performed": False,
            "llm_used": False,
            "qdrant_used": False,
            "external_calls_performed": False,
        },
        **sections,
        "compliance_readiness": compliance,
        "diagnostics": diagnostics,
        "postgresql_source_of_truth": True,
        "side_effects_performed": False,
        "llm_used": False,
        "qdrant_used": False,
        "external_calls_performed": False,
    }
