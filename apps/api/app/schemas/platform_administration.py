from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class PlatformAdministrationRuntimeResponse(BaseModel):
    platform_administration_runtime_schema_version: str = "1"
    runtime_name: str
    runtime_status: str
    platform: dict[str, Any] = Field(default_factory=dict)
    organizations: dict[str, Any] = Field(default_factory=dict)
    security: dict[str, Any] = Field(default_factory=dict)
    documents: dict[str, Any] = Field(default_factory=dict)
    knowledge: dict[str, Any] = Field(default_factory=dict)
    enterprise_search: dict[str, Any] = Field(default_factory=dict)
    assistants: dict[str, Any] = Field(default_factory=dict)
    reference_tenant: dict[str, Any] = Field(default_factory=dict)
    health_summary: dict[str, Any] = Field(default_factory=dict)
    data_scope: dict[str, Any] = Field(default_factory=dict)
    warnings: list[dict[str, Any]] = Field(default_factory=list)
    blocking_issues: list[dict[str, Any]] = Field(default_factory=list)
    postgresql_source_of_truth: bool = True
    llm_used: bool = False
    embeddings_used: bool = False
    qdrant_used: bool = False
