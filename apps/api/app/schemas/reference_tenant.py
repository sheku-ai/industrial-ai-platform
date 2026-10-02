from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, Field


class ReferenceTenantAsset(BaseModel):
    asset_type: str
    logical_key: str | None = None
    asset_id: str | None = None
    logical_name: str
    status: str
    created_or_reused: str
    source_domain: str
    readiness: str = "ready"
    dependencies: list[str] = Field(default_factory=list)
    blocking_issues: list[dict[str, Any]] = Field(default_factory=list)
    pending_reason: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class ReferenceTenantInventory(BaseModel):
    core: list[ReferenceTenantAsset] = Field(default_factory=list)
    security: list[ReferenceTenantAsset] = Field(default_factory=list)
    documents: list[ReferenceTenantAsset] = Field(default_factory=list)
    knowledge: list[ReferenceTenantAsset] = Field(default_factory=list)
    ai: list[ReferenceTenantAsset] = Field(default_factory=list)
    search: list[ReferenceTenantAsset] = Field(default_factory=list)
    chat: list[ReferenceTenantAsset] = Field(default_factory=list)
    feedback: list[ReferenceTenantAsset] = Field(default_factory=list)
    audit: list[ReferenceTenantAsset] = Field(default_factory=list)


class ReferenceTenantReadiness(BaseModel):
    reference_tenant_ready: bool
    organization_ready: bool
    security_ready: bool
    knowledge_ready: bool
    documents_ready: bool
    assistant_ready: bool
    knowledge_source_ready: bool
    feedback_ready: bool
    audit_ready: bool
    search_ready: bool
    chat_ready: bool
    reference_content_provisioned: bool = False
    reference_documents_count: int = 0
    knowledge_indexed: bool = False
    enterprise_search_ready: bool = False
    domain_results: dict[str, dict[str, Any]] = Field(default_factory=dict)
    postgresql_source_of_truth: bool = True
    llm_used: bool = False
    embeddings_used: bool = False
    qdrant_used: bool = False
    warnings: list[dict[str, Any]] = Field(default_factory=list)
    pending_capabilities: list[dict[str, Any]] = Field(default_factory=list)
    blocking_issues: list[dict[str, Any]] = Field(default_factory=list)


class ReferenceTenantProvisionRequest(BaseModel):
    requested_by: str | None = None


class ReferenceTenantProvisionResponse(BaseModel):
    passed: bool
    provisioned: bool
    organization_id: uuid.UUID | None = None
    readiness: ReferenceTenantReadiness
    assets: ReferenceTenantInventory
    created_count: int
    reused_count: int
    pending_count: int
    warnings: list[dict[str, Any]] = Field(default_factory=list)
    pending_capabilities: list[dict[str, Any]] = Field(default_factory=list)
    blocking_issues: list[dict[str, Any]] = Field(default_factory=list)
    postgresql_source_of_truth: bool = True
    llm_used: bool = False
    embeddings_used: bool = False
    qdrant_used: bool = False


class ReferenceTenantStatus(BaseModel):
    organization: dict[str, Any] | None = None
    organization_nodes: list[dict[str, Any]] = Field(default_factory=list)
    roles: list[dict[str, Any]] = Field(default_factory=list)
    permissions: list[dict[str, Any]] = Field(default_factory=list)
    policies: list[dict[str, Any]] = Field(default_factory=list)
    role_assignments: list[dict[str, Any]] = Field(default_factory=list)
    collections: list[dict[str, Any]] = Field(default_factory=list)
    knowledge_sources: list[dict[str, Any]] = Field(default_factory=list)
    document_types: list[dict[str, Any]] = Field(default_factory=list)
    metadata_templates: list[dict[str, Any]] = Field(default_factory=list)
    retention_policies: list[dict[str, Any]] = Field(default_factory=list)
    classification_rules: list[dict[str, Any]] = Field(default_factory=list)
    assistants: list[dict[str, Any]] = Field(default_factory=list)
    prompts: list[dict[str, Any]] = Field(default_factory=list)
    models: list[dict[str, Any]] = Field(default_factory=list)
    guardrails: list[dict[str, Any]] = Field(default_factory=list)
    workflows: list[dict[str, Any]] = Field(default_factory=list)
    reference_documents: list[dict[str, Any]] = Field(default_factory=list)
    document_lifecycle_results: list[dict[str, Any]] = Field(default_factory=list)
    knowledge_publication_results: list[dict[str, Any]] = Field(default_factory=list)
    search_readiness: dict[str, Any] = Field(default_factory=dict)
    chat_readiness: dict[str, Any] = Field(default_factory=dict)
    readiness_summary: ReferenceTenantReadiness
    pending_capabilities: list[dict[str, Any]] = Field(default_factory=list)


class ReferenceTenantValidationResponse(BaseModel):
    passed: bool
    readiness: ReferenceTenantReadiness
    domain_results: dict[str, dict[str, Any]] = Field(default_factory=dict)
    missing_required_assets: list[str] = Field(default_factory=list)
    missing_assets: list[str] = Field(default_factory=list)
    duplicate_risks: list[dict[str, Any]] = Field(default_factory=list)
    product_baseline_ready: bool = False
    warnings: list[dict[str, Any]] = Field(default_factory=list)
    pending_capabilities: list[dict[str, Any]] = Field(default_factory=list)
    blocking_issues: list[dict[str, Any]] = Field(default_factory=list)
    postgresql_source_of_truth: bool = True
    llm_used: bool = False
    embeddings_used: bool = False
    qdrant_used: bool = False
