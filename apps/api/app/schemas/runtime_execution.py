from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field

AnswerMode = Literal["context_only", "extractive", "assisted"]


class RuntimeResolveRequest(BaseModel):
    organization_id: uuid.UUID | None = None
    requested_answer_mode: str = Field(min_length=1, max_length=64)


class RuntimeResolveResponse(BaseModel):
    requested_answer_mode: str
    resolved_answer_mode: str
    runtime_profile_id: uuid.UUID | None = None
    provider_id: uuid.UUID | None = None
    model_id: uuid.UUID | None = None
    prompt_id: uuid.UUID | None = None
    guardrail_id: uuid.UUID | None = None
    generation_requested: bool
    generation_allowed: bool
    fallback_used: bool
    fallback_reason: str | None = None
    provider_configured: bool
    model_configured: bool
    prompt_configured: bool
    guardrail_configured: bool
    execution_attempted: bool = False
    provider_execution_performed: bool = False
    generation_performed: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class RuntimeExecuteRequest(BaseModel):
    organization_id: uuid.UUID | None = None
    requested_answer_mode: str = Field(min_length=1, max_length=64)
    context: list[str] = Field(default_factory=list)
    citations: list[dict[str, Any]] = Field(default_factory=list)
    variables: dict[str, Any] = Field(default_factory=dict)
    parameters: dict[str, Any] = Field(default_factory=dict)


class RuntimeExecuteResponse(BaseModel):
    status: str
    requested_answer_mode: str
    resolved_answer_mode: str
    answer_text: str | None = None
    answer_generated: bool = False
    execution_attempted: bool = False
    fallback_used: bool = True
    fallback_reason: str | None = None
    error_code: str | None = None
    context_preserved: bool = True
    citation_count: int = 0
    provider_execution_performed: bool = False
    secret_resolution_performed: bool = False
    generation_performed: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class RuntimeStatusResponse(BaseModel):
    status: str = "available"
    resolver_enabled: bool = True
    execution_enabled: bool = False
    provider_execution_enabled: bool = False
    supported_answer_modes: list[str] = Field(default_factory=lambda: ["context_only", "extractive", "assisted"])
    fallback_answer_mode: str = "extractive"
    contract_version: str = "runtime_execution_api_v1"
