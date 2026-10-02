from __future__ import annotations

from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.platform_metadata import build_platform_info
from app.models.ai import Guardrail, KnowledgeSource, Prompt, Provider, RuntimeProfile, Workflow
from app.models.ai import Model as AiModel
from app.models.assistant_runtime import (
    AssistantDefinition,
    AssistantLlmExecution,
    AssistantResponse,
    AssistantRuntimeRun,
    AssistantSearchExecution,
    AssistantSession,
    Conversation,
    ConversationTurn,
)
from app.models.audit import AuditAction, AuditEvent, AuditHistory
from app.models.core import Organization, OrganizationNode, OrganizationRelationship
from app.models.documents import (
    Artifact,
    Chunk,
    ClassificationRule,
    Collection,
    DocumentRecord,
    DocumentType,
    DocumentVersion,
    IngestionJob,
    MetadataTemplate,
    RetentionPolicy,
)
from app.models.knowledge_index import KnowledgeChunk, KnowledgeDocument
from app.models.runtime import RuntimeExecution, RuntimePersistenceRecord
from app.models.runtime_configuration import RuntimeConfiguration, RuntimeConfigurationRevision
from app.models.runtime_worker import RuntimeWorker
from app.models.security import RolePermission
from app.services.data_classification import classify_persisted_metadata, is_visible_product_data
from app.services.document_management_configuration import build_document_configuration_contract
from app.services.knowledge_collection_management import list_knowledge_collections
from app.services.reference_tenant import (
    build_reference_tenant_readiness,
    build_reference_tenant_status,
    validate_reference_tenant,
)
from app.services.security_management import (
    list_permissions,
    list_policies,
    list_role_assignments,
    list_roles,
)

PLATFORM_ADMINISTRATION_RUNTIME_SCHEMA_VERSION = "1"
PLATFORM_ADMINISTRATION_RUNTIME_NAME = "platform_administration_runtime"

INSTALLED_CAPABILITIES = (
    "organization_runtime",
    "security_management",
    "document_management",
    "document_lifecycle_orchestrator",
    "storage_execution",
    "processing_runtime",
    "chunk_runtime",
    "knowledge_publication",
    "postgresql_knowledge_index",
    "enterprise_search",
    "assistant_runtime",
    "conversation_runtime",
    "chat_runtime",
    "feedback_audit",
    "reference_tenant",
    "platform_administration",
)


def _count(db: Session, model: Any, *criteria: Any) -> int:
    primary_key = model.id if hasattr(model, "id") else next(iter(model.__table__.primary_key.columns))
    statement = select(func.count(primary_key))
    if criteria:
        statement = statement.where(*criteria)
    return int(db.scalar(statement) or 0)


def _count_by_status(db: Session, model: Any, status_column: Any, *criteria: Any) -> dict[str, int]:
    statement = select(status_column, func.count()).select_from(model)
    if criteria:
        statement = statement.where(*criteria)
    rows = db.execute(statement.group_by(status_column)).all()
    return {str(status or "unknown"): int(count or 0) for status, count in rows}


def _to_dict(item: Any, fields: tuple[str, ...]) -> dict[str, Any]:
    return {field: getattr(item, field) for field in fields}


def _rows(
    db: Session,
    model: Any,
    fields: tuple[str, ...],
    order_by: Any | None = None,
    *criteria: Any,
) -> list[dict[str, Any]]:
    statement = select(model)
    if criteria:
        statement = statement.where(*criteria)
    if order_by is not None:
        statement = statement.order_by(order_by)
    return [_to_dict(item, fields) for item in db.scalars(statement).all()]


def _validation_organization_ids(db: Session) -> set[Any]:
    organizations = db.scalars(select(Organization)).all()
    return {item.id for item in organizations if classify_persisted_metadata(item.config or {}) == "validation"}


def _organization_data_classification(config: dict[str, Any] | None) -> str:
    return classify_persisted_metadata(config or {})


def _visible_configuration_rows(
    rows: list[dict[str, Any]],
    *metadata_fields: str,
    include_validation: bool,
) -> list[dict[str, Any]]:
    return [
        row
        for row in rows
        if is_visible_product_data(
            *(row.get(field) for field in metadata_fields),
            include_validation=include_validation,
        )
    ]


def _owned_criterion(model: Any, organization_id: Any, *, include_global: bool = False) -> Any:
    if include_global:
        return or_(model.organization_id == organization_id, model.organization_id.is_(None))
    return model.organization_id == organization_id


def _organization_section(
    db: Session,
    *,
    organization_id: Any,
    platform_scope: bool,
    include_validation: bool,
    validation_organization_ids: set[Any],
) -> dict[str, Any]:
    organization_criteria: tuple[Any, ...] = ()
    node_criteria: tuple[Any, ...] = ()
    relationship_criteria: tuple[Any, ...] = ()
    if not platform_scope:
        organization_criteria = (Organization.id == organization_id,)
        node_criteria = (OrganizationNode.organization_id == organization_id,)
        relationship_criteria = (OrganizationRelationship.organization_id == organization_id,)
    elif not include_validation and validation_organization_ids:
        organization_criteria = (Organization.id.notin_(validation_organization_ids),)
        node_criteria = (OrganizationNode.organization_id.notin_(validation_organization_ids),)
        relationship_criteria = (OrganizationRelationship.organization_id.notin_(validation_organization_ids),)
    organizations = _rows(
        db,
        Organization,
        ("id", "slug", "name", "description", "status", "config"),
        Organization.slug.asc(),
        *organization_criteria,
    )
    for organization in organizations:
        organization["data_classification"] = _organization_data_classification(
            organization.get("config") if isinstance(organization.get("config"), dict) else {}
        )
    location_types = {"location", "region", "area"}
    nodes = _rows(
        db,
        OrganizationNode,
        (
            "id",
            "organization_id",
            "parent_node_id",
            "node_type",
            "code",
            "name",
            "description",
            "metadata_json",
            "position",
            "status",
        ),
        OrganizationNode.organization_id.asc(),
        *node_criteria,
    )
    relationships = _rows(
        db,
        OrganizationRelationship,
        ("id", "organization_id", "source_node_id", "target_node_id", "relationship_type", "metadata_json", "status"),
        OrganizationRelationship.organization_id.asc(),
        *relationship_criteria,
    )
    return {
        "organizations": organizations,
        "organization_hierarchy": {
            "nodes": nodes,
            "relationships": relationships,
        },
        "locations": [item for item in nodes if str(item.get("node_type", "")).lower() in location_types],
        "counts": {
            "organizations": len(organizations),
            "organization_nodes": len(nodes),
            "organization_relationships": len(relationships),
            "locations": len([item for item in nodes if str(item.get("node_type", "")).lower() in location_types]),
        },
    }


def _security_section(
    db: Session,
    *,
    organization_id: Any,
    platform_scope: bool,
    include_validation: bool,
    validation_organization_ids: set[Any],
) -> dict[str, Any]:
    roles = list_roles(db, organization_id=None if platform_scope else organization_id, limit=10000)
    permissions = [
        {
            **item,
            "code": item["key"],
            "name": item.get("description") or str(item["key"]).replace(".", " ").replace(":", " — "),
            "status": "active",
            "scope_domain": str(item["resource"]).split(".", 1)[0],
        }
        for item in list_permissions(db, limit=10000)
    ]
    policies = list_policies(db, organization_id=None if platform_scope else organization_id, limit=10000)
    assignments = list_role_assignments(db, organization_id=None if platform_scope else organization_id, limit=10000)
    if platform_scope and not include_validation:
        roles = [item for item in roles if item.get("organization_id") not in validation_organization_ids]
        policies = [item for item in policies if item.get("organization_id") not in validation_organization_ids]
        assignments = [item for item in assignments if item.get("organization_id") not in validation_organization_ids]
    role_ids = [item["id"] for item in roles]
    role_permission_count = _count(db, RolePermission, RolePermission.role_id.in_(role_ids)) if role_ids else 0
    readiness = {
        "roles_count": len(roles),
        "permissions_count": len(permissions),
        "policies_count": len(policies),
        "assignments_count": len(assignments),
        "security_management_ready": bool(roles and permissions),
        "postgresql_source_of_truth": True,
    }
    return {
        "readiness": readiness,
        "roles": roles,
        "permissions": permissions,
        "policies": policies,
        "assignments": assignments,
        "effective_totals": {
            "roles": len(roles),
            "permissions": len(permissions),
            "policies": len(policies),
            "assignments": len(assignments),
            "role_permissions": role_permission_count,
        },
    }


def _documents_section(
    db: Session,
    *,
    organization_id: Any,
    platform_scope: bool,
    include_validation: bool,
    validation_organization_ids: set[Any],
) -> dict[str, Any]:
    if not platform_scope:
        criteria = (_owned_criterion(DocumentRecord, organization_id),)
        version_criteria = (_owned_criterion(DocumentVersion, organization_id),)
        artifact_criteria = (_owned_criterion(Artifact, organization_id),)
        chunk_criteria = (_owned_criterion(Chunk, organization_id),)
        job_criteria = (_owned_criterion(IngestionJob, organization_id),)
    elif not include_validation and validation_organization_ids:
        criteria = (DocumentRecord.organization_id.notin_(validation_organization_ids),)
        version_criteria = (DocumentVersion.organization_id.notin_(validation_organization_ids),)
        artifact_criteria = (Artifact.organization_id.notin_(validation_organization_ids),)
        chunk_criteria = (Chunk.organization_id.notin_(validation_organization_ids),)
        job_criteria = (IngestionJob.organization_id.notin_(validation_organization_ids),)
    else:
        criteria = version_criteria = artifact_criteria = chunk_criteria = job_criteria = ()
    configuration_contract = build_document_configuration_contract(db) if platform_scope else {"scope": "organization"}

    def configuration_criteria(model: Any) -> tuple[Any, ...]:
        if not platform_scope:
            return (_owned_criterion(model, organization_id, include_global=True),)
        if not include_validation and validation_organization_ids:
            return (or_(model.organization_id.is_(None), model.organization_id.notin_(validation_organization_ids)),)
        return ()

    configuration_criterion = configuration_criteria(DocumentType)
    document_types = _visible_configuration_rows(
        _rows(
            db,
            DocumentType,
            ("id", "organization_id", "code", "name", "description", "version", "status", "config"),
            DocumentType.code.asc(),
            *configuration_criterion,
        ),
        "config",
        include_validation=include_validation,
    )
    visible_document_type_ids = {item["id"] for item in document_types}
    metadata_templates = _visible_configuration_rows(
        _rows(
            db,
            MetadataTemplate,
            ("id", "organization_id", "document_type_id", "code", "name", "schema_definition", "status"),
            MetadataTemplate.code.asc(),
            *configuration_criteria(MetadataTemplate),
        ),
        "schema_definition",
        include_validation=include_validation,
    )
    metadata_templates = [
        item
        for item in metadata_templates
        if item.get("document_type_id") is None or item.get("document_type_id") in visible_document_type_ids
    ]
    retention_policies = _visible_configuration_rows(
        _rows(
            db,
            RetentionPolicy,
            ("id", "organization_id", "code", "name", "rules", "status"),
            RetentionPolicy.code.asc(),
            *configuration_criteria(RetentionPolicy),
        ),
        "rules",
        include_validation=include_validation,
    )
    classification_rules = _visible_configuration_rows(
        _rows(
            db,
            ClassificationRule,
            ("id", "organization_id", "code", "name", "rules", "status"),
            ClassificationRule.code.asc(),
            *configuration_criteria(ClassificationRule),
        ),
        "rules",
        include_validation=include_validation,
    )
    collections = _visible_configuration_rows(
        _rows(
            db,
            Collection,
            (
                "id",
                "organization_id",
                "code",
                "name",
                "description",
                "vector_provider",
                "vector_collection_name",
                "config",
                "status",
            ),
            Collection.code.asc(),
            *configuration_criteria(Collection),
        ),
        "config",
        include_validation=include_validation,
    )
    knowledge_sources = _visible_configuration_rows(
        _rows(
            db,
            KnowledgeSource,
            ("id", "organization_id", "agent_id", "collection_id", "source_type", "source_id", "config", "status"),
            KnowledgeSource.id.asc(),
            *configuration_criteria(KnowledgeSource),
        ),
        "config",
        include_validation=include_validation,
    )
    return {
        "configuration_contract": configuration_contract,
        "document_types": document_types,
        "metadata_templates": metadata_templates,
        "retention_policies": retention_policies,
        "classification_rules": classification_rules,
        "collections": collections,
        "knowledge_sources": knowledge_sources,
        "counts": {
            "document_types": len(document_types),
            "metadata_templates": len(metadata_templates),
            "retention_policies": len(retention_policies),
            "classification_rules": len(classification_rules),
            "collections": len(collections),
            "knowledge_sources": len(knowledge_sources),
            "document_records": _count(db, DocumentRecord, *criteria),
            "document_versions": _count(db, DocumentVersion, *version_criteria),
            "artifacts": _count(db, Artifact, *artifact_criteria),
            "chunks": _count(db, Chunk, *chunk_criteria),
            "ingestion_jobs": _count(db, IngestionJob, *job_criteria),
        },
        "status_totals": {
            "document_records": _count_by_status(db, DocumentRecord, DocumentRecord.status, *criteria),
            "document_versions": _count_by_status(db, DocumentVersion, DocumentVersion.status, *version_criteria),
            "artifacts": _count_by_status(db, Artifact, Artifact.status, *artifact_criteria),
            "chunks": _count_by_status(db, Chunk, Chunk.status, *chunk_criteria),
            "ingestion_jobs": _count_by_status(db, IngestionJob, IngestionJob.status, *job_criteria),
        },
    }


def _knowledge_section(
    db: Session,
    *,
    organization_id: Any,
    platform_scope: bool,
    include_validation: bool,
    validation_organization_ids: set[Any],
) -> dict[str, Any]:
    record_statement = select(DocumentRecord.id)
    if not platform_scope:
        record_statement = record_statement.where(DocumentRecord.organization_id == organization_id)
    elif not include_validation and validation_organization_ids:
        record_statement = record_statement.where(DocumentRecord.organization_id.notin_(validation_organization_ids))
    record_ids = [str(item) for item in db.scalars(record_statement).all()]
    document_criteria = (KnowledgeDocument.document_record_id.in_(record_ids),) if record_ids else (False,)
    knowledge_document_ids = list(db.scalars(select(KnowledgeDocument.id).where(*document_criteria)).all())
    chunk_criteria = (
        (KnowledgeChunk.knowledge_document_id.in_(knowledge_document_ids),)
        if knowledge_document_ids
        else (False,)
    )
    collections = list_knowledge_collections(
        db,
        organization_id=None if platform_scope else organization_id,
        limit=10000,
    )
    if platform_scope and not include_validation and validation_organization_ids:
        collections = [
            item for item in collections if item.get("organization_id") not in validation_organization_ids
        ]
    collections = [
        item
        for item in collections
        if is_visible_product_data(
            item.get("config"),
            item.get("metadata"),
            include_validation=include_validation,
        )
    ]
    knowledge_document_count = _count(db, KnowledgeDocument, *document_criteria)
    knowledge_chunk_count = _count(db, KnowledgeChunk, *chunk_criteria)
    indexed_documents = _count(
        db,
        KnowledgeDocument,
        *document_criteria,
        KnowledgeDocument.status.in_(("indexed", "ready")),
    )
    indexed_chunks = _count(
        db,
        KnowledgeChunk,
        *chunk_criteria,
        KnowledgeChunk.status.in_(("indexed", "ready")),
    )
    index_ready = indexed_documents > 0 and indexed_chunks > 0
    return {
        "collections": collections,
        "knowledge_documents": {
            "count": knowledge_document_count,
            "by_status": _count_by_status(db, KnowledgeDocument, KnowledgeDocument.status, *document_criteria),
        },
        "knowledge_chunks": {
            "count": knowledge_chunk_count,
            "by_status": _count_by_status(db, KnowledgeChunk, KnowledgeChunk.status, *chunk_criteria),
        },
        "readiness": {
            "knowledge_index_ready": index_ready,
            "indexed_document_count": indexed_documents,
            "indexed_chunk_count": indexed_chunks,
            "postgresql_source_of_truth": True,
            "llm_used": False,
            "embeddings_used": False,
            "qdrant_used": False,
        },
        "publication_statistics": {
            "runtime_records": _count(
                db,
                RuntimePersistenceRecord,
                RuntimePersistenceRecord.runtime_domain == "knowledge_publication",
            ),
        },
        "index_statistics": {
            "documents": {
                "total": knowledge_document_count,
                "indexed": indexed_documents,
                "by_status": _count_by_status(db, KnowledgeDocument, KnowledgeDocument.status, *document_criteria),
            },
            "chunks": {
                "total": knowledge_chunk_count,
                "indexed": indexed_chunks,
                "by_status": _count_by_status(db, KnowledgeChunk, KnowledgeChunk.status, *chunk_criteria),
            },
        },
    }


def _enterprise_search_section(
    db: Session,
    knowledge: dict[str, Any],
    *,
    organization_id: Any,
    platform_scope: bool,
) -> dict[str, Any]:
    search_criteria = () if platform_scope else (_owned_criterion(AssistantSearchExecution, organization_id),)
    search_executions = _count(db, AssistantSearchExecution, *search_criteria)
    completed_searches = _count(
        db,
        AssistantSearchExecution,
        *search_criteria,
        AssistantSearchExecution.search_completed.is_(True),
    )
    indexed_chunks = int((knowledge.get("knowledge_chunks") or {}).get("by_status", {}).get("indexed", 0))
    return {
        "fts_readiness": {
            "postgresql_fts_available": True,
            "indexed_chunk_count": indexed_chunks,
            "ready": indexed_chunks > 0,
        },
        "knowledge_index_readiness": knowledge.get("readiness", {}),
        "search_readiness": {
            "ready": indexed_chunks > 0,
            "search_executions": search_executions,
            "completed_searches": completed_searches,
        },
        "statistics": {
            "assistant_search_executions": search_executions,
            "completed_searches": completed_searches,
            "runtime_records": _count(
                db,
                RuntimePersistenceRecord,
                RuntimePersistenceRecord.runtime_domain == "enterprise_search",
            ),
        },
    }


def _assistants_section(
    db: Session,
    *,
    organization_id: Any,
    platform_scope: bool,
    include_validation: bool,
    validation_organization_ids: set[Any],
) -> dict[str, Any]:
    assistant_criteria: tuple[Any, ...] = (
        AssistantDefinition.ownership_scope != "legacy_unscoped",
    )
    if not include_validation:
        assistant_criteria += (AssistantDefinition.data_origin != "validation",)
    if not platform_scope:
        assistant_criteria += (
            or_(
                AssistantDefinition.ownership_scope == "global",
                (AssistantDefinition.ownership_scope == "organization")
                & (AssistantDefinition.organization_id == organization_id),
            ),
        )
    def visible_criteria(model: Any) -> tuple[Any, ...]:
        if not platform_scope:
            return (_owned_criterion(model, organization_id, include_global=True),)
        if not include_validation and validation_organization_ids:
            return (or_(model.organization_id.is_(None), model.organization_id.notin_(validation_organization_ids)),)
        return ()

    owned = visible_criteria(AiModel)
    return {
        "assistant_definitions": _rows(
            db,
            AssistantDefinition,
            (
                "assistant_id",
                "assistant_key",
                "assistant_name",
                "assistant_status",
                "assistant_version",
                "assistant_type",
                "default_search_mode",
            ),
            AssistantDefinition.assistant_key.asc(),
            *assistant_criteria,
        ),
        "models": _rows(
            db,
            AiModel,
            ("id", "organization_id", "code", "name", "provider", "model_name", "status", "enabled"),
            AiModel.code.asc(),
            *owned,
        ),
        "prompts": _rows(
            db,
            Prompt,
            ("id", "organization_id", "code", "name", "status", "enabled", "version"),
            Prompt.code.asc(),
            *visible_criteria(Prompt),
        ),
        "guardrails": _rows(
            db,
            Guardrail,
            ("id", "organization_id", "code", "name", "status", "enabled", "guardrail_type"),
            Guardrail.code.asc(),
            *visible_criteria(Guardrail),
        ),
        "workflows": _rows(
            db,
            Workflow,
            ("id", "organization_id", "code", "name", "status"),
            Workflow.code.asc(),
            *visible_criteria(Workflow),
        ),
        "knowledge_source_assignments": _rows(
            db,
            KnowledgeSource,
            ("id", "organization_id", "agent_id", "collection_id", "source_type", "source_id", "status"),
            KnowledgeSource.id.asc(),
            *visible_criteria(KnowledgeSource),
        ),
        "providers": _rows(
            db,
            Provider,
            (
                "id",
                "organization_id",
                "provider_key",
                "display_name",
                "adapter_type",
                "provider_type",
                "status",
                "enabled",
                "health_state",
            ),
            Provider.provider_key.asc(),
            *visible_criteria(Provider),
        ),
        "runtime_profiles": _rows(
            db,
            RuntimeProfile,
            (
                "id",
                "organization_id",
                "profile_key",
                "display_name",
                "answer_mode",
                "generation_enabled",
                "status",
                "is_default",
            ),
            RuntimeProfile.profile_key.asc(),
            *visible_criteria(RuntimeProfile),
        ),
        "conversation_statistics": {
            "assistant_sessions": _count(
                db,
                AssistantSession,
                *(() if platform_scope else (_owned_criterion(AssistantSession, organization_id),)),
            ),
            "assistant_runtime_runs": _count(
                db,
                AssistantRuntimeRun,
                *(() if platform_scope else (_owned_criterion(AssistantRuntimeRun, organization_id),)),
            ),
            "llm_executions": _count(
                db,
                AssistantLlmExecution,
                *(() if platform_scope else (_owned_criterion(AssistantLlmExecution, organization_id),)),
            ),
            "assistant_responses": _count(
                db,
                AssistantResponse,
                *(() if platform_scope else (_owned_criterion(AssistantResponse, organization_id),)),
            ),
            "conversations": _count(
                db, Conversation, *(() if platform_scope else (_owned_criterion(Conversation, organization_id),))
            ),
            "conversation_turns": _count(
                db,
                ConversationTurn,
                *(() if platform_scope else (_owned_criterion(ConversationTurn, organization_id),)),
            ),
        },
    }


def _runtime_status_section(db: Session, *, organization_id: Any, platform_scope: bool) -> dict[str, Any]:
    execution_criteria = () if platform_scope else (RuntimeExecution.organization_id == organization_id,)
    configuration_criteria = () if platform_scope else (
        or_(RuntimeConfiguration.organization_id == organization_id, RuntimeConfiguration.organization_id.is_(None)),
    )
    return {
        "runtime_executions": {
            "count": _count(db, RuntimeExecution, *execution_criteria),
            "by_status": _count_by_status(db, RuntimeExecution, RuntimeExecution.status, *execution_criteria),
        },
        "runtime_persistence": {
            "count": _count(db, RuntimePersistenceRecord) if platform_scope else 0,
            "by_status": _count_by_status(db, RuntimePersistenceRecord, RuntimePersistenceRecord.persistence_status)
            if platform_scope
            else {},
            "scope_status": "platform_only" if not platform_scope else "available",
        },
        "runtime_workers": {
            "count": _count(db, RuntimeWorker) if platform_scope else 0,
            "by_status": _count_by_status(db, RuntimeWorker, RuntimeWorker.observed_state) if platform_scope else {},
            "scope_status": "platform_only" if not platform_scope else "available",
        },
        "runtime_configurations": {
            "count": _count(db, RuntimeConfiguration, *configuration_criteria),
            "revisions": _count(db, RuntimeConfigurationRevision) if platform_scope else 0,
        },
    }


def _feedback_audit_section(db: Session, *, organization_id: Any, platform_scope: bool) -> dict[str, Any]:
    event_criteria = () if platform_scope else (AuditEvent.organization_id == organization_id,)
    feedback_events = _count(db, AuditEvent, *event_criteria, AuditEvent.resource_type == "feedback")
    return {
        "feedback_records": feedback_events,
        "audit_actions": _count(db, AuditAction) if platform_scope else 0,
        "audit_events": _count(db, AuditEvent, *event_criteria),
        "audit_history": _count(db, AuditHistory) if platform_scope else 0,
        "feedback_center_ready": True,
        "audit_explorer_ready": True,
    }


def _capability_flags(sections: dict[str, Any]) -> dict[str, bool]:
    organizations = sections["organizations"]["counts"]["organizations"] > 0
    security = bool(sections["security"]["readiness"].get("security_management_ready"))
    documents = bool(sections["documents"]["document_types"])
    knowledge = int(sections["knowledge"]["knowledge_documents"]["count"]) > 0
    assistants = bool(sections["assistants"]["assistant_definitions"])
    reference_tenant = bool(sections["reference_tenant"]["readiness"].get("reference_tenant_ready"))
    return {
        "organizations_configured": organizations,
        "security_configured": security,
        "documents_configured": documents,
        "knowledge_index_configured": knowledge,
        "enterprise_search_configured": bool(sections["enterprise_search"]["search_readiness"].get("ready")),
        "assistants_configured": assistants,
        "reference_tenant_ready": reference_tenant,
        "feedback_audit_available": True,
    }


def _health_summary(
    sections: dict[str, Any],
    *,
    platform_scope: bool,
) -> dict[str, Any]:
    domain_ready = {
        "platform": True,
        "organizations": sections["organizations"]["counts"]["organizations"] > 0,
        "security": bool(sections["security"]["readiness"].get("security_management_ready")),
        "documents": bool(sections["documents"]["document_types"]),
        "knowledge": int(sections["knowledge"]["knowledge_documents"]["count"]) > 0,
        "enterprise_search": bool(sections["enterprise_search"]["search_readiness"].get("ready")),
        "assistants": bool(sections["assistants"]["assistant_definitions"]),
        "reference_tenant": bool(sections["reference_tenant"]["readiness"].get("reference_tenant_ready")),
    }
    blocking_domains = sorted(
        domain
        for domain, ready in domain_ready.items()
        if not ready and (platform_scope or domain != "reference_tenant")
    )
    return {
        "runtime_ready": not blocking_domains,
        "domain_ready": domain_ready,
        "blocking_domains": blocking_domains,
        "warnings": [],
        "blocking_issues": [
            {
                "code": "mandatory_domain_not_ready",
                "message": f"Platform administration mandatory domain is not ready: {domain}.",
                "component": "platform_administration",
                "domain": domain,
            }
            for domain in blocking_domains
        ],
    }


def build_platform_administration_runtime(
    db: Session,
    *,
    organization_id: Any = None,
    platform_scope: bool = True,
    include_validation: bool = False,
) -> dict[str, Any]:
    settings = get_settings()
    platform_info = build_platform_info(settings).model_dump()
    validation_organization_ids = _validation_organization_ids(db)
    organizations = _organization_section(
        db,
        organization_id=organization_id,
        platform_scope=platform_scope,
        include_validation=include_validation,
        validation_organization_ids=validation_organization_ids,
    )
    security = _security_section(
        db,
        organization_id=organization_id,
        platform_scope=platform_scope,
        include_validation=include_validation,
        validation_organization_ids=validation_organization_ids,
    )
    documents = _documents_section(
        db,
        organization_id=organization_id,
        platform_scope=platform_scope,
        include_validation=include_validation,
        validation_organization_ids=validation_organization_ids,
    )
    knowledge = _knowledge_section(
        db,
        organization_id=organization_id,
        platform_scope=platform_scope,
        include_validation=include_validation,
        validation_organization_ids=validation_organization_ids,
    )
    enterprise_search = _enterprise_search_section(
        db,
        knowledge,
        organization_id=organization_id,
        platform_scope=platform_scope,
    )
    assistants = _assistants_section(
        db,
        organization_id=organization_id,
        platform_scope=platform_scope,
        include_validation=include_validation,
        validation_organization_ids=validation_organization_ids,
    )
    selected_organization = db.get(Organization, organization_id) if organization_id is not None else None
    is_reference_scope = platform_scope
    reference_readiness = (
        build_reference_tenant_readiness(db) if is_reference_scope else {"reference_tenant_ready": False}
    )
    reference_validation = validate_reference_tenant(db) if is_reference_scope else {"product_baseline_ready": False}
    reference_status = build_reference_tenant_status(db) if is_reference_scope else {"status": "not_applicable"}
    runtime_status = _runtime_status_section(db, organization_id=organization_id, platform_scope=platform_scope)
    feedback_audit = _feedback_audit_section(db, organization_id=organization_id, platform_scope=platform_scope)
    sections = {
        "organizations": organizations,
        "security": security,
        "documents": documents,
        "knowledge": knowledge,
        "enterprise_search": enterprise_search,
        "assistants": assistants,
        "reference_tenant": {
            "readiness": reference_readiness,
            "validation": reference_validation,
            "status": reference_status,
            "product_baseline": {
                "product_baseline_ready": bool(reference_validation.get("product_baseline_ready")),
                "pending_capabilities": reference_validation.get("pending_capabilities") or [],
                "blocking_issues": reference_validation.get("blocking_issues") or [],
            },
        },
    }
    health = _health_summary(sections, platform_scope=platform_scope)
    configured_capabilities = _capability_flags(sections)
    platform = {
        "metadata": platform_info,
        "version": platform_info.get("product_version"),
        "edition": "community",
        "runtime_status": runtime_status,
        "configured_capabilities": configured_capabilities,
        "installed_capabilities": list(INSTALLED_CAPABILITIES),
        "feature_flags": platform_info.get("feature_flags") or {},
        "health_summary": health,
        "feedback_audit": feedback_audit,
    }
    return {
        "platform_administration_runtime_schema_version": PLATFORM_ADMINISTRATION_RUNTIME_SCHEMA_VERSION,
        "runtime_name": PLATFORM_ADMINISTRATION_RUNTIME_NAME,
        "runtime_status": "ready" if health["runtime_ready"] else "degraded",
        "platform": platform,
        "organizations": organizations,
        "security": security,
        "documents": documents,
        "knowledge": knowledge,
        "enterprise_search": enterprise_search,
        "assistants": assistants,
        "reference_tenant": sections["reference_tenant"],
        "health_summary": health,
        "warnings": health["warnings"],
        "blocking_issues": health["blocking_issues"],
        "postgresql_source_of_truth": True,
        "llm_used": False,
        "embeddings_used": False,
        "qdrant_used": False,
        "data_scope": {
            "scope_type": "platform" if platform_scope else "organization",
            "organization_id": str(organization_id) if organization_id else None,
            "include_validation": include_validation,
            "validation_records_hidden": not include_validation,
            "legacy_unscoped_hidden": True,
            "selected_data_classification": _organization_data_classification(
                selected_organization.config if selected_organization else {}
            )
            if not platform_scope
            else "mixed_operational",
        },
    }
