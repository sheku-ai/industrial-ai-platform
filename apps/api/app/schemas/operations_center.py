from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class OperationsCenterAuthorization(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    platform_operations_read: bool = Field(alias="platform.operations:read")
    platform_operations_administer: bool = Field(alias="platform.operations:administer")


class OperationsCenterRuntimeResponse(BaseModel):
    operations_center_runtime_schema_version: str = "1"
    runtime_name: str
    runtime_status: str
    authorization: OperationsCenterAuthorization
    workspace_summary: dict[str, Any] = Field(default_factory=dict)
    runtime_persistence: dict[str, Any] = Field(default_factory=dict)
    document_lifecycle_operations: dict[str, Any] = Field(default_factory=dict)
    processing_workers: dict[str, Any] = Field(default_factory=dict)
    knowledge_operations: dict[str, Any] = Field(default_factory=dict)
    enterprise_search_operations: dict[str, Any] = Field(default_factory=dict)
    assistant_operations: dict[str, Any] = Field(default_factory=dict)
    connector_operations: dict[str, Any] = Field(default_factory=dict)
    feedback_audit_operations: dict[str, Any] = Field(default_factory=dict)
    operational_readiness: dict[str, Any] = Field(default_factory=dict)
    security_readiness: dict[str, Any] = Field(default_factory=dict)
    component_summary: dict[str, Any] = Field(default_factory=dict)
    worker_summary: dict[str, Any] = Field(default_factory=dict)
    scheduler_summary: dict[str, Any] = Field(default_factory=dict)
    lease_summary: dict[str, Any] = Field(default_factory=dict)
    execution_summary: dict[str, Any] = Field(default_factory=dict)
    retry_summary: dict[str, Any] = Field(default_factory=dict)
    incident_summary: dict[str, Any] = Field(default_factory=dict)
    recent_recovery_actions: list[dict[str, Any]] = Field(default_factory=list)
    evidence_freshness: dict[str, Any] = Field(default_factory=dict)
    next_actions: list[dict[str, Any]] = Field(default_factory=list)
    diagnostics: dict[str, Any] = Field(default_factory=dict)
    postgresql_source_of_truth: bool = True
    side_effects_performed: bool = False
    llm_used: bool = False
    qdrant_used: bool = False
    external_calls_performed: bool = False
