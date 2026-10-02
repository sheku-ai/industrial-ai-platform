from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ReadinessGateEvidence(BaseModel):
    gate_code: str
    status: str
    summary: str
    evidence_ids: list[str] = Field(default_factory=list)
    components_evaluated: list[str] = Field(default_factory=list)


class AuthoritativeReadinessEvidence(BaseModel):
    domain: str
    status: str
    reason: str
    gate_results: list[ReadinessGateEvidence] = Field(default_factory=list)
    blockers: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[dict[str, Any]] = Field(default_factory=list)
    recommendations: list[dict[str, Any]] = Field(default_factory=list)
    next_actions: list[dict[str, Any]] = Field(default_factory=list)
    contract_version: str = "platform.readiness.evidence.v1"
    runtime_version: str
    evaluation_timestamp: datetime
    expires_at: datetime | None
    evidence_origin: str
    evaluation_duration: int = Field(ge=0, description="Evaluation duration in milliseconds.")
    components_evaluated: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    postgresql_source_of_truth: bool = True
