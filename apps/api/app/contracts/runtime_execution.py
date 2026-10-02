from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

JsonMapping = Mapping[str, Any]
StringSequence = Sequence[str]


@dataclass(frozen=True)
class InferenceRequest:
    request_id: uuid.UUID
    organization_id: uuid.UUID | None
    runtime_profile_id: uuid.UUID | None
    provider_id: uuid.UUID | None
    model_id: uuid.UUID | None
    answer_mode: str
    rendered_prompt: str
    context: tuple[str, ...] = ()
    citations: tuple[JsonMapping, ...] = ()
    parameters: JsonMapping = field(default_factory=dict)
    metadata: JsonMapping = field(default_factory=dict)


@dataclass(frozen=True)
class InferenceResponse:
    request_id: uuid.UUID
    status: str
    text: str | None = None
    finish_reason: str | None = None
    usage: JsonMapping = field(default_factory=dict)
    provider_metadata: JsonMapping = field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None


@dataclass(frozen=True)
class ProviderExecutionRequest:
    request_id: uuid.UUID
    provider_id: uuid.UUID
    model_id: uuid.UUID
    adapter_type: str
    model_ref: str
    rendered_prompt: str
    credential_ref: str | None = None
    timeout_ms: int | None = None
    parameters: JsonMapping = field(default_factory=dict)
    metadata: JsonMapping = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderExecutionResult:
    request_id: uuid.UUID
    status: str
    output_text: str | None = None
    finish_reason: str | None = None
    usage: JsonMapping = field(default_factory=dict)
    latency_ms: int | None = None
    retryable: bool = False
    provider_error_code: str | None = None
    provider_metadata: JsonMapping = field(default_factory=dict)


@dataclass(frozen=True)
class PromptRenderRequest:
    prompt_id: uuid.UUID
    template: str
    variables: JsonMapping = field(default_factory=dict)
    context: tuple[str, ...] = ()
    citations: tuple[JsonMapping, ...] = ()
    metadata: JsonMapping = field(default_factory=dict)


@dataclass(frozen=True)
class PromptRenderResult:
    status: str
    rendered_prompt: str | None = None
    missing_variables: tuple[str, ...] = ()
    error_code: str | None = None
    metadata: JsonMapping = field(default_factory=dict)


@dataclass(frozen=True)
class GuardrailEvaluationRequest:
    guardrail_id: uuid.UUID
    stage: str
    input_text: str | None = None
    output_text: str | None = None
    context: tuple[str, ...] = ()
    metadata: JsonMapping = field(default_factory=dict)


@dataclass(frozen=True)
class GuardrailEvaluationResult:
    status: str
    decision: str
    reason: str | None = None
    rule_results: tuple[JsonMapping, ...] = ()
    metadata: JsonMapping = field(default_factory=dict)


@dataclass(frozen=True)
class RuntimeExecutionRequest:
    request_id: uuid.UUID
    organization_id: uuid.UUID | None
    requested_answer_mode: str
    resolved_answer_mode: str
    runtime_profile_id: uuid.UUID | None
    provider_id: uuid.UUID | None
    model_id: uuid.UUID | None
    prompt_id: uuid.UUID | None
    guardrail_id: uuid.UUID | None
    generation_allowed: bool
    context: tuple[str, ...] = ()
    citations: tuple[JsonMapping, ...] = ()
    variables: JsonMapping = field(default_factory=dict)
    parameters: JsonMapping = field(default_factory=dict)
    timeout_ms: int | None = None
    metadata: JsonMapping = field(default_factory=dict)


@dataclass(frozen=True)
class RuntimeExecutionResult:
    request_id: uuid.UUID
    status: str
    resolved_answer_mode: str
    answer_text: str | None = None
    answer_generated: bool = False
    execution_attempted: bool = False
    fallback_used: bool = False
    fallback_reason: str | None = None
    provider_id: uuid.UUID | None = None
    model_id: uuid.UUID | None = None
    prompt_id: uuid.UUID | None = None
    guardrail_id: uuid.UUID | None = None
    latency_ms: int | None = None
    usage: JsonMapping = field(default_factory=dict)
    error_code: str | None = None
    metadata: JsonMapping = field(default_factory=dict)
