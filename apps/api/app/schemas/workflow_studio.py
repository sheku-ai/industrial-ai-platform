from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class WorkflowStudioRuntimeResponse(BaseModel):
    workflow_studio_runtime_schema_version: str = "1"
    runtime_name: str
    runtime_status: str
    workspace_summary: dict[str, Any] = Field(default_factory=dict)
    workflow_inventory: list[dict[str, Any]] = Field(default_factory=list)
    workflow_categories: dict[str, Any] = Field(default_factory=dict)
    workflow_readiness: dict[str, Any] = Field(default_factory=dict)
    workflow_diagnostics: dict[str, Any] = Field(default_factory=dict)
    workflow_dependencies: dict[str, Any] = Field(default_factory=dict)
    workflow_evidence: dict[str, Any] = Field(default_factory=dict)
    workflow_runtime_state: dict[str, Any] = Field(default_factory=dict)
    workflow_health: dict[str, Any] = Field(default_factory=dict)
    workflow_recommendations: list[dict[str, Any]] = Field(default_factory=list)
    reference_tenant: dict[str, Any] = Field(default_factory=dict)
    pending_capabilities: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[dict[str, Any]] = Field(default_factory=list)
    postgresql_source_of_truth: bool = True
    side_effects_performed: bool = False
    external_calls_performed: bool = False
    llm_used: bool = False
    qdrant_used: bool = False
