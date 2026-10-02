from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SchedulerBackgroundServicesRuntimeResponse(BaseModel):
    scheduler_background_services_runtime_schema_version: str = "1"
    runtime_name: str
    runtime_status: str
    workspace_summary: dict[str, Any] = Field(default_factory=dict)
    scheduler_summary: dict[str, Any] = Field(default_factory=dict)
    background_services: list[dict[str, Any]] = Field(default_factory=list)
    worker_inventory: list[dict[str, Any]] = Field(default_factory=list)
    worker_health: dict[str, Any] = Field(default_factory=dict)
    worker_activity: dict[str, Any] = Field(default_factory=dict)
    lease_management: dict[str, Any] = Field(default_factory=dict)
    lease_diagnostics: dict[str, Any] = Field(default_factory=dict)
    retry_engine: dict[str, Any] = Field(default_factory=dict)
    runtime_executions: dict[str, Any] = Field(default_factory=dict)
    execution_history: dict[str, Any] = Field(default_factory=dict)
    background_pipelines: list[dict[str, Any]] = Field(default_factory=list)
    pipeline_health: dict[str, Any] = Field(default_factory=dict)
    pipeline_dependencies: dict[str, Any] = Field(default_factory=dict)
    runtime_readiness: dict[str, Any] = Field(default_factory=dict)
    operational_diagnostics: dict[str, Any] = Field(default_factory=dict)
    runtime_recommendations: list[dict[str, Any]] = Field(default_factory=list)
    reference_tenant: dict[str, Any] = Field(default_factory=dict)
    pending_capabilities: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[dict[str, Any]] = Field(default_factory=list)
    postgresql_source_of_truth: bool = True
    side_effects_performed: bool = False
    external_calls_performed: bool = False
    llm_used: bool = False
    qdrant_used: bool = False
