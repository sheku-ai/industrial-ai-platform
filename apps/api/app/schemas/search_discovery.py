from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SearchDiscoveryRuntimeResponse(BaseModel):
    search_discovery_runtime_schema_version: str = "1"
    runtime_name: str
    runtime_status: str
    workspace_summary: dict[str, Any] = Field(default_factory=dict)
    enterprise_search_summary: dict[str, Any] = Field(default_factory=dict)
    knowledge_coverage: dict[str, Any] = Field(default_factory=dict)
    knowledge_collections: list[dict[str, Any]] = Field(default_factory=list)
    knowledge_sources: list[dict[str, Any]] = Field(default_factory=list)
    knowledge_documents: list[dict[str, Any]] = Field(default_factory=list)
    knowledge_chunks: dict[str, Any] = Field(default_factory=dict)
    chunk_explorer: dict[str, Any] = Field(default_factory=dict)
    document_explorer: dict[str, Any] = Field(default_factory=dict)
    citation_explorer: dict[str, Any] = Field(default_factory=dict)
    search_explorer: dict[str, Any] = Field(default_factory=dict)
    search_diagnostics: dict[str, Any] = Field(default_factory=dict)
    coverage_diagnostics: dict[str, Any] = Field(default_factory=dict)
    evidence_readiness: dict[str, Any] = Field(default_factory=dict)
    traceability: dict[str, Any] = Field(default_factory=dict)
    search_performance: dict[str, Any] = Field(default_factory=dict)
    search_quality: dict[str, Any] = Field(default_factory=dict)
    reference_tenant_coverage: dict[str, Any] = Field(default_factory=dict)
    pending_capabilities: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[dict[str, Any]] = Field(default_factory=list)
    recommendations: list[dict[str, Any]] = Field(default_factory=list)
    postgresql_source_of_truth: bool = True
    llm_used: bool = False
    qdrant_used: bool = False
    external_calls_performed: bool = False
    side_effects_performed: bool = False
