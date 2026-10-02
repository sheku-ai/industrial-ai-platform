from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class PlatformOperationsRuntimeResponse(BaseModel):
    platform_operations_runtime_schema_version: str = "1"
    runtime_name: str
    runtime_status: str
    platform_runtime: dict[str, Any] = Field(default_factory=dict)
    documents: dict[str, Any] = Field(default_factory=dict)
    knowledge: dict[str, Any] = Field(default_factory=dict)
    enterprise_search: dict[str, Any] = Field(default_factory=dict)
    assistant: dict[str, Any] = Field(default_factory=dict)
    runtime: dict[str, Any] = Field(default_factory=dict)
    feedback: dict[str, Any] = Field(default_factory=dict)
    reference_tenant: dict[str, Any] = Field(default_factory=dict)
    operational_readiness: dict[str, Any] = Field(default_factory=dict)
    warnings: list[dict[str, Any]] = Field(default_factory=list)
    blocking_issues: list[dict[str, Any]] = Field(default_factory=list)
    postgresql_source_of_truth: bool = True
    llm_required: bool = False
    embeddings_required: bool = False
    qdrant_required: bool = False
