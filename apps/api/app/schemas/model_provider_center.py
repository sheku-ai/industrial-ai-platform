from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ModelProviderCenterRuntimeResponse(BaseModel):
    model_provider_center_runtime_schema_version: str = "1"
    runtime_name: str
    runtime_status: str
    workspace_summary: dict[str, Any] = Field(default_factory=dict)
    model_inventory: list[dict[str, Any]] = Field(default_factory=list)
    provider_inventory: list[dict[str, Any]] = Field(default_factory=list)
    gateway_readiness: dict[str, Any] = Field(default_factory=dict)
    model_capabilities: dict[str, Any] = Field(default_factory=dict)
    default_model_profiles: dict[str, Any] = Field(default_factory=dict)
    assistant_model_usage: dict[str, Any] = Field(default_factory=dict)
    prompt_guardrail_relationships: dict[str, Any] = Field(default_factory=dict)
    execution_readiness: dict[str, Any] = Field(default_factory=dict)
    capability_availability: dict[str, Any] = Field(default_factory=dict)
    historical_usage: dict[str, Any] = Field(default_factory=dict)
    configuration_diagnostics: dict[str, Any] = Field(default_factory=dict)
    provider_diagnostics: dict[str, Any] = Field(default_factory=dict)
    optional_ai_status: dict[str, Any] = Field(default_factory=dict)
    pending_capabilities: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[dict[str, Any]] = Field(default_factory=list)
    recommendations: list[dict[str, Any]] = Field(default_factory=list)
    postgresql_source_of_truth: bool = True
    side_effects_performed: bool = False
    external_calls_performed: bool = False
    llm_used: bool = False
    qdrant_used: bool = False
    secrets_exposed: bool = False
