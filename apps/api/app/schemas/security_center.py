from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SecurityCenterRuntimeResponse(BaseModel):
    security_center_runtime_schema_version: str = "1"
    runtime_name: str
    runtime_status: str
    workspace_summary: dict[str, Any] = Field(default_factory=dict)
    security_readiness: dict[str, Any] = Field(default_factory=dict)
    security_acceptance: dict[str, Any] = Field(default_factory=dict)
    security_findings: list[dict[str, Any]] = Field(default_factory=list)
    security_evidence: list[dict[str, Any]] = Field(default_factory=list)
    security_policies: list[dict[str, Any]] = Field(default_factory=list)
    security_configuration: dict[str, Any] = Field(default_factory=dict)
    roles: dict[str, Any] = Field(default_factory=dict)
    permissions: dict[str, Any] = Field(default_factory=dict)
    policies: dict[str, Any] = Field(default_factory=dict)
    role_assignments: dict[str, Any] = Field(default_factory=dict)
    effective_permissions: dict[str, Any] = Field(default_factory=dict)
    scopes: dict[str, Any] = Field(default_factory=dict)
    policy_evaluation: dict[str, Any] = Field(default_factory=dict)
    access_diagnostics: dict[str, Any] = Field(default_factory=dict)
    security_audit: dict[str, Any] = Field(default_factory=dict)
    security_governance: dict[str, Any] = Field(default_factory=dict)
    reference_tenant_security: dict[str, Any] = Field(default_factory=dict)
    advanced_security_records: dict[str, Any] = Field(default_factory=dict)
    pending_capabilities: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[dict[str, Any]] = Field(default_factory=list)
    recommendations: list[dict[str, Any]] = Field(default_factory=list)
    postgresql_source_of_truth: bool = True
    side_effects_performed: bool = False
    external_calls_performed: bool = False
    llm_used: bool = False
    qdrant_used: bool = False
