from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AIStudioRuntimeResponse(BaseModel):
    ai_studio_runtime_schema_version: str = "1"
    runtime_name: str
    runtime_status: str
    workspace_summary: dict[str, Any] = Field(default_factory=dict)
    models_and_providers: dict[str, Any] = Field(default_factory=dict)
    prompts: list[dict[str, Any]] = Field(default_factory=list)
    guardrails: list[dict[str, Any]] = Field(default_factory=list)
    workflows: list[dict[str, Any]] = Field(default_factory=list)
    assistants: list[dict[str, Any]] = Field(default_factory=list)
    knowledge_sources: list[dict[str, Any]] = Field(default_factory=list)
    runtime_executions: dict[str, Any] = Field(default_factory=dict)
    capability_availability: dict[str, Any] = Field(default_factory=dict)
    policy_readiness: dict[str, Any] = Field(default_factory=dict)
    audit_diagnostics: dict[str, Any] = Field(default_factory=dict)
    diagnostics: dict[str, Any] = Field(default_factory=dict)
    postgresql_source_of_truth: bool = True
    ai_required: bool = False
    llm_used: bool = False
    qdrant_used: bool = False
    external_provider_calls: bool = False
