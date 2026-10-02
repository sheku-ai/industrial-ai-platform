from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.contracts.runtime_execution import ProviderExecutionResult
from app.orchestration.base import FailureCategory, OrchestrationPolicy
from app.orchestration.timing import ExecutionControl, ExecutionTimedOut


class RetryDecision(StrEnum):
    RETRY = "retry"
    STOP = "stop"


@dataclass(frozen=True)
class FailureClassification:
    category: FailureCategory
    retryable: bool
    normalized_code: str


NON_RETRYABLE_PROVIDER_CODES = frozenset(
    {
        "invalid_request",
        "authentication_failed",
        "authorization_failed",
        "model_not_found",
        "content_blocked",
        "configuration_error",
    }
)

RETRYABLE_PROVIDER_CODES = frozenset(
    {
        "rate_limited",
        "provider_timeout",
        "transport_error",
        "temporarily_unavailable",
        "service_unavailable",
    }
)


def classify_provider_failure(result: ProviderExecutionResult) -> FailureClassification:
    code = (result.provider_error_code or "provider_execution_failed").strip().lower()

    if code in {"authentication_failed", "authorization_failed"}:
        return FailureClassification(FailureCategory.PROVIDER_AUTHENTICATION_ERROR, False, code)
    if code == "rate_limited":
        return FailureClassification(FailureCategory.PROVIDER_RATE_LIMITED, True, code)
    if code == "provider_timeout":
        return FailureClassification(FailureCategory.PROVIDER_TIMEOUT, True, code)
    if code in {"transport_error", "temporarily_unavailable", "service_unavailable"}:
        return FailureClassification(FailureCategory.PROVIDER_TRANSPORT_ERROR, True, code)
    if code == "invalid_response":
        return FailureClassification(FailureCategory.PROVIDER_INVALID_RESPONSE, False, code)
    if code == "content_blocked":
        return FailureClassification(FailureCategory.PROVIDER_CONTENT_ERROR, False, code)
    if code in {"invalid_request", "model_not_found", "configuration_error"}:
        return FailureClassification(FailureCategory.CONFIGURATION_ERROR, False, code)

    return FailureClassification(
        FailureCategory.PROVIDER_TRANSPORT_ERROR,
        bool(result.retryable),
        code,
    )


@dataclass(frozen=True)
class RetryPlan:
    decision: RetryDecision
    next_attempt: int | None
    delay_ms: int
    reason: str


@dataclass(frozen=True)
class RetryPolicy:
    base_delay_ms: int = 250
    max_delay_ms: int = 2_000

    def __post_init__(self) -> None:
        if self.base_delay_ms < 0:
            raise ValueError("base_delay_ms cannot be negative")
        if self.max_delay_ms < self.base_delay_ms:
            raise ValueError("max_delay_ms must be greater than or equal to base_delay_ms")

    def delay_for_attempt(self, attempt_number: int) -> int:
        if attempt_number < 1:
            raise ValueError("attempt_number must be at least 1")
        return min(self.base_delay_ms * (2 ** (attempt_number - 1)), self.max_delay_ms)

    def evaluate(
        self,
        *,
        attempt_number: int,
        classification: FailureClassification,
        orchestration_policy: OrchestrationPolicy,
        control: ExecutionControl,
    ) -> RetryPlan:
        if not orchestration_policy.retries_enabled:
            return RetryPlan(RetryDecision.STOP, None, 0, "retries_disabled")
        if not classification.retryable:
            return RetryPlan(RetryDecision.STOP, None, 0, "failure_not_retryable")
        if attempt_number >= orchestration_policy.max_attempts:
            return RetryPlan(RetryDecision.STOP, None, 0, "max_attempts_reached")

        next_attempt = attempt_number + 1
        delay_ms = self.delay_for_attempt(next_attempt)
        try:
            remaining_ms = control.checkpoint(minimum_remaining_ms=delay_ms + 1)
        except ExecutionTimedOut:
            return RetryPlan(RetryDecision.STOP, None, 0, "deadline_exhausted")

        if remaining_ms <= delay_ms:
            return RetryPlan(RetryDecision.STOP, None, 0, "insufficient_time_remaining")

        return RetryPlan(RetryDecision.RETRY, next_attempt, delay_ms, "retryable_failure")
