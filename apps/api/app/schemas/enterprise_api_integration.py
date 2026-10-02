from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class EnterpriseApiIntegrationRuntimeResponse(BaseModel):
    enterprise_api_integration_runtime_schema_version: str = "1"
    runtime_name: str
    runtime_status: str
    workspace_summary: dict[str, Any] = Field(default_factory=dict)
    platform_api_inventory: dict[str, Any] = Field(default_factory=dict)
    endpoint_catalog: list[dict[str, Any]] = Field(default_factory=list)
    runtime_endpoint_catalog: list[dict[str, Any]] = Field(default_factory=list)
    api_groups: dict[str, Any] = Field(default_factory=dict)
    versioning: dict[str, Any] = Field(default_factory=dict)
    authentication_methods: dict[str, Any] = Field(default_factory=dict)
    authorization_model: dict[str, Any] = Field(default_factory=dict)
    security_scopes: dict[str, Any] = Field(default_factory=dict)
    jwt_readiness: dict[str, Any] = Field(default_factory=dict)
    service_endpoints: dict[str, Any] = Field(default_factory=dict)
    external_integrations: dict[str, Any] = Field(default_factory=dict)
    connector_integrations: dict[str, Any] = Field(default_factory=dict)
    webhook_inventory: dict[str, Any] = Field(default_factory=dict)
    event_catalog: dict[str, Any] = Field(default_factory=dict)
    integration_diagnostics: dict[str, Any] = Field(default_factory=dict)
    api_readiness: dict[str, Any] = Field(default_factory=dict)
    reference_tenant_integration_readiness: dict[str, Any] = Field(default_factory=dict)
    operational_recommendations: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[dict[str, Any]] = Field(default_factory=list)
    postgresql_source_of_truth: bool = True
    side_effects_performed: bool = False
    external_calls_performed: bool = False
    llm_used: bool = False
    qdrant_used: bool = False
