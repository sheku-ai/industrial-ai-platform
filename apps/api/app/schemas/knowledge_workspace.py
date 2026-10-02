from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class KnowledgeWorkspaceRuntimeResponse(BaseModel):
    knowledge_workspace_runtime_schema_version: str = "1"
    runtime_name: str
    runtime_status: str
    workspace_summary: dict[str, Any] = Field(default_factory=dict)
    collections: list[dict[str, Any]] = Field(default_factory=list)
    knowledge_sources: list[dict[str, Any]] = Field(default_factory=list)
    knowledge_documents: list[dict[str, Any]] = Field(default_factory=list)
    chunk_overview: dict[str, Any] = Field(default_factory=dict)
    enterprise_search: dict[str, Any] = Field(default_factory=dict)
    diagnostics: dict[str, Any] = Field(default_factory=dict)
    postgresql_source_of_truth: bool = True
    ai_required: bool = False
    llm_used: bool = False
    qdrant_used: bool = False
