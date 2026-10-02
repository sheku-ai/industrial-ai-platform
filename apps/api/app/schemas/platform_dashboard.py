from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class PlatformDashboardRuntimeResponse(BaseModel):
    platform_dashboard_runtime_schema_version: str = "1"
    runtime_name: str
    runtime_status: str
    platform_summary: dict[str, Any] = Field(default_factory=dict)
    administration_summary: dict[str, Any] = Field(default_factory=dict)
    operations_summary: dict[str, Any] = Field(default_factory=dict)
    readiness_summary: dict[str, Any] = Field(default_factory=dict)
    operational_summary: dict[str, Any] = Field(default_factory=dict)
    functional_capabilities: dict[str, Any] = Field(default_factory=dict)
    dashboard_sections: dict[str, Any] = Field(default_factory=dict)
    alerts_and_diagnostics: dict[str, Any] = Field(default_factory=dict)
    navigation: list[dict[str, Any]] = Field(default_factory=list)
    recommended_next_actions: list[dict[str, Any]] = Field(default_factory=list)
    source_runtimes: dict[str, Any] = Field(default_factory=dict)
    postgresql_source_of_truth: bool = True
    ai_required: bool = False
    llm_used: bool = False
    embeddings_used: bool = False
    qdrant_used: bool = False
