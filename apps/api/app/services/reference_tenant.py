from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.ai import Guardrail, KnowledgeSource, Prompt, Workflow
from app.models.ai import Model as AiModel
from app.models.assistant_runtime import AssistantDefinition
from app.models.audit import AuditEvent
from app.models.core import Organization, OrganizationNode
from app.models.documents import (
    Artifact,
    ClassificationRule,
    Collection,
    DocumentRecord,
    DocumentType,
    DocumentVersion,
    MetadataTemplate,
    RetentionPolicy,
)
from app.models.knowledge_index import KnowledgeChunk, KnowledgeDocument
from app.models.security import Permission, Policy, Role, RoleAssignment, RolePermission
from app.schemas.documents import DocumentLifecycleOrchestrateRequest, DocumentRegistrationRequest
from app.security.platform_roles import PLATFORM_ADMIN_PERMISSION_CATALOG
from app.services.document_lifecycle_orchestrator import build_document_lifecycle_orchestration

REFERENCE_ORGANIZATION_SLUG = "reference-tenant"
REFERENCE_MARKER = {"reference_tenant": True, "canonical_product_reference": True}

REFERENCE_PERMISSIONS = (
    ("reference_tenant", "read", "Read reference tenant configuration."),
    ("reference_tenant", "administer", "Administer reference tenant configuration."),
    ("organization.dashboard", "read", "Read the selected organization's product dashboard."),
    ("organization.security", "read", "Read organization-owned access configuration and posture."),
    (
        "organization.security",
        "administer",
        "Administer organization-owned memberships, roles, assignments, and policies.",
    ),
    ("organization.reporting", "read", "Read analytics scoped to the selected organization."),
    ("knowledge_collections", "read", "Read knowledge collection configuration."),
    ("document_configuration", "read", "Read document configuration."),
    ("documents", "read", "Read organization-owned documents and lifecycle state."),
    ("documents", "administer", "Register and process organization-owned documents."),
    ("control_plane.health", "read", "Read organization operational health."),
    ("control_plane.reconciliation", "read", "Preview artifact reconciliation."),
    ("control_plane.reconciliation", "administer", "Run bounded artifact reconciliation."),
    ("control_plane.scheduler", "read", "Read scheduler jobs, schedules, and runs."),
    ("control_plane.scheduler", "administer", "Administer scheduler jobs, schedules, and evaluations."),
    ("platform.assistants", "read", "Read organization-owned assistants, conversations, and chat history."),
    ("platform.assistants", "administer", "Operate organization-owned assistants, conversations, and chat."),
    ("ai.configuration", "read", "Read organization AI provider and model configuration."),
    ("ai.providers", "administer", "Administer organization AI provider configurations."),
    ("ai.models", "administer", "Administer organization AI model configurations."),
    ("ai.validation", "execute", "Validate organization AI provider and model configurations."),
)

REFERENCE_REVIEWER_PERMISSIONS = tuple(
    permission
    for permission in REFERENCE_PERMISSIONS
    if permission[1] == "read" and permission[0] != "organization.security"
)

REFERENCE_PLATFORM_PERMISSIONS = PLATFORM_ADMIN_PERMISSION_CATALOG

REFERENCE_ROLES = (
    ("reference-administrator", "Reference Administrator", "Generic administrator for the reference tenant."),
    ("reference-reviewer", "Reference Reviewer", "Generic reviewer for the reference tenant."),
)

REFERENCE_PLATFORM_ROLE = (
    "reference-platform-operator",
    "Reference Platform Operator",
    "Generic platform operator for the reference tenant.",
)

REFERENCE_DOCUMENTS = (
    {
        "logical_key": "reference-platform-overview",
        "title": "Reference Platform Overview",
        "file_name": "reference-platform-overview.txt",
        "search_query": "governed knowledge enterprise search assistants audit",
        "description": "Generic overview of the Industrial AI Platform reference tenant.",
        "content": (
            "Reference Platform Overview\n\n"
            "The Industrial AI Platform organizes governed knowledge in configurable collections. "
            "Documents move through registration, versioning, binary storage, processing, publication, "
            "PostgreSQL knowledge indexing, enterprise search, assistant context assembly, citations, "
            "feedback, audit, and runtime traceability. PostgreSQL remains the source of truth for "
            "platform state, lifecycle state, security configuration, knowledge metadata, search records, "
            "feedback, and audit history. AI services are optional and do not own platform truth."
        ),
    },
    {
        "logical_key": "reference-governance-guide",
        "title": "Reference Governance Guide",
        "file_name": "reference-governance-guide.txt",
        "search_query": "security collections citations feedback audit runtime traceability",
        "description": "Generic governance guide for the Industrial AI Platform reference tenant.",
        "content": (
            "Reference Governance Guide\n\n"
            "The platform uses configurable organizations, roles, permissions, policies, document types, "
            "metadata templates, retention policies, classification rules, knowledge collections, prompts, "
            "guardrails, workflows, assistants, and knowledge sources. Enterprise Search uses PostgreSQL "
            "full text search as the governed lexical baseline. Assistant responses should use searchable "
            "governed content, cite retrieved evidence when available, and keep feedback and audit events "
            "persisted for administrative review."
        ),
    },
)


@dataclass
class AssetResult:
    domain: str
    asset_type: str
    logical_name: str
    status: str
    created_or_reused: str
    asset_id: str | None = None
    details: dict[str, Any] | None = None
    logical_key: str | None = None
    readiness: str = "ready"
    dependencies: list[str] | None = None
    blocking_issues: list[dict[str, Any]] | None = None
    pending_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset_type": self.asset_type,
            "logical_key": self.logical_key or self.logical_name,
            "asset_id": self.asset_id,
            "logical_name": self.logical_name,
            "status": self.status,
            "created_or_reused": self.created_or_reused,
            "source_domain": self.domain,
            "readiness": self.readiness,
            "dependencies": self.dependencies or [],
            "blocking_issues": self.blocking_issues or [],
            "pending_reason": self.pending_reason,
            "details": self.details or {},
        }


def _issue(code: str, message: str, *, component: str = "reference_tenant") -> dict[str, Any]:
    return {"code": code, "message": message, "component": component}


def _sort_issues(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        issues,
        key=lambda item: (str(item.get("component", "")), str(item.get("code", "")), str(item.get("message", ""))),
    )


def _merge_marker(value: dict[str, Any] | None) -> dict[str, Any]:
    merged = dict(value or {})
    merged.update(REFERENCE_MARKER)
    return merged


def _flush(db: Session) -> None:
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise


def _organization_to_dict(organization: Organization | None) -> dict[str, Any] | None:
    if organization is None:
        return None
    return {
        "id": organization.id,
        "slug": organization.slug,
        "name": organization.name,
        "description": organization.description,
        "status": organization.status,
        "config": organization.config or {},
        "created_at": organization.created_at,
        "updated_at": organization.updated_at,
    }


def _simple_model_dict(item: Any, keys: tuple[str, ...]) -> dict[str, Any]:
    payload = {"id": getattr(item, "id", getattr(item, "assistant_id", None))}
    for key in keys:
        payload[key] = getattr(item, key)
    return payload


def _reference_organization(db: Session) -> Organization | None:
    return db.scalar(select(Organization).where(Organization.slug == REFERENCE_ORGANIZATION_SLUG))


def _get_or_create_organization(db: Session, assets: list[AssetResult]) -> Organization:
    organization = _reference_organization(db)
    if organization is None:
        organization = Organization(
            slug=REFERENCE_ORGANIZATION_SLUG,
            name="Reference Tenant",
            description="Canonical generic reference tenant for the Industrial AI Platform.",
            status="active",
            config=_merge_marker({"tenant_kind": "reference"}),
        )
        db.add(organization)
        _flush(db)
        state = "created"
    else:
        state = "reused"
        organization.config = _merge_marker(organization.config)
        if organization.status != "active":
            organization.status = "active"
        db.add(organization)
        _flush(db)
    assets.append(
        AssetResult(
            "core",
            "organization",
            organization.slug,
            organization.status,
            state,
            str(organization.id),
        )
    )
    return organization


def _get_or_create_organization_node(
    db: Session, organization: Organization, assets: list[AssetResult]
) -> OrganizationNode:
    node = db.scalar(
        select(OrganizationNode).where(
            OrganizationNode.organization_id == organization.id,
            OrganizationNode.code == "reference-root",
        )
    )
    if node is None:
        node = OrganizationNode(
            organization_id=organization.id,
            parent_node_id=None,
            node_type="organization_unit",
            code="reference-root",
            name="Reference Root",
            description="Generic root node for the reference tenant.",
            metadata_json=REFERENCE_MARKER.copy(),
            position={},
            status="active",
        )
        db.add(node)
        _flush(db)
        state = "created"
    else:
        state = "reused"
        node.metadata_json = _merge_marker(node.metadata_json)
        node.status = "active"
        db.add(node)
        _flush(db)
    assets.append(AssetResult("core", "organization_node", node.code, node.status, state, str(node.id)))
    return node


def _get_or_create_permission(
    db: Session,
    resource: str,
    action: str,
    description: str,
    assets: list[AssetResult],
) -> Permission:
    permission = db.scalar(select(Permission).where(Permission.resource == resource, Permission.action == action))
    if permission is None:
        permission = Permission(resource=resource, action=action, description=description)
        db.add(permission)
        _flush(db)
        state = "created"
    else:
        state = "reused"
    assets.append(
        AssetResult(
            "security",
            "permission",
            f"{resource}:{action}",
            "active",
            state,
            str(permission.id),
        )
    )
    return permission


def _get_or_create_role(
    db: Session,
    organization: Organization,
    code: str,
    name: str,
    description: str,
    assets: list[AssetResult],
) -> Role:
    role = db.scalar(select(Role).where(Role.organization_id == organization.id, Role.code == code))
    if role is None:
        role = Role(
            organization_id=organization.id,
            code=code,
            name=name,
            description=description,
            is_system=False,
            status="active",
            config=_merge_marker({}),
        )
        db.add(role)
        _flush(db)
        state = "created"
    else:
        state = "reused"
        role.config = _merge_marker(role.config)
        role.status = "active"
        db.add(role)
        _flush(db)
    assets.append(AssetResult("security", "role", role.code, role.status, state, str(role.id)))
    return role


def _get_or_create_platform_role(
    db: Session,
    code: str,
    name: str,
    description: str,
    assets: list[AssetResult],
) -> Role:
    role = db.scalar(select(Role).where(Role.organization_id.is_(None), Role.code == code))
    if role is None:
        role = Role(
            organization_id=None,
            code=code,
            name=name,
            description=description,
            is_system=False,
            status="active",
            config=_merge_marker({"scope": "platform"}),
        )
        db.add(role)
        _flush(db)
        state = "created"
    else:
        state = "reused"
        role.config = _merge_marker({**(role.config or {}), "scope": "platform"})
        role.status = "active"
        db.add(role)
        _flush(db)
    assets.append(AssetResult("security", "platform_role", role.code, role.status, state, str(role.id)))
    return role


def _attach_role_permission(
    db: Session, role: Role, permission: Permission, assets: list[AssetResult]
) -> RolePermission:
    link = db.scalar(
        select(RolePermission).where(
            RolePermission.role_id == role.id,
            RolePermission.permission_id == permission.id,
        )
    )
    if link is None:
        now = datetime.now(UTC)
        link = RolePermission(role_id=role.id, permission_id=permission.id, created_at=now, updated_at=now)
        db.add(link)
        _flush(db)
        state = "created"
    else:
        state = "reused"
    assets.append(
        AssetResult(
            "security",
            "role_permission",
            f"{role.code}:{permission.resource}:{permission.action}",
            "active",
            state,
            str(link.id),
        )
    )
    return link


def _reconcile_role_permission_catalog(
    db: Session,
    *,
    role_catalogs: list[tuple[Role, tuple[tuple[str, str, str], ...]]],
    assets: list[AssetResult],
) -> dict[str, int]:
    permission_catalog = {
        (resource, action): (resource, action, description)
        for _, catalog in role_catalogs
        for resource, action, description in catalog
    }
    permissions_created = 0
    permissions: dict[tuple[str, str], Permission] = {}
    for key, (resource, action, description) in permission_catalog.items():
        existing = db.scalar(
            select(Permission.id).where(
                Permission.resource == resource,
                Permission.action == action,
            )
        )
        permissions[key] = _get_or_create_permission(
            db,
            resource,
            action,
            description,
            assets,
        )
        permissions_created += int(existing is None)

    role_permissions_created = 0
    for role, catalog in role_catalogs:
        for resource, action, _ in catalog:
            permission = permissions[(resource, action)]
            existing = db.scalar(
                select(RolePermission.id).where(
                    RolePermission.role_id == role.id,
                    RolePermission.permission_id == permission.id,
                )
            )
            _attach_role_permission(db, role, permission, assets)
            role_permissions_created += int(existing is None)

    return {
        "permissions_created": permissions_created,
        "role_permissions_created": role_permissions_created,
        "permissions_reused": len(permission_catalog) - permissions_created,
    }


def _get_or_create_policy(db: Session, organization: Organization, assets: list[AssetResult]) -> Policy:
    policy = db.scalar(
        select(Policy).where(Policy.organization_id == organization.id, Policy.code == "reference-access")
    )
    if policy is None:
        policy = Policy(
            organization_id=organization.id,
            code="reference-access",
            name="Reference Access",
            effect="allow",
            rules={"scope": "reference_tenant", "permissions": ["read", "administer"]},
            status="active",
        )
        db.add(policy)
        _flush(db)
        state = "created"
    else:
        state = "reused"
        policy.status = "active"
        db.add(policy)
        _flush(db)
    assets.append(AssetResult("security", "policy", policy.code, policy.status, state, str(policy.id)))
    return policy


def _get_or_create_role_assignment(
    db: Session,
    organization: Organization,
    role: Role,
    principal_id: str,
    assets: list[AssetResult],
) -> RoleAssignment:
    assignment = db.scalar(
        select(RoleAssignment).where(
            RoleAssignment.organization_id == organization.id,
            RoleAssignment.role_id == role.id,
            RoleAssignment.principal_type == "reference_principal",
            RoleAssignment.principal_id == principal_id,
            RoleAssignment.scope_type == "organization",
            RoleAssignment.scope_id == str(organization.id),
        )
    )
    if assignment is None:
        assignment = RoleAssignment(
            organization_id=organization.id,
            role_id=role.id,
            principal_type="reference_principal",
            principal_id=principal_id,
            scope_type="organization",
            scope_id=str(organization.id),
            status="active",
        )
        db.add(assignment)
        _flush(db)
        state = "created"
    else:
        state = "reused"
        assignment.status = "active"
        db.add(assignment)
        _flush(db)
    assets.append(
        AssetResult(
            "security", "role_assignment", f"{principal_id}:{role.code}", assignment.status, state, str(assignment.id)
        )
    )
    return assignment


def _get_or_create_platform_role_assignment(
    db: Session,
    role: Role,
    principal_id: str,
    assets: list[AssetResult],
) -> RoleAssignment:
    assignment = db.scalar(
        select(RoleAssignment).where(
            RoleAssignment.organization_id.is_(None),
            RoleAssignment.role_id == role.id,
            RoleAssignment.principal_type == "reference_principal",
            RoleAssignment.principal_id == principal_id,
            RoleAssignment.scope_type == "platform",
            RoleAssignment.scope_id == "platform",
        )
    )
    if assignment is None:
        assignment = RoleAssignment(
            organization_id=None,
            role_id=role.id,
            principal_type="reference_principal",
            principal_id=principal_id,
            scope_type="platform",
            scope_id="platform",
            status="active",
        )
        db.add(assignment)
        _flush(db)
        state = "created"
    else:
        state = "reused"
        assignment.status = "active"
        db.add(assignment)
        _flush(db)
    assets.append(
        AssetResult(
            "security",
            "platform_role_assignment",
            f"{principal_id}:{role.code}",
            assignment.status,
            state,
            str(assignment.id),
        )
    )
    return assignment


def _get_or_create_collection(db: Session, organization: Organization, assets: list[AssetResult]) -> Collection:
    collection = db.scalar(
        select(Collection).where(
            Collection.organization_id == organization.id, Collection.code == "reference-knowledge"
        )
    )
    if collection is None:
        collection = Collection(
            organization_id=organization.id,
            code="reference-knowledge",
            name="Reference Knowledge",
            description="Generic governed knowledge collection for the reference tenant.",
            vector_provider=None,
            vector_collection_name=None,
            config=_merge_marker({"postgresql_fts": True}),
            status="active",
        )
        db.add(collection)
        _flush(db)
        state = "created"
    else:
        state = "reused"
        collection.config = _merge_marker(collection.config)
        collection.status = "active"
        db.add(collection)
        _flush(db)
    assets.append(
        AssetResult("knowledge", "knowledge_collection", collection.code, collection.status, state, str(collection.id))
    )
    return collection


def _get_or_create_document_type(db: Session, organization: Organization, assets: list[AssetResult]) -> DocumentType:
    item = db.scalar(
        select(DocumentType).where(
            DocumentType.organization_id == organization.id, DocumentType.code == "reference-document"
        )
    )
    if item is None:
        item = DocumentType(
            organization_id=organization.id,
            code="reference-document",
            name="Reference Document",
            description="Generic document type for the reference tenant.",
            version="1.0",
            status="active",
            config=_merge_marker({}),
        )
        db.add(item)
        _flush(db)
        state = "created"
    else:
        state = "reused"
        item.config = _merge_marker(item.config)
        item.status = "active"
        db.add(item)
        _flush(db)
    assets.append(AssetResult("documents", "document_type", item.code, item.status, state, str(item.id)))
    return item


def _get_or_create_metadata_template(
    db: Session,
    organization: Organization,
    document_type: DocumentType,
    assets: list[AssetResult],
) -> MetadataTemplate:
    item = db.scalar(
        select(MetadataTemplate).where(
            MetadataTemplate.organization_id == organization.id,
            MetadataTemplate.code == "reference-metadata",
        )
    )
    if item is None:
        item = MetadataTemplate(
            organization_id=organization.id,
            document_type_id=document_type.id,
            code="reference-metadata",
            name="Reference Metadata",
            schema_definition={"type": "object", "properties": {}, "additionalProperties": True},
            status="active",
        )
        db.add(item)
        _flush(db)
        state = "created"
    else:
        state = "reused"
        item.document_type_id = document_type.id
        item.status = "active"
        db.add(item)
        _flush(db)
    assets.append(AssetResult("documents", "metadata_template", item.code, item.status, state, str(item.id)))
    return item


def _get_or_create_retention_policy(
    db: Session, organization: Organization, assets: list[AssetResult]
) -> RetentionPolicy:
    item = db.scalar(
        select(RetentionPolicy).where(
            RetentionPolicy.organization_id == organization.id, RetentionPolicy.code == "reference-retention"
        )
    )
    if item is None:
        item = RetentionPolicy(
            organization_id=organization.id,
            code="reference-retention",
            name="Reference Retention",
            rules={"policy": "configurable"},
            status="active",
        )
        db.add(item)
        _flush(db)
        state = "created"
    else:
        state = "reused"
        item.status = "active"
        db.add(item)
        _flush(db)
    assets.append(AssetResult("documents", "retention_policy", item.code, item.status, state, str(item.id)))
    return item


def _get_or_create_classification_rule(
    db: Session, organization: Organization, assets: list[AssetResult]
) -> ClassificationRule:
    item = db.scalar(
        select(ClassificationRule).where(
            ClassificationRule.organization_id == organization.id,
            ClassificationRule.code == "reference-classification",
        )
    )
    if item is None:
        item = ClassificationRule(
            organization_id=organization.id,
            code="reference-classification",
            name="Reference Classification",
            rules={"classification": "configurable"},
            status="active",
        )
        db.add(item)
        _flush(db)
        state = "created"
    else:
        state = "reused"
        item.status = "active"
        db.add(item)
        _flush(db)
    assets.append(AssetResult("documents", "classification_rule", item.code, item.status, state, str(item.id)))
    return item


def _get_or_create_prompt(db: Session, organization: Organization, assets: list[AssetResult]) -> Prompt:
    item = db.scalar(
        select(Prompt).where(
            Prompt.organization_id == organization.id,
            or_(Prompt.code == "reference-assistant-prompt", Prompt.prompt_key == "reference-assistant-prompt"),
        )
    )
    if item is None:
        item = Prompt(
            organization_id=organization.id,
            code="reference-assistant-prompt",
            name="Reference Assistant Prompt",
            content=(
                "Use governed platform knowledge when available. If knowledge is unavailable, "
                "say that the capability is pending."
            ),
            variables={},
            status="active",
            prompt_key="reference-assistant-prompt",
            display_name="Reference Assistant Prompt",
            prompt_type="assistant",
            template=(
                "Use governed platform knowledge when available. If knowledge is unavailable, "
                "say that the capability is pending."
            ),
            template_format="text",
            enabled=True,
            version="1.0",
            metadata_json=REFERENCE_MARKER.copy(),
        )
        db.add(item)
        _flush(db)
        state = "created"
    else:
        state = "reused"
        item.status = "active"
        item.enabled = True
        item.metadata_json = _merge_marker(item.metadata_json)
        db.add(item)
        _flush(db)
    assets.append(AssetResult("ai", "prompt", item.code, item.status, state, str(item.id)))
    return item


def _get_or_create_guardrail(db: Session, organization: Organization, assets: list[AssetResult]) -> Guardrail:
    item = db.scalar(
        select(Guardrail).where(
            Guardrail.organization_id == organization.id,
            or_(Guardrail.code == "reference-guardrail", Guardrail.guardrail_key == "reference-guardrail"),
        )
    )
    if item is None:
        item = Guardrail(
            organization_id=organization.id,
            code="reference-guardrail",
            name="Reference Guardrail",
            rules={"mode": "governed"},
            status="active",
            guardrail_key="reference-guardrail",
            display_name="Reference Guardrail",
            guardrail_type="platform",
            policy={"answer_policy": "grounded_when_knowledge_available"},
            enforcement_mode="advisory",
            fallback_behavior="pending_capability",
            enabled=True,
            metadata_json=REFERENCE_MARKER.copy(),
        )
        db.add(item)
        _flush(db)
        state = "created"
    else:
        state = "reused"
        item.status = "active"
        item.enabled = True
        item.metadata_json = _merge_marker(item.metadata_json)
        db.add(item)
        _flush(db)
    assets.append(AssetResult("ai", "guardrail", item.code, item.status, state, str(item.id)))
    return item


def _get_or_create_workflow(db: Session, organization: Organization, assets: list[AssetResult]) -> Workflow:
    item = db.scalar(
        select(Workflow).where(
            Workflow.organization_id == organization.id, Workflow.code == "reference-readiness-workflow"
        )
    )
    if item is None:
        item = Workflow(
            organization_id=organization.id,
            code="reference-readiness-workflow",
            name="Reference Readiness Workflow",
            definition={"steps": [{"key": "validate_reference_tenant", "type": "readiness_check"}]},
            status="active",
        )
        db.add(item)
        _flush(db)
        state = "created"
    else:
        state = "reused"
        item.status = "active"
        db.add(item)
        _flush(db)
    assets.append(AssetResult("ai", "workflow", item.code, item.status, state, str(item.id)))
    return item


def _get_or_create_assistant(
    db: Session,
    organization: Organization,
    assets: list[AssetResult],
) -> AssistantDefinition:
    item = db.scalar(
        select(AssistantDefinition).where(
            AssistantDefinition.organization_id == organization.id,
            AssistantDefinition.ownership_scope == "organization",
            AssistantDefinition.assistant_key == "reference-assistant",
            AssistantDefinition.assistant_version == "1.0",
        )
    )
    if item is None:
        item = AssistantDefinition(
            organization_id=organization.id,
            ownership_scope="organization",
            data_origin="reference",
            assistant_key="reference-assistant",
            assistant_name="Reference Assistant",
            assistant_status="prepared",
            assistant_version="1.0",
            assistant_type="platform_assistant",
            description="Generic assistant definition for the reference tenant.",
            default_search_mode="enterprise_search",
            allowed_runtime_domains=["enterprise_search"],
            guardrail_profile={"guardrail_key": "reference-guardrail"},
            runtime_metadata=REFERENCE_MARKER.copy(),
        )
        db.add(item)
        _flush(db)
        state = "created"
    else:
        state = "reused"
        item.organization_id = organization.id
        item.ownership_scope = "organization"
        item.data_origin = "reference"
        item.assistant_status = "prepared" if item.assistant_status == "draft" else item.assistant_status
        item.runtime_metadata = _merge_marker(item.runtime_metadata)
        db.add(item)
        _flush(db)
    assets.append(
        AssetResult("ai", "assistant", item.assistant_key, item.assistant_status, state, str(item.assistant_id))
    )
    return item


def _get_or_create_knowledge_source(
    db: Session,
    organization: Organization,
    collection: Collection,
    assets: list[AssetResult],
) -> KnowledgeSource:
    item = db.scalar(
        select(KnowledgeSource).where(
            KnowledgeSource.organization_id == organization.id,
            KnowledgeSource.collection_id == collection.id,
            KnowledgeSource.source_type == "collection",
            KnowledgeSource.source_id == str(collection.id),
        )
    )
    if item is None:
        item = KnowledgeSource(
            organization_id=organization.id,
            agent_id=None,
            collection_id=collection.id,
            source_type="collection",
            source_id=str(collection.id),
            config=_merge_marker({"source_key": collection.code}),
            status="active",
        )
        db.add(item)
        _flush(db)
        state = "created"
    else:
        state = "reused"
        item.config = _merge_marker(item.config)
        item.status = "active"
        db.add(item)
        _flush(db)
    assets.append(
        AssetResult("knowledge", "knowledge_source", f"collection:{collection.code}", item.status, state, str(item.id))
    )
    return item


def _provision_reference_documents(
    db: Session,
    *,
    organization: Organization,
    collection: Collection,
    document_type: DocumentType,
    metadata_template: MetadataTemplate,
    retention_policy: RetentionPolicy,
    classification_rule: ClassificationRule,
    requested_by: str | None,
    assets: list[AssetResult],
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for document in REFERENCE_DOCUMENTS:
        logical_key = document["logical_key"]
        external_reference = f"reference-tenant:{logical_key}"
        existing_record = _reference_document_record(db, organization.id, logical_key)
        payload = DocumentLifecycleOrchestrateRequest(
            registration=DocumentRegistrationRequest(
                organization_id=organization.id,
                title=document["title"],
                source_type="reference_tenant",
                document_type_id=document_type.id,
                metadata_template_id=metadata_template.id,
                classification_rule_id=classification_rule.id,
                retention_policy_id=retention_policy.id,
                collection_id=collection.id,
                external_reference=external_reference,
                description=document["description"],
                source_ref={"source": "reference_tenant", "logical_key": logical_key},
                metadata={
                    **REFERENCE_MARKER,
                    "logical_key": logical_key,
                    "reference_content": True,
                },
                classification={"classification": "reference"},
                requested_by=requested_by or "reference-tenant",
            ),
            version_label="1.0",
            file_name=document["file_name"],
            content_type="text/plain",
            content_text=document["content"],
            storage_provider={"provider": "filesystem"},
            chunker_config={"strategy": "paragraph", "reference_tenant": True},
            publication_config={"reference_tenant": True, "logical_key": logical_key},
            search_query=document["search_query"],
            search_config={"reference_tenant": True},
            top_k=10,
            requested_by=requested_by or "reference-tenant",
            idempotency_key=f"reference-tenant:{logical_key}:lifecycle",
            lifecycle_metadata={
                **REFERENCE_MARKER,
                "logical_key": logical_key,
                "reference_content": True,
            },
        )
        result = build_document_lifecycle_orchestration(
            db,
            payload=payload,
            actor_permissions=frozenset(
                {
                    "documents:read",
                    "documents:administer",
                    "reference_tenant:read",
                }
            ),
        )
        results.append({"logical_key": logical_key, **result})
        record_id = result.get("document_record_id")
        version_id = result.get("document_version_id")
        artifact_id = result.get("artifact_id")
        created_or_reused = "reused" if existing_record is not None else "created"
        if record_id:
            assets.append(
                AssetResult(
                    "documents",
                    "reference_document",
                    document["title"],
                    "ready" if result.get("storage_verified") else "blocked",
                    created_or_reused,
                    str(record_id),
                    logical_key=f"documents:reference_document:{logical_key}",
                    readiness="ready" if result.get("knowledge_indexed") else "blocked",
                    dependencies=["document_type", "knowledge_collection", "document_lifecycle"],
                    blocking_issues=result.get("blocking_issues") or [],
                )
            )
        if version_id:
            assets.append(
                AssetResult(
                    "documents",
                    "document_version",
                    f"{logical_key}:1.0",
                    "ready" if result.get("storage_verified") else "blocked",
                    created_or_reused,
                    str(version_id),
                    logical_key=f"documents:document_version:{logical_key}:1.0",
                    readiness="ready" if result.get("storage_verified") else "blocked",
                    dependencies=["reference_document"],
                    blocking_issues=result.get("blocking_issues") or [],
                )
            )
        if artifact_id:
            assets.append(
                AssetResult(
                    "documents",
                    "artifact",
                    f"{logical_key}:binary",
                    "ready" if result.get("storage_verified") else "blocked",
                    created_or_reused,
                    str(artifact_id),
                    logical_key=f"documents:artifact:{logical_key}",
                    readiness="ready" if result.get("storage_verified") else "blocked",
                    dependencies=["document_version", "storage_execution"],
                    blocking_issues=result.get("blocking_issues") or [],
                )
            )
    return results


def _pending_capabilities() -> list[dict[str, Any]]:
    return []


def _reference_tenant_warnings() -> list[dict[str, Any]]:
    return []


def _pending_asset_results(db: Session) -> list[AssetResult]:
    return [
        AssetResult(
            domain="ai",
            asset_type="model",
            logical_name="reference-model-configuration",
            status="skipped",
            created_or_reused="skipped",
            asset_id=None,
            details={"reason": "governed_provider_configuration_not_required_for_reference_baseline"},
            logical_key="ai:model:reference-model-configuration",
            readiness="skipped",
            dependencies=[],
            blocking_issues=[],
            pending_reason=(
                "model table exists, but creating a runnable model without governed provider configuration "
                "would create a misleading baseline"
            ),
        ),
    ]


def _empty_inventory() -> dict[str, list[dict[str, Any]]]:
    return {
        "core": [],
        "security": [],
        "documents": [],
        "knowledge": [],
        "ai": [],
        "search": [],
        "chat": [],
        "feedback": [],
        "audit": [],
    }


def _inventory_from_assets(assets: list[AssetResult]) -> dict[str, list[dict[str, Any]]]:
    inventory = _empty_inventory()
    for asset in assets:
        inventory.setdefault(asset.domain, []).append(asset.to_dict())
    return inventory


def reconcile_reference_tenant_permissions(
    db: Session,
    *,
    requested_by: str | None = None,
) -> dict[str, Any]:
    """Additively reconcile the persisted canonical role-permission catalog."""
    db.execute(text("SELECT pg_advisory_xact_lock(:lock_key)"), {"lock_key": 7_241_003})
    organization = _reference_organization(db)
    if organization is None or organization.status != "active":
        raise ValueError("canonical reference organization is not provisioned or active")

    roles = {
        role.code: role
        for role in db.scalars(
            select(Role).where(
                Role.organization_id == organization.id,
                Role.code.in_(tuple(item[0] for item in REFERENCE_ROLES)),
            )
        ).all()
    }
    missing_roles = sorted(code for code, _, _ in REFERENCE_ROLES if code not in roles)
    if missing_roles:
        raise ValueError("canonical reference roles are not fully provisioned")

    role_catalogs = [
        (roles[REFERENCE_ROLES[0][0]], REFERENCE_PERMISSIONS),
        (roles[REFERENCE_ROLES[1][0]], REFERENCE_REVIEWER_PERMISSIONS),
    ]
    assets: list[AssetResult] = []
    result = _reconcile_role_permission_catalog(
        db,
        role_catalogs=role_catalogs,
        assets=assets,
    )
    db.add(
        AuditEvent(
            organization_id=organization.id,
            actor_type="administrative_cli",
            actor_id=requested_by,
            resource_type="role_permission_catalog",
            resource_id=str(organization.id),
            summary="Canonical organization role-permission catalog reconciled.",
            metadata_json={
                **result,
                "idempotent": True,
                "permission_count": len(REFERENCE_PERMISSIONS),
            },
        )
    )
    db.commit()
    return {
        **result,
        "roles_reconciled": len(role_catalogs),
        "permission_count": len(REFERENCE_PERMISSIONS),
        "idempotent": True,
    }


def provision_reference_tenant(db: Session, requested_by: str | None = None) -> dict[str, Any]:
    assets: list[AssetResult] = []
    blocking_issues: list[dict[str, Any]] = []
    try:
        organization = _get_or_create_organization(db, assets)
        _get_or_create_organization_node(db, organization, assets)

        roles = [
            _get_or_create_role(db, organization, code, name, description, assets)
            for code, name, description in REFERENCE_ROLES
        ]
        _get_or_create_policy(db, organization, assets)
        _reconcile_role_permission_catalog(
            db,
            role_catalogs=[
                (roles[0], REFERENCE_PERMISSIONS),
                (roles[1], REFERENCE_REVIEWER_PERMISSIONS),
            ],
            assets=assets,
        )
        _get_or_create_role_assignment(db, organization, roles[0], "reference-administrator", assets)
        _get_or_create_role_assignment(db, organization, roles[1], "reference-reviewer", assets)
        platform_permissions = [
            _get_or_create_permission(db, resource, action, description, assets)
            for resource, action, description in REFERENCE_PLATFORM_PERMISSIONS
        ]
        platform_role = _get_or_create_platform_role(db, *REFERENCE_PLATFORM_ROLE, assets)
        for permission in platform_permissions:
            _attach_role_permission(db, platform_role, permission, assets)
        _get_or_create_platform_role_assignment(db, platform_role, "reference-platform-operator", assets)

        collection = _get_or_create_collection(db, organization, assets)
        document_type = _get_or_create_document_type(db, organization, assets)
        metadata_template = _get_or_create_metadata_template(db, organization, document_type, assets)
        retention_policy = _get_or_create_retention_policy(db, organization, assets)
        classification_rule = _get_or_create_classification_rule(db, organization, assets)

        _get_or_create_prompt(db, organization, assets)
        _get_or_create_guardrail(db, organization, assets)
        _get_or_create_workflow(db, organization, assets)
        _get_or_create_assistant(db, organization, assets)
        _get_or_create_knowledge_source(db, organization, collection, assets)
        lifecycle_results = _provision_reference_documents(
            db,
            organization=organization,
            collection=collection,
            document_type=document_type,
            metadata_template=metadata_template,
            retention_policy=retention_policy,
            classification_rule=classification_rule,
            requested_by=requested_by,
            assets=assets,
        )
        for result in lifecycle_results:
            for issue in result.get("blocking_issues") or []:
                blocking_issues.append({**issue, "logical_key": result.get("logical_key")})

        db.commit()
    except IntegrityError as exc:
        db.rollback()
        blocking_issues.append(_issue("reference_tenant_conflict", str(getattr(exc, "orig", exc))))
    except Exception as exc:
        db.rollback()
        blocking_issues.append(_issue("reference_tenant_provision_failed", str(exc)))

    readiness = build_reference_tenant_readiness(db)
    pending = _pending_capabilities()
    warnings = list(readiness["warnings"])
    created_count = sum(1 for asset in assets if asset.created_or_reused == "created")
    reused_count = sum(1 for asset in assets if asset.created_or_reused == "reused")
    return {
        "passed": not blocking_issues and readiness["reference_tenant_ready"],
        "provisioned": not blocking_issues,
        "organization_id": readiness.get("organization_id"),
        "readiness": readiness,
        "assets": _inventory_from_assets(assets + _pending_asset_results(db)),
        "created_count": created_count,
        "reused_count": reused_count,
        "pending_count": len(pending),
        "warnings": warnings,
        "pending_capabilities": pending,
        "blocking_issues": blocking_issues,
        "postgresql_source_of_truth": True,
        "llm_used": False,
        "embeddings_used": False,
        "qdrant_used": False,
    }


def _reference_assets(db: Session, organization: Organization | None = None) -> list[AssetResult]:
    organization = organization or _reference_organization(db)
    assets: list[AssetResult] = []
    if organization is None:
        return assets

    assets.append(
        AssetResult("core", "organization", organization.slug, organization.status, "reused", str(organization.id))
    )
    for item in db.scalars(
        select(OrganizationNode)
        .where(OrganizationNode.organization_id == organization.id)
        .order_by(OrganizationNode.code.asc())
    ).all():
        assets.append(AssetResult("core", "organization_node", item.code, item.status, "reused", str(item.id)))
    for item in _reference_roles(db, organization.id):
        assets.append(AssetResult("security", "role", item.code, item.status, "reused", str(item.id)))
    for item in _reference_permissions(db):
        assets.append(
            AssetResult("security", "permission", f"{item.resource}:{item.action}", "active", "reused", str(item.id))
        )
    for item in _reference_policies(db, organization.id):
        assets.append(AssetResult("security", "policy", item.code, item.status, "reused", str(item.id)))
    for item in _reference_role_assignments(db, organization.id):
        assets.append(
            AssetResult("security", "role_assignment", item.principal_id, item.status, "reused", str(item.id))
        )
    for item in _reference_role_permissions(db, organization.id):
        assets.append(AssetResult("security", "role_permission", str(item.id), "active", "reused", str(item.id)))
    for item in _reference_collections(db, organization.id):
        assets.append(AssetResult("knowledge", "knowledge_collection", item.code, item.status, "reused", str(item.id)))
    for item in _reference_knowledge_sources(db, organization.id):
        assets.append(
            AssetResult(
                "knowledge",
                "knowledge_source",
                f"{item.source_type}:{item.source_id}",
                item.status,
                "reused",
                str(item.id),
            )
        )
    for item in _reference_document_types(db, organization.id):
        assets.append(AssetResult("documents", "document_type", item.code, item.status, "reused", str(item.id)))
    for item in _reference_metadata_templates(db, organization.id):
        assets.append(AssetResult("documents", "metadata_template", item.code, item.status, "reused", str(item.id)))
    for item in _reference_retention_policies(db, organization.id):
        assets.append(AssetResult("documents", "retention_policy", item.code, item.status, "reused", str(item.id)))
    for item in _reference_classification_rules(db, organization.id):
        assets.append(AssetResult("documents", "classification_rule", item.code, item.status, "reused", str(item.id)))
    for item in _reference_prompts(db, organization.id):
        assets.append(AssetResult("ai", "prompt", item.code, item.status, "reused", str(item.id)))
    for item in _reference_guardrails(db, organization.id):
        assets.append(AssetResult("ai", "guardrail", item.code, item.status, "reused", str(item.id)))
    for item in _reference_workflows(db, organization.id):
        assets.append(AssetResult("ai", "workflow", item.code, item.status, "reused", str(item.id)))
    assistant = _reference_assistant(db)
    if assistant is not None:
        assets.append(
            AssetResult(
                "ai",
                "assistant",
                assistant.assistant_key,
                assistant.assistant_status,
                "reused",
                str(assistant.assistant_id),
            )
        )
    for summary in _reference_document_summaries(db, organization.id):
        logical_key = summary["logical_key"]
        assets.append(
            AssetResult(
                "documents",
                "reference_document",
                summary["title"],
                "ready" if summary["enterprise_search_ready"] else "blocked",
                "reused",
                summary.get("document_record_id"),
                logical_key=f"documents:reference_document:{logical_key}",
                readiness="ready" if summary["enterprise_search_ready"] else "blocked",
                dependencies=["document_lifecycle", "knowledge_collection"],
                blocking_issues=[]
                if summary["enterprise_search_ready"]
                else [
                    _issue(
                        "reference_document_not_searchable", "Reference document is not indexed for enterprise search."
                    )
                ],
            )
        )
        if summary.get("document_version_id"):
            assets.append(
                AssetResult(
                    "documents",
                    "document_version",
                    f"{logical_key}:latest",
                    "ready" if summary["storage_verified"] else "blocked",
                    "reused",
                    summary.get("document_version_id"),
                    logical_key=f"documents:document_version:{logical_key}",
                    readiness="ready" if summary["storage_verified"] else "blocked",
                    dependencies=["reference_document", "storage_execution"],
                )
            )
        if summary.get("artifact_id"):
            assets.append(
                AssetResult(
                    "documents",
                    "artifact",
                    f"{logical_key}:artifact",
                    "ready" if summary["storage_verified"] else "blocked",
                    "reused",
                    summary.get("artifact_id"),
                    logical_key=f"documents:artifact:{logical_key}",
                    readiness="ready" if summary["storage_verified"] else "blocked",
                    dependencies=["document_version", "storage_execution"],
                )
            )
        assets.append(
            AssetResult(
                "knowledge",
                "knowledge_index_entry",
                f"{logical_key}:knowledge-index",
                "ready" if summary["knowledge_indexed"] else "blocked",
                "reused",
                summary.get("knowledge_document_id"),
                logical_key=f"knowledge:index:{logical_key}",
                readiness="ready" if summary["knowledge_indexed"] else "blocked",
                dependencies=["knowledge_publication", "postgresql_knowledge_index"],
            )
        )
    search_ready = _reference_search_ready(db, organization.id)
    chat_ready = _reference_chat_ready(db, organization.id)
    assets.append(
        AssetResult(
            "search",
            "enterprise_search_readiness",
            "reference-enterprise-search",
            "ready" if search_ready else "blocked",
            "reused",
            None,
            logical_key="search:enterprise_search_readiness:reference",
            readiness="ready" if search_ready else "blocked",
            dependencies=["reference_documents", "postgresql_knowledge_index"],
        )
    )
    assets.append(
        AssetResult(
            "chat",
            "chat_readiness",
            "reference-chat",
            "ready" if chat_ready else "blocked",
            "reused",
            None,
            logical_key="chat:chat_readiness:reference",
            readiness="ready" if chat_ready else "blocked",
            dependencies=["assistant", "knowledge_source", "enterprise_search_readiness"],
        )
    )
    assets.append(AssetResult("feedback", "feedback_capability", "feedback-audit-ux", "available", "reused", None))
    assets.append(AssetResult("audit", "audit_capability", "audit-events", "available", "reused", None))
    assets.extend(_pending_asset_results(db))
    return assets


def build_reference_tenant_assets(db: Session) -> dict[str, list[dict[str, Any]]]:
    return _inventory_from_assets(_reference_assets(db))


def build_reference_tenant_status(db: Session) -> dict[str, Any]:
    organization = _reference_organization(db)
    organization_id = organization.id if organization else None
    readiness = build_reference_tenant_readiness(db)
    reference_documents = _reference_document_summaries(db, organization_id) if organization_id else []
    if organization_id is None:
        return {
            "organization": None,
            "organization_nodes": [],
            "roles": [],
            "permissions": _permissions_to_dicts(_reference_permissions(db)),
            "policies": [],
            "role_assignments": [],
            "collections": [],
            "knowledge_sources": [],
            "document_types": [],
            "metadata_templates": [],
            "retention_policies": [],
            "classification_rules": [],
            "assistants": [_assistant_to_dict(item) for item in [_reference_assistant(db)] if item is not None],
            "prompts": [],
            "models": [],
            "guardrails": [],
            "workflows": [],
            "reference_documents": [],
            "document_lifecycle_results": [],
            "knowledge_publication_results": [],
            "search_readiness": {"ready": False, "reason": "reference_organization_missing"},
            "chat_readiness": {"ready": False, "reason": "reference_organization_missing"},
            "readiness_summary": readiness,
            "pending_capabilities": _pending_capabilities(),
        }
    return {
        "organization": _organization_to_dict(organization),
        "organization_nodes": [
            _simple_model_dict(item, ("organization_id", "parent_node_id", "node_type", "code", "name", "status"))
            for item in db.scalars(
                select(OrganizationNode).where(OrganizationNode.organization_id == organization_id)
            ).all()
        ],
        "roles": [
            _simple_model_dict(item, ("organization_id", "code", "name", "status", "config"))
            for item in _reference_roles(db, organization_id)
        ],
        "permissions": _permissions_to_dicts(_reference_permissions(db)),
        "policies": [
            _simple_model_dict(item, ("organization_id", "code", "name", "effect", "rules", "status"))
            for item in _reference_policies(db, organization_id)
        ],
        "role_assignments": [
            _simple_model_dict(
                item,
                ("organization_id", "role_id", "principal_type", "principal_id", "scope_type", "scope_id", "status"),
            )
            for item in _reference_role_assignments(db, organization_id)
        ],
        "collections": [
            _simple_model_dict(item, ("organization_id", "code", "name", "description", "config", "status"))
            for item in _reference_collections(db, organization_id)
        ],
        "knowledge_sources": [
            _simple_model_dict(
                item, ("organization_id", "agent_id", "collection_id", "source_type", "source_id", "config", "status")
            )
            for item in _reference_knowledge_sources(db, organization_id)
        ],
        "document_types": [
            _simple_model_dict(item, ("organization_id", "code", "name", "description", "version", "config", "status"))
            for item in _reference_document_types(db, organization_id)
        ],
        "metadata_templates": [
            _simple_model_dict(
                item, ("organization_id", "document_type_id", "code", "name", "schema_definition", "status")
            )
            for item in _reference_metadata_templates(db, organization_id)
        ],
        "retention_policies": [
            _simple_model_dict(item, ("organization_id", "code", "name", "rules", "status"))
            for item in _reference_retention_policies(db, organization_id)
        ],
        "classification_rules": [
            _simple_model_dict(item, ("organization_id", "code", "name", "rules", "status"))
            for item in _reference_classification_rules(db, organization_id)
        ],
        "assistants": [_assistant_to_dict(item) for item in [_reference_assistant(db)] if item is not None],
        "prompts": [
            _simple_model_dict(item, ("organization_id", "code", "name", "status", "enabled"))
            for item in _reference_prompts(db, organization_id)
        ],
        "models": [
            _simple_model_dict(item, ("organization_id", "code", "name", "provider", "status", "enabled"))
            for item in _reference_models(db, organization_id)
        ],
        "guardrails": [
            _simple_model_dict(item, ("organization_id", "code", "name", "status", "enabled"))
            for item in _reference_guardrails(db, organization_id)
        ],
        "workflows": [
            _simple_model_dict(item, ("organization_id", "code", "name", "status"))
            for item in _reference_workflows(db, organization_id)
        ],
        "reference_documents": reference_documents,
        "document_lifecycle_results": [
            {
                "logical_key": item["logical_key"],
                "document_record_id": item["document_record_id"],
                "document_version_id": item["document_version_id"],
                "artifact_id": item["artifact_id"],
                "storage_verified": item["storage_verified"],
                "storage_reused": item["storage_reused"],
                "storage_reuse_status_complete": item["storage_reuse_status_complete"],
                "processing_handoff_ready": item["processing_handoff_ready"],
                "processing_handoff_blocking_issues": item["processing_handoff_blocking_issues"],
                "processing_completed": item["processing_completed"],
                "chunks_created": item["chunks_created"],
                "knowledge_published": item["knowledge_published"],
                "knowledge_indexed": item["knowledge_indexed"],
                "knowledge_document_id": item["knowledge_document_id"],
                "knowledge_document_ids": item["knowledge_document_ids"],
                "knowledge_chunk_count": item["knowledge_chunk_count"],
                "knowledge_index_status": item["knowledge_index_status"],
                "knowledge_index_blocking_issues": item["knowledge_index_blocking_issues"],
                "knowledge_index_warnings": item["knowledge_index_warnings"],
                "search_result_count": item["search_result_count"],
                "search_index_contract_inconsistent": item["search_index_contract_inconsistent"],
                "enterprise_search_ready": item["enterprise_search_ready"],
                "chat_ready": item["chat_ready"],
            }
            for item in reference_documents
        ],
        "knowledge_publication_results": [
            {
                "logical_key": item["logical_key"],
                "knowledge_document_id": item["knowledge_document_id"],
                "knowledge_document_ids": item["knowledge_document_ids"],
                "knowledge_chunk_count": item["knowledge_chunk_count"],
                "knowledge_index_status": item["knowledge_index_status"],
                "knowledge_index_blocking_issues": item["knowledge_index_blocking_issues"],
                "knowledge_index_warnings": item["knowledge_index_warnings"],
                "knowledge_indexed": item["knowledge_indexed"],
            }
            for item in reference_documents
        ],
        "search_readiness": {
            "ready": readiness["search_ready"],
            "reference_documents_count": len(reference_documents),
            "indexed_documents_count": sum(1 for item in reference_documents if item["knowledge_indexed"]),
        },
        "chat_readiness": {
            "ready": readiness["chat_ready"],
            "assistant_ready": readiness["assistant_ready"],
            "knowledge_source_ready": readiness["knowledge_source_ready"],
            "search_ready": readiness["search_ready"],
        },
        "readiness_summary": readiness,
        "pending_capabilities": _pending_capabilities(),
    }


def build_reference_tenant_readiness(db: Session) -> dict[str, Any]:
    organization = _reference_organization(db)
    organization_id = organization.id if organization else None
    organization_ready = bool(organization and organization.status == "active")
    node_ready = bool(
        organization_id
        and _count(
            db, select(func.count(OrganizationNode.id)).where(OrganizationNode.organization_id == organization_id)
        )
        > 0
    )
    required_administrator_permissions = {f"{resource}:{action}" for resource, action, _ in REFERENCE_PERMISSIONS}
    administrator_permissions = (
        _reference_role_permission_keys(db, organization_id, role_code="reference-administrator")
        if organization_id
        else set()
    )
    security_ready = bool(
        organization_id
        and len(_reference_roles(db, organization_id)) >= len(REFERENCE_ROLES)
        and len(_reference_permissions(db)) >= len(REFERENCE_PERMISSIONS)
        and len(_reference_policies(db, organization_id)) >= 1
        and len(_reference_role_assignments(db, organization_id)) >= len(REFERENCE_ROLES)
        and len(_reference_role_permissions(db, organization_id)) >= 1
        and required_administrator_permissions.issubset(administrator_permissions)
    )
    knowledge_config_ready = bool(organization_id and len(_reference_collections(db, organization_id)) >= 1)
    documents_config_ready = bool(
        organization_id
        and len(_reference_document_types(db, organization_id)) >= 1
        and len(_reference_metadata_templates(db, organization_id)) >= 1
        and len(_reference_retention_policies(db, organization_id)) >= 1
        and len(_reference_classification_rules(db, organization_id)) >= 1
    )
    assistant_ready = _reference_assistant(db) is not None
    knowledge_source_ready = bool(organization_id and len(_reference_knowledge_sources(db, organization_id)) >= 1)
    feedback_ready = True
    audit_ready = True
    reference_documents = _reference_document_summaries(db, organization_id) if organization_id else []
    search_index_contract_inconsistent = any(
        item.get("search_index_contract_inconsistent") for item in reference_documents
    )
    reference_content_ready = len(reference_documents) >= len(REFERENCE_DOCUMENTS) and all(
        item["storage_verified"] and item["knowledge_indexed"] and item["enterprise_search_ready"]
        for item in reference_documents
    )
    knowledge_ready = bool(knowledge_config_ready and reference_content_ready)
    documents_ready = bool(documents_config_ready and reference_content_ready)
    search_ready = bool(organization_id and reference_content_ready and _reference_search_ready(db, organization_id))
    chat_ready = bool(assistant_ready and knowledge_source_ready and search_ready)
    warnings: list[dict[str, Any]] = []
    blocking_issues: list[dict[str, Any]] = []
    pending = _pending_capabilities()
    if organization_ready and not node_ready:
        warnings.append(
            _issue("organization_node_pending", "Reference organization exists but no organization node is configured.")
        )
    if not organization_ready:
        blocking_issues.append(_issue("organization_missing", "Reference organization is not provisioned."))
    if not security_ready:
        blocking_issues.append(_issue("security_missing", "Reference security configuration is incomplete."))
    missing_administrator_permissions = sorted(required_administrator_permissions - administrator_permissions)
    if missing_administrator_permissions:
        blocking_issues.append(
            _issue(
                "reference_administrator_permissions_missing",
                "The canonical organization administrator is missing required explicit product permissions; "
                "run idempotent reference access reconciliation.",
            )
        )
    if not knowledge_config_ready:
        blocking_issues.append(_issue("knowledge_missing", "Reference knowledge collection is not provisioned."))
    if not documents_config_ready:
        blocking_issues.append(_issue("documents_missing", "Reference document configuration is incomplete."))
    if not reference_content_ready:
        blocking_issues.append(
            _issue("reference_content_not_ready", "Reference content is not fully stored and indexed.")
        )
    if search_index_contract_inconsistent:
        blocking_issues.append(
            _issue(
                "search_index_contract_inconsistent",
                "Enterprise Search readiness cannot pass while PostgreSQL Knowledge Index records are missing.",
            )
        )
    if not search_ready:
        blocking_issues.append(
            _issue("search_not_ready", "Reference content is not visible through Enterprise Search.")
        )
    if not chat_ready:
        blocking_issues.append(
            _issue("chat_not_ready", "Reference assistant is not ready with searchable governed content.")
        )
    warnings.extend(_reference_tenant_warnings())
    reference_tenant_ready = (
        organization_ready
        and security_ready
        and knowledge_ready
        and documents_ready
        and assistant_ready
        and knowledge_source_ready
        and feedback_ready
        and audit_ready
        and search_ready
        and chat_ready
    )
    domain_results = {
        "core": _domain_result(
            "ready" if organization_ready and node_ready else ("blocked" if not organization_ready else "pending"),
            organization_ready and node_ready,
        ),
        "security": _domain_result("ready" if security_ready else "blocked", security_ready),
        "documents": _domain_result(
            "ready" if documents_ready and reference_content_ready else "blocked",
            documents_ready and reference_content_ready,
        ),
        "knowledge": _domain_result(
            "ready" if knowledge_ready and knowledge_source_ready and reference_content_ready else "blocked",
            knowledge_ready and knowledge_source_ready and reference_content_ready,
        ),
        "ai": _domain_result("ready" if assistant_ready else "blocked", assistant_ready),
        "search": _domain_result(
            "ready" if search_ready else "blocked",
            search_ready,
            dependencies=["reference_content", "knowledge_publication", "postgresql_fts"],
        ),
        "chat": _domain_result(
            "ready" if chat_ready else "blocked",
            chat_ready,
            dependencies=["assistant", "knowledge_source", "enterprise_search_index"],
        ),
        "feedback": _domain_result("ready", feedback_ready),
        "audit": _domain_result("ready", audit_ready),
    }
    payload = {
        "reference_tenant_ready": reference_tenant_ready,
        "organization_ready": organization_ready,
        "security_ready": security_ready,
        "knowledge_ready": knowledge_ready,
        "documents_ready": documents_ready,
        "assistant_ready": assistant_ready,
        "knowledge_source_ready": knowledge_source_ready,
        "feedback_ready": feedback_ready,
        "audit_ready": audit_ready,
        "search_ready": search_ready,
        "chat_ready": chat_ready,
        "reference_content_provisioned": reference_content_ready,
        "reference_documents_count": len(reference_documents),
        "knowledge_indexed": all(item["knowledge_indexed"] for item in reference_documents)
        if reference_documents
        else False,
        "enterprise_search_ready": search_ready,
        "search_index_contract_inconsistent": search_index_contract_inconsistent,
        "domain_results": domain_results,
        "postgresql_source_of_truth": True,
        "llm_used": False,
        "embeddings_used": False,
        "qdrant_used": False,
        "warnings": warnings,
        "pending_capabilities": pending,
        "blocking_issues": blocking_issues,
    }
    if organization_id is not None:
        payload["organization_id"] = organization_id
    return payload


def validate_reference_tenant(db: Session) -> dict[str, Any]:
    readiness = build_reference_tenant_readiness(db)
    required_flags = (
        "organization_ready",
        "security_ready",
        "knowledge_ready",
        "documents_ready",
        "assistant_ready",
        "knowledge_source_ready",
        "feedback_ready",
        "audit_ready",
        "reference_content_provisioned",
        "knowledge_indexed",
        "search_ready",
        "chat_ready",
    )
    missing = [key for key in required_flags if not readiness.get(key)]
    duplicate_risks = _duplicate_risks(db)
    product_baseline_ready = not missing and not duplicate_risks
    return {
        "passed": product_baseline_ready,
        "readiness": readiness,
        "domain_results": readiness["domain_results"],
        "missing_required_assets": missing,
        "missing_assets": missing,
        "duplicate_risks": duplicate_risks,
        "product_baseline_ready": product_baseline_ready,
        "warnings": readiness["warnings"],
        "pending_capabilities": readiness["pending_capabilities"],
        "blocking_issues": readiness["blocking_issues"],
        "postgresql_source_of_truth": True,
        "llm_used": False,
        "embeddings_used": False,
        "qdrant_used": False,
    }


def _domain_result(
    status: str,
    ready: bool,
    *,
    pending_reason: str | None = None,
    dependencies: list[str] | None = None,
    blocking_issues: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "ready": ready,
        "pending": status == "pending",
        "blocked": status == "blocked",
        "skipped": status == "skipped",
        "dependencies": dependencies or [],
        "pending_reason": pending_reason,
        "blocking_issues": blocking_issues or [],
    }


def _reference_document_record(db: Session, organization_id: uuid.UUID, logical_key: str) -> DocumentRecord | None:
    return db.scalar(
        select(DocumentRecord).where(
            DocumentRecord.organization_id == organization_id,
            DocumentRecord.external_reference == f"reference-tenant:{logical_key}",
        )
    )


def _latest_document_version(db: Session, record_id: uuid.UUID) -> DocumentVersion | None:
    return db.scalar(
        select(DocumentVersion)
        .where(DocumentVersion.document_record_id == record_id)
        .order_by(DocumentVersion.version_number.desc(), DocumentVersion.created_at.desc())
        .limit(1)
    )


def _latest_artifact(db: Session, version_id: uuid.UUID | None) -> Artifact | None:
    if version_id is None:
        return None
    return db.scalar(
        select(Artifact)
        .where(Artifact.document_version_id == version_id)
        .order_by(Artifact.created_at.desc(), Artifact.id.asc())
        .limit(1)
    )


def _knowledge_documents_for_reference(
    db: Session,
    *,
    record_id: uuid.UUID,
    version_id: uuid.UUID | None,
    artifact_id: uuid.UUID | None,
    publication_id: str | None,
) -> list[KnowledgeDocument]:
    filters = [KnowledgeDocument.document_record_id == str(record_id)]
    if version_id is not None:
        filters.append(KnowledgeDocument.document_version_id == str(version_id))
    if artifact_id is not None:
        filters.append(KnowledgeDocument.artifact_id == str(artifact_id))
    if publication_id:
        filters.append(KnowledgeDocument.publication_id == str(publication_id))
    return list(
        db.scalars(
            select(KnowledgeDocument)
            .where(
                or_(*filters),
                KnowledgeDocument.status.in_(("indexed", "ready")),
            )
            .order_by(KnowledgeDocument.created_at.desc(), KnowledgeDocument.id.asc())
        ).all()
    )


def _knowledge_chunk_count(db: Session, knowledge_document_ids: list[uuid.UUID]) -> int:
    if not knowledge_document_ids:
        return 0
    return _count(
        db,
        select(func.count(KnowledgeChunk.id)).where(
            KnowledgeChunk.knowledge_document_id.in_(knowledge_document_ids),
            KnowledgeChunk.status.in_(("indexed", "ready")),
        ),
    )


def _reference_lifecycle_summary(version: DocumentVersion | None) -> dict[str, Any]:
    snapshot = dict(version.source_snapshot or {}) if version is not None else {}
    summary = snapshot.get("reference_tenant_lifecycle_summary")
    return summary if isinstance(summary, dict) else snapshot


def _reference_search_result_count(lifecycle_summary: dict[str, Any]) -> int:
    value = lifecycle_summary.get("search_result_count")
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _reference_document_summaries(db: Session, organization_id: uuid.UUID) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    collection = db.scalar(
        select(Collection).where(
            Collection.organization_id == organization_id, Collection.code == "reference-knowledge"
        )
    )
    for document in REFERENCE_DOCUMENTS:
        logical_key = document["logical_key"]
        record = _reference_document_record(db, organization_id, logical_key)
        if record is None:
            continue
        version = _latest_document_version(db, record.id) if record is not None else None
        artifact = _latest_artifact(db, version.id) if version is not None else None
        lifecycle_snapshot = dict(version.source_snapshot or {}) if version is not None else {}
        lifecycle_summary = _reference_lifecycle_summary(version)
        publication_id = lifecycle_summary.get("publication_id") or lifecycle_snapshot.get("publication_id")
        knowledge_documents = (
            _knowledge_documents_for_reference(
                db,
                record_id=record.id,
                version_id=version.id if version is not None else None,
                artifact_id=artifact.id if artifact is not None else None,
                publication_id=str(publication_id) if publication_id else None,
            )
            if record is not None
            else []
        )
        knowledge_document_ids = [item.id for item in knowledge_documents]
        knowledge_index_count = _knowledge_chunk_count(db, knowledge_document_ids)
        storage_verified = bool(
            version
            and version.object_store_key
            and version.checksum_sha256
            and version.size_bytes is not None
            and (version.source_snapshot or {}).get("storage_verified") is True
        )
        search_result_count = _reference_search_result_count(lifecycle_summary)
        knowledge_index_status = "indexed" if knowledge_documents and knowledge_index_count > 0 else "missing"
        knowledge_indexed = knowledge_index_status == "indexed"
        search_index_contract_inconsistent = bool(search_result_count > 0 and not knowledge_indexed)
        enterprise_search_ready = bool(
            knowledge_indexed and search_result_count > 0 and not search_index_contract_inconsistent
        )
        knowledge_index_blocking_issues = list(lifecycle_summary.get("knowledge_index_blocking_issues") or [])
        if search_index_contract_inconsistent:
            knowledge_index_blocking_issues.append(
                _issue(
                    "search_index_contract_inconsistent",
                    "Enterprise Search returned results but PostgreSQL Knowledge Index records were not found "
                    "for the reference document.",
                    component="reference_tenant",
                )
            )
        summaries.append(
            {
                "logical_key": logical_key,
                "title": document["title"],
                "document_record_id": str(record.id) if record is not None else None,
                "document_version_id": str(version.id) if version is not None else None,
                "artifact_id": str(artifact.id) if artifact is not None else None,
                "knowledge_document_id": str(knowledge_documents[0].id) if knowledge_documents else None,
                "knowledge_document_ids": [str(item.id) for item in knowledge_documents],
                "collection_id": str(collection.id) if collection is not None else None,
                "storage_verified": storage_verified,
                "storage_reused": bool(lifecycle_snapshot.get("storage_reused")),
                "storage_reuse_status_complete": bool(lifecycle_snapshot.get("storage_reuse_status_complete", True)),
                "processing_handoff_ready": bool(lifecycle_snapshot.get("processing_handoff_ready", True)),
                "processing_handoff_blocking_issues": lifecycle_snapshot.get("processing_handoff_blocking_issues")
                or [],
                "processing_completed": bool(lifecycle_snapshot.get("processing_ready")),
                "chunks_created": bool(lifecycle_snapshot.get("chunks_created")),
                "knowledge_published": bool(lifecycle_snapshot.get("knowledge_published")),
                "knowledge_indexed": knowledge_indexed,
                "knowledge_index_count": knowledge_index_count,
                "knowledge_chunk_count": knowledge_index_count,
                "knowledge_index_status": knowledge_index_status,
                "knowledge_index_blocking_issues": _sort_issues(knowledge_index_blocking_issues),
                "knowledge_index_warnings": _sort_issues(lifecycle_summary.get("knowledge_index_warnings") or []),
                "search_result_count": search_result_count,
                "search_index_contract_inconsistent": search_index_contract_inconsistent,
                "enterprise_search_ready": enterprise_search_ready,
                "chat_ready": enterprise_search_ready,
            }
        )
    return summaries


def _reference_search_ready(db: Session, organization_id: uuid.UUID) -> bool:
    summaries = _reference_document_summaries(db, organization_id)
    return bool(summaries) and all(item["enterprise_search_ready"] for item in summaries)


def _reference_chat_ready(db: Session, organization_id: uuid.UUID) -> bool:
    return bool(
        _reference_assistant(db)
        and _reference_knowledge_sources(db, organization_id)
        and _reference_search_ready(db, organization_id)
    )


def _count(db: Session, statement: Any) -> int:
    return int(db.scalar(statement) or 0)


def _duplicate_risks(db: Session) -> list[dict[str, Any]]:
    organization = _reference_organization(db)
    organization_id = organization.id if organization else None
    checks: list[tuple[str, str, int]] = [
        (
            "organization",
            REFERENCE_ORGANIZATION_SLUG,
            _count(db, select(func.count(Organization.id)).where(Organization.slug == REFERENCE_ORGANIZATION_SLUG)),
        ),
        (
            "assistant",
            "reference-assistant:1.0",
            _count(
                db,
                select(func.count(AssistantDefinition.assistant_id)).where(
                    AssistantDefinition.organization_id == organization_id,
                    AssistantDefinition.ownership_scope == "organization",
                    AssistantDefinition.assistant_key == "reference-assistant",
                    AssistantDefinition.assistant_version == "1.0",
                ),
            ),
        ),
    ]
    if organization_id is not None:
        collection = db.scalar(
            select(Collection).where(
                Collection.organization_id == organization_id, Collection.code == "reference-knowledge"
            )
        )
        collection_id = collection.id if collection is not None else None
        knowledge_source_id_clause = (
            KnowledgeSource.source_id == str(collection_id)
            if collection_id is not None
            else KnowledgeSource.source_id.is_(None)
        )
        checks.extend(
            [
                (
                    "role",
                    code,
                    _count(
                        db,
                        select(func.count(Role.id)).where(Role.organization_id == organization_id, Role.code == code),
                    ),
                )
                for code, _, _ in REFERENCE_ROLES
            ]
        )
        checks.extend(
            [
                (
                    "role_assignment",
                    "reference-administrator",
                    _count(
                        db,
                        select(func.count(RoleAssignment.id)).where(
                            RoleAssignment.organization_id == organization_id,
                            RoleAssignment.principal_type == "reference_principal",
                            RoleAssignment.principal_id == "reference-administrator",
                        ),
                    ),
                ),
                (
                    "role_assignment",
                    "reference-reviewer",
                    _count(
                        db,
                        select(func.count(RoleAssignment.id)).where(
                            RoleAssignment.organization_id == organization_id,
                            RoleAssignment.principal_type == "reference_principal",
                            RoleAssignment.principal_id == "reference-reviewer",
                        ),
                    ),
                ),
                (
                    "collection",
                    "reference-knowledge",
                    _count(
                        db,
                        select(func.count(Collection.id)).where(
                            Collection.organization_id == organization_id, Collection.code == "reference-knowledge"
                        ),
                    ),
                ),
                (
                    "document_type",
                    "reference-document",
                    _count(
                        db,
                        select(func.count(DocumentType.id)).where(
                            DocumentType.organization_id == organization_id, DocumentType.code == "reference-document"
                        ),
                    ),
                ),
                (
                    "knowledge_source",
                    "collection:reference-knowledge",
                    _count(
                        db,
                        select(func.count(KnowledgeSource.id)).where(
                            KnowledgeSource.organization_id == organization_id,
                            KnowledgeSource.collection_id == collection_id,
                            KnowledgeSource.source_type == "collection",
                            knowledge_source_id_clause,
                        ),
                    ),
                ),
            ]
        )
        for document in REFERENCE_DOCUMENTS:
            logical_key = document["logical_key"]
            record = _reference_document_record(db, organization_id, logical_key)
            checks.append(
                (
                    "reference_document",
                    logical_key,
                    _count(
                        db,
                        select(func.count(DocumentRecord.id)).where(
                            DocumentRecord.organization_id == organization_id,
                            DocumentRecord.external_reference == f"reference-tenant:{logical_key}",
                        ),
                    ),
                )
            )
            if record is not None:
                version_count = _count(
                    db,
                    select(func.count(DocumentVersion.id)).where(
                        DocumentVersion.document_record_id == record.id,
                    ),
                )
                artifact_count = _count(
                    db,
                    select(func.count(Artifact.id)).where(
                        Artifact.document_record_id == record.id,
                    ),
                )
                knowledge_count = _count(
                    db,
                    select(func.count(KnowledgeDocument.id)).where(
                        KnowledgeDocument.document_record_id == str(record.id),
                        KnowledgeDocument.status == "indexed",
                    ),
                )
                checks.extend(
                    [
                        ("document_version", f"{logical_key}:versions", version_count),
                        ("artifact", f"{logical_key}:artifacts", artifact_count),
                        ("knowledge_record", f"{logical_key}:knowledge", knowledge_count),
                    ]
                )
    checks.extend(
        [
            (
                "permission",
                f"{resource}:{action}",
                _count(
                    db,
                    select(func.count(Permission.id)).where(
                        Permission.resource == resource, Permission.action == action
                    ),
                ),
            )
            for resource, action, _ in REFERENCE_PERMISSIONS
        ]
    )
    return [
        {"asset_type": asset_type, "logical_key": logical_key, "count": count, "risk": "duplicate_asset"}
        for asset_type, logical_key, count in checks
        if count > 1
    ]


def _reference_permissions(db: Session) -> list[Permission]:
    clauses = [
        and_(Permission.resource == resource, Permission.action == action)
        for resource, action, _ in REFERENCE_PERMISSIONS
    ]
    if not clauses:
        return []
    return list(db.scalars(select(Permission).where(or_(*clauses))).all())


def _permissions_to_dicts(items: list[Permission]) -> list[dict[str, Any]]:
    return [
        {"id": item.id, "resource": item.resource, "action": item.action, "description": item.description}
        for item in items
    ]


def _reference_roles(db: Session, organization_id: uuid.UUID) -> list[Role]:
    return list(
        db.scalars(
            select(Role)
            .where(Role.organization_id == organization_id, Role.code.in_([item[0] for item in REFERENCE_ROLES]))
            .order_by(Role.code.asc())
        ).all()
    )


def _reference_policies(db: Session, organization_id: uuid.UUID) -> list[Policy]:
    return list(
        db.scalars(
            select(Policy).where(Policy.organization_id == organization_id, Policy.code == "reference-access")
        ).all()
    )


def _reference_role_assignments(db: Session, organization_id: uuid.UUID) -> list[RoleAssignment]:
    return list(
        db.scalars(
            select(RoleAssignment)
            .where(
                RoleAssignment.organization_id == organization_id,
                RoleAssignment.principal_type == "reference_principal",
            )
            .order_by(RoleAssignment.principal_id.asc())
        ).all()
    )


def _reference_role_permissions(db: Session, organization_id: uuid.UUID) -> list[RolePermission]:
    role_ids = [role.id for role in _reference_roles(db, organization_id)]
    if not role_ids:
        return []
    return list(
        db.scalars(
            select(RolePermission)
            .where(RolePermission.role_id.in_(role_ids))
            .order_by(RolePermission.role_id.asc(), RolePermission.permission_id.asc())
        ).all()
    )


def _reference_role_permission_keys(
    db: Session,
    organization_id: uuid.UUID,
    *,
    role_code: str,
) -> set[str]:
    rows = db.execute(
        select(Permission.resource, Permission.action)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .join(Role, Role.id == RolePermission.role_id)
        .where(Role.organization_id == organization_id, Role.code == role_code)
    ).all()
    return {f"{resource}:{action}" for resource, action in rows}


def _reference_collections(db: Session, organization_id: uuid.UUID) -> list[Collection]:
    return list(
        db.scalars(
            select(Collection).where(
                Collection.organization_id == organization_id, Collection.code == "reference-knowledge"
            )
        ).all()
    )


def _reference_knowledge_sources(db: Session, organization_id: uuid.UUID) -> list[KnowledgeSource]:
    return list(
        db.scalars(
            select(KnowledgeSource).where(
                KnowledgeSource.organization_id == organization_id,
                KnowledgeSource.source_type == "collection",
            )
        ).all()
    )


def _reference_document_types(db: Session, organization_id: uuid.UUID) -> list[DocumentType]:
    return list(
        db.scalars(
            select(DocumentType).where(
                DocumentType.organization_id == organization_id, DocumentType.code == "reference-document"
            )
        ).all()
    )


def _reference_metadata_templates(db: Session, organization_id: uuid.UUID) -> list[MetadataTemplate]:
    return list(
        db.scalars(
            select(MetadataTemplate).where(
                MetadataTemplate.organization_id == organization_id, MetadataTemplate.code == "reference-metadata"
            )
        ).all()
    )


def _reference_retention_policies(db: Session, organization_id: uuid.UUID) -> list[RetentionPolicy]:
    return list(
        db.scalars(
            select(RetentionPolicy).where(
                RetentionPolicy.organization_id == organization_id, RetentionPolicy.code == "reference-retention"
            )
        ).all()
    )


def _reference_classification_rules(db: Session, organization_id: uuid.UUID) -> list[ClassificationRule]:
    return list(
        db.scalars(
            select(ClassificationRule).where(
                ClassificationRule.organization_id == organization_id,
                ClassificationRule.code == "reference-classification",
            )
        ).all()
    )


def _reference_prompts(db: Session, organization_id: uuid.UUID) -> list[Prompt]:
    return list(
        db.scalars(
            select(Prompt).where(
                Prompt.organization_id == organization_id,
                or_(Prompt.code == "reference-assistant-prompt", Prompt.prompt_key == "reference-assistant-prompt"),
            )
        ).all()
    )


def _reference_models(db: Session, organization_id: uuid.UUID) -> list[AiModel]:
    return list(
        db.scalars(
            select(AiModel).where(AiModel.organization_id == organization_id, AiModel.code == "reference-model")
        ).all()
    )


def _reference_guardrails(db: Session, organization_id: uuid.UUID) -> list[Guardrail]:
    return list(
        db.scalars(
            select(Guardrail).where(
                Guardrail.organization_id == organization_id,
                or_(Guardrail.code == "reference-guardrail", Guardrail.guardrail_key == "reference-guardrail"),
            )
        ).all()
    )


def _reference_workflows(db: Session, organization_id: uuid.UUID) -> list[Workflow]:
    return list(
        db.scalars(
            select(Workflow).where(
                Workflow.organization_id == organization_id, Workflow.code == "reference-readiness-workflow"
            )
        ).all()
    )


def _reference_assistant(db: Session) -> AssistantDefinition | None:
    organization = _reference_organization(db)
    if organization is None:
        return None
    return db.scalar(
        select(AssistantDefinition).where(
            AssistantDefinition.organization_id == organization.id,
            AssistantDefinition.ownership_scope == "organization",
            AssistantDefinition.data_origin == "reference",
            AssistantDefinition.assistant_key == "reference-assistant",
            AssistantDefinition.assistant_version == "1.0",
        )
    )


def _assistant_to_dict(item: AssistantDefinition) -> dict[str, Any]:
    return {
        "id": item.assistant_id,
        "assistant_key": item.assistant_key,
        "assistant_name": item.assistant_name,
        "assistant_status": item.assistant_status,
        "assistant_version": item.assistant_version,
        "assistant_type": item.assistant_type,
        "default_search_mode": item.default_search_mode,
        "runtime_metadata": item.runtime_metadata,
    }
