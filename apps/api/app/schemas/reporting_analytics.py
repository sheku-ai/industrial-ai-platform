from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ReportingAnalyticsRuntimeResponse(BaseModel):
    reporting_analytics_runtime_schema_version: str = "1"
    runtime_name: str
    runtime_status: str
    workspace_summary: dict[str, Any] = Field(default_factory=dict)
    platform_summary: dict[str, Any] = Field(default_factory=dict)
    executive_kpis: dict[str, Any] = Field(default_factory=dict)
    document_analytics: dict[str, Any] = Field(default_factory=dict)
    knowledge_analytics: dict[str, Any] = Field(default_factory=dict)
    enterprise_search_analytics: dict[str, Any] = Field(default_factory=dict)
    assistant_analytics: dict[str, Any] = Field(default_factory=dict)
    conversation_analytics: dict[str, Any] = Field(default_factory=dict)
    workflow_analytics: dict[str, Any] = Field(default_factory=dict)
    scheduler_analytics: dict[str, Any] = Field(default_factory=dict)
    background_services_analytics: dict[str, Any] = Field(default_factory=dict)
    connector_analytics: dict[str, Any] = Field(default_factory=dict)
    security_analytics: dict[str, Any] = Field(default_factory=dict)
    governance_analytics: dict[str, Any] = Field(default_factory=dict)
    audit_analytics: dict[str, Any] = Field(default_factory=dict)
    feedback_analytics: dict[str, Any] = Field(default_factory=dict)
    reference_tenant_analytics: dict[str, Any] = Field(default_factory=dict)
    product_readiness_trends: dict[str, Any] = Field(default_factory=dict)
    runtime_health_trends: dict[str, Any] = Field(default_factory=dict)
    operational_trends: dict[str, Any] = Field(default_factory=dict)
    readiness_scores: dict[str, Any] = Field(default_factory=dict)
    diagnostics: dict[str, Any] = Field(default_factory=dict)
    recommendations: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[dict[str, Any]] = Field(default_factory=list)
    postgresql_source_of_truth: bool = True
    side_effects_performed: bool = False
    external_calls_performed: bool = False
    llm_used: bool = False
    qdrant_used: bool = False
