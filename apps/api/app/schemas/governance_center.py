from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class GovernanceCenterRuntimeResponse(BaseModel):
    governance_center_runtime_schema_version: str = "1"
    runtime_name: str
    runtime_status: str
    workspace_summary: dict[str, Any] = Field(default_factory=dict)
    audit_governance: dict[str, Any] = Field(default_factory=dict)
    feedback_governance: dict[str, Any] = Field(default_factory=dict)
    classification_governance: dict[str, Any] = Field(default_factory=dict)
    retention_governance: dict[str, Any] = Field(default_factory=dict)
    policy_governance: dict[str, Any] = Field(default_factory=dict)
    runtime_evidence: dict[str, Any] = Field(default_factory=dict)
    document_lineage: dict[str, Any] = Field(default_factory=dict)
    knowledge_lineage: dict[str, Any] = Field(default_factory=dict)
    assistant_traceability: dict[str, Any] = Field(default_factory=dict)
    compliance_readiness: dict[str, Any] = Field(default_factory=dict)
    diagnostics: dict[str, Any] = Field(default_factory=dict)
    postgresql_source_of_truth: bool = True
    side_effects_performed: bool = False
    llm_used: bool = False
    qdrant_used: bool = False
    external_calls_performed: bool = False
