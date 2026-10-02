from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.readiness import AuthoritativeReadinessEvidence


class ProductionReadinessRuntimeResponse(BaseModel):
    production_readiness_runtime_schema_version: str = "3"
    runtime_name: str
    runtime_status: str
    status: str
    reason: str
    product_acceptance: dict[str, Any] = Field(default_factory=dict)
    evidence_freshness: dict[str, Any] = Field(default_factory=dict)
    release_eligibility: dict[str, Any] = Field(default_factory=dict)
    workspace_summary: dict[str, Any] = Field(default_factory=dict)
    overall_production_readiness: dict[str, Any] = Field(default_factory=dict)
    gate_matrix: list[dict[str, Any]] = Field(default_factory=list)
    blockers: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[dict[str, Any]] = Field(default_factory=list)
    recommendations: list[dict[str, Any]] = Field(default_factory=list)
    next_actions: list[dict[str, Any]] = Field(default_factory=list)
    production_score: dict[str, Any] = Field(default_factory=dict)
    evidence_contracts: list[AuthoritativeReadinessEvidence] = Field(default_factory=list)
    evaluation_timestamp: datetime | None = None
    expires_at: datetime | None = None
    contract_version: str = "platform.readiness.evidence.v1"
    runtime_version: str = "production-readiness-runtime.v3"
    postgresql_source_of_truth: bool = True
    side_effects_performed: bool = False
    external_calls_performed: bool = False
    llm_used: bool = False
    qdrant_used: bool = False
