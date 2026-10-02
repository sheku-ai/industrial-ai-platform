from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AssistantWorkspaceRuntimeResponse(BaseModel):
    assistant_workspace_runtime_schema_version: str = "1"
    runtime_name: str
    runtime_status: str
    workspace_summary: dict[str, Any] = Field(default_factory=dict)
    assistant_definitions: list[dict[str, Any]] = Field(default_factory=list)
    conversations: list[dict[str, Any]] = Field(default_factory=list)
    conversation_turns: list[dict[str, Any]] = Field(default_factory=list)
    runtime_executions: dict[str, Any] = Field(default_factory=dict)
    retrieval_and_citations: dict[str, Any] = Field(default_factory=dict)
    feedback_and_audit: dict[str, Any] = Field(default_factory=dict)
    assistant_explorer: dict[str, Any] = Field(default_factory=dict)
    conversation_explorer: dict[str, Any] = Field(default_factory=dict)
    conversation_timeline: dict[str, Any] = Field(default_factory=dict)
    retrieval_explorer: dict[str, Any] = Field(default_factory=dict)
    citation_explorer: dict[str, Any] = Field(default_factory=dict)
    runtime_execution: dict[str, Any] = Field(default_factory=dict)
    feedback: dict[str, Any] = Field(default_factory=dict)
    audit: dict[str, Any] = Field(default_factory=dict)
    runtime_trace: dict[str, Any] = Field(default_factory=dict)
    diagnostics: dict[str, Any] = Field(default_factory=dict)
    postgresql_source_of_truth: bool = True
    ai_required: bool = False
    llm_used: bool = False
    qdrant_used: bool = False


class AssistantWorkspaceCapabilitiesResponse(BaseModel):
    organization_id: str | None = None
    assistant_read: bool
    assistant_administer: bool
    workspace_available: bool
    chat_available: bool
    conversations_available: bool
    reason: str | None = None
