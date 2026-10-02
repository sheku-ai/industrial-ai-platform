from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from app.contracts.runtime_execution import RuntimeExecutionRequest, RuntimeExecutionResult

JsonMapping = Mapping[str, Any]


class ExecutionState(StrEnum):
    RECEIVED = "received"
    VALIDATED = "validated"
    REJECTED = "rejected"
    PREPARING = "preparing"
    PROMPT_RENDERED = "prompt_rendered"
    PRE_GUARDRAIL_PASSED = "pre_guardrail_passed"
    SECRET_RESOLVED = "secret_resolved"
    PROVIDER_READY = "provider_ready"
    EXECUTING = "executing"
    PROVIDER_COMPLETED = "provider_completed"
    POST_GUARDRAIL_PASSED = "post_guardrail_passed"
    COMPLETED = "completed"
    FALLBACK_COMPLETED = "fallback_completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


class FailureCategory(StrEnum):
    CONFIGURATION_ERROR = "configuration_error"
    ELIGIBILITY_REJECTED = "eligibility_rejected"
    PROMPT_RENDER_ERROR = "prompt_render_error"
    GUARDRAIL_BLOCKED = "guardrail_blocked"
    SECRET_RESOLUTION_ERROR = "secret_resolution_error"
    PROVIDER_NOT_READY = "provider_not_ready"
    PROVIDER_AUTHENTICATION_ERROR = "provider_authentication_error"
    PROVIDER_RATE_LIMITED = "provider_rate_limited"
    PROVIDER_TIMEOUT = "provider_timeout"
    PROVIDER_TRANSPORT_ERROR = "provider_transport_error"
    PROVIDER_INVALID_RESPONSE = "provider_invalid_response"
    PROVIDER_CONTENT_ERROR = "provider_content_error"
    CANCELLED = "cancelled"
    INTERNAL_ERROR = "internal_error"


class FallbackReason(StrEnum):
    EXECUTION_NOT_ENABLED = "execution_not_enabled"
    PROVIDER_EXECUTION_NOT_ENABLED = "provider_execution_not_enabled"
    GENERATION_NOT_ALLOWED = "generation_not_allowed"
    UNSUPPORTED_ANSWER_MODE = "unsupported_answer_mode"
    INCOMPLETE_RUNTIME_RESOLUTION = "incomplete_runtime_resolution"
    PROMPT_RENDER_FAILED = "prompt_render_failed"
    PRE_GUARDRAIL_BLOCKED = "pre_guardrail_blocked"
    SECRET_RESOLUTION_FAILED = "secret_resolution_failed"
    PROVIDER_NOT_READY = "provider_not_ready"
    PROVIDER_EXECUTION_FAILED = "provider_execution_failed"
    POST_GUARDRAIL_BLOCKED = "post_guardrail_blocked"
    EXECUTION_CANCELLED = "execution_cancelled"
    EXECUTION_TIMED_OUT = "execution_timed_out"


TERMINAL_STATES = frozenset(
    {
        ExecutionState.REJECTED,
        ExecutionState.COMPLETED,
        ExecutionState.FALLBACK_COMPLETED,
        ExecutionState.FAILED,
        ExecutionState.CANCELLED,
        ExecutionState.TIMED_OUT,
    }
)


@dataclass(frozen=True)
class OrchestrationPolicy:
    execution_enabled: bool = False
    provider_execution_enabled: bool = False
    retries_enabled: bool = False
    max_attempts: int = 1
    default_timeout_ms: int = 30_000
    max_timeout_ms: int = 120_000
    metadata: JsonMapping = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if self.default_timeout_ms < 1:
            raise ValueError("default_timeout_ms must be positive")
        if self.max_timeout_ms < self.default_timeout_ms:
            raise ValueError("max_timeout_ms must be greater than or equal to default_timeout_ms")


@dataclass(frozen=True)
class OrchestrationTrace:
    state: ExecutionState
    attempt_count: int = 0
    failure_category: FailureCategory | None = None
    fallback_reason: FallbackReason | None = None
    metadata: JsonMapping = field(default_factory=dict)


@runtime_checkable
class CancellationBoundary(Protocol):
    def is_cancelled(self) -> bool: ...


class NeverCancelled:
    def is_cancelled(self) -> bool:
        return False


@runtime_checkable
class RuntimeExecutionOrchestrator(Protocol):
    def execute(
        self,
        request: RuntimeExecutionRequest,
        *,
        policy: OrchestrationPolicy,
        cancellation: CancellationBoundary | None = None,
    ) -> RuntimeExecutionResult: ...
