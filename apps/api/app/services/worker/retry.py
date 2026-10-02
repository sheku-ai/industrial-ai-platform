"""Retry policy for Platform Worker jobs."""

from __future__ import annotations

from dataclasses import dataclass

from app.services.worker.contracts import JobLease, RetryDecision, WorkerExecutionResult, WorkerJobStatus
from app.services.worker.interfaces import JobRetryService


@dataclass(frozen=True)
class RetryPolicyConfig:
    """Configurable retry behavior for platform jobs."""

    base_backoff_seconds: int = 30
    max_backoff_seconds: int = 900
    retryable_error_codes: tuple[str, ...] = (
        "timeout",
        "temporary_unavailable",
        "object_store_unavailable",
        "connector_unavailable",
        "model_unavailable",
    )


class ConfigurableJobRetryService(JobRetryService):
    """Deterministic retry policy for worker execution failures."""

    def __init__(self, config: RetryPolicyConfig | None = None) -> None:
        self.config = config or RetryPolicyConfig()

    def decide(self, lease: JobLease, result: WorkerExecutionResult) -> RetryDecision:
        next_attempt = lease.attempt_count + 1

        if result.status == WorkerJobStatus.SUCCEEDED:
            return RetryDecision(
                retryable=False,
                next_status=WorkerJobStatus.SUCCEEDED,
                next_attempt_count=lease.attempt_count,
                backoff_seconds=0,
            )

        has_attempts = next_attempt < lease.max_attempts
        error_is_retryable = result.error_code in self.config.retryable_error_codes
        retryable = has_attempts and error_is_retryable

        if retryable:
            backoff = min(
                self.config.base_backoff_seconds * (2 ** max(next_attempt - 1, 0)),
                self.config.max_backoff_seconds,
            )
            return RetryDecision(
                retryable=True,
                next_status=WorkerJobStatus.FAILED_RETRYABLE,
                next_attempt_count=next_attempt,
                backoff_seconds=backoff,
                error_code=result.error_code,
                error_message=result.error_message,
            )

        return RetryDecision(
            retryable=False,
            next_status=WorkerJobStatus.FAILED_TERMINAL,
            next_attempt_count=next_attempt,
            backoff_seconds=0,
            error_code=result.error_code,
            error_message=result.error_message,
        )
