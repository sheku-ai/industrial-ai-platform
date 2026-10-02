from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ConnectorWorkspaceRuntimeResponse(BaseModel):
    connector_workspace_runtime_schema_version: str = "2"
    runtime_name: str
    runtime_status: str
    capabilities: dict[str, bool] = Field(default_factory=dict)
    credential_resolver_types: list[str] = Field(default_factory=list)
    workspace_summary: dict[str, Any] = Field(default_factory=dict)
    connector_types: list[dict[str, Any]] = Field(default_factory=list)
    connectors: list[dict[str, Any]] = Field(default_factory=list)
    connector_configurations: list[dict[str, Any]] = Field(default_factory=list)
    connector_runs: dict[str, Any] = Field(default_factory=dict)
    sync_ingestion_impact: dict[str, Any] = Field(default_factory=dict)
    audit_trace: dict[str, Any] = Field(default_factory=dict)
    diagnostics: dict[str, Any] = Field(default_factory=dict)
    postgresql_source_of_truth: bool = True
    external_calls_performed: bool = False
    llm_used: bool = False
    qdrant_used: bool = False
