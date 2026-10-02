from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class DocumentWorkspaceRuntimeResponse(BaseModel):
    document_workspace_runtime_schema_version: str = "1"
    runtime_name: str
    runtime_status: str
    workspace_summary: dict[str, Any] = Field(default_factory=dict)
    document_registry: list[dict[str, Any]] = Field(default_factory=list)
    versions: list[dict[str, Any]] = Field(default_factory=list)
    upload_capabilities: dict[str, Any] = Field(default_factory=dict)
    lifecycle: dict[str, Any] = Field(default_factory=dict)
    storage: dict[str, Any] = Field(default_factory=dict)
    processing: dict[str, Any] = Field(default_factory=dict)
    chunks: dict[str, Any] = Field(default_factory=dict)
    knowledge: dict[str, Any] = Field(default_factory=dict)
    enterprise_search: dict[str, Any] = Field(default_factory=dict)
    diagnostics: dict[str, Any] = Field(default_factory=dict)
    organization_associations: dict[str, Any] = Field(default_factory=dict)
    postgresql_source_of_truth: bool = True
    llm_used: bool = False
    qdrant_used: bool = False
