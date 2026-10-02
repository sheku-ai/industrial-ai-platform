from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ProductIntegrationRuntimeResponse(BaseModel):
    product_integration_runtime_schema_version: str = "1"
    runtime_name: str
    runtime_status: str
    platform: dict[str, Any] = Field(default_factory=dict)
    administration: dict[str, Any] = Field(default_factory=dict)
    documents: dict[str, Any] = Field(default_factory=dict)
    knowledge: dict[str, Any] = Field(default_factory=dict)
    assistants: dict[str, Any] = Field(default_factory=dict)
    operations: dict[str, Any] = Field(default_factory=dict)
    governance: dict[str, Any] = Field(default_factory=dict)
    connectors: dict[str, Any] = Field(default_factory=dict)
    ai_studio: dict[str, Any] = Field(default_factory=dict)
    workspace_validation: dict[str, Any] = Field(default_factory=dict)
    runtime_validation: dict[str, Any] = Field(default_factory=dict)
    reference_tenant: dict[str, Any] = Field(default_factory=dict)
    domain_readiness: dict[str, Any] = Field(default_factory=dict)
    rc_gate: dict[str, Any] = Field(default_factory=dict)
    product_acceptance: dict[str, Any] = Field(default_factory=dict)
    evidence_freshness: dict[str, Any] = Field(default_factory=dict)
    release_eligibility: dict[str, Any] = Field(default_factory=dict)
    overall: dict[str, Any] = Field(default_factory=dict)
    product_score: dict[str, Any] = Field(default_factory=dict)
    readiness_matrix: dict[str, Any] = Field(default_factory=dict)
    diagnostics: dict[str, Any] = Field(default_factory=dict)
    postgresql_source_of_truth: bool = True
    side_effects_performed: bool = False
    external_calls_performed: bool = False
    llm_used: bool = False
    qdrant_used: bool = False
