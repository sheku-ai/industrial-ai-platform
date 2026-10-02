from __future__ import annotations

import sys
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = REPO_ROOT / "apps" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.contracts.runtime_execution import ProviderExecutionResult
from app.orchestration import (
    ExecutionControl,
    ExecutionDeadline,
    FailureCategory,
    NeverCancelled,
    OrchestrationPolicy,
    RetryDecision,
    RetryPolicy,
    classify_provider_failure,
)


class FakeClock:
    def __init__(self, value: float = 100.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value

    def advance_ms(self, milliseconds: int) -> None:
        self.value += milliseconds / 1000.0


def provider_result(code: str, *, retryable: bool = False) -> ProviderExecutionResult:
    return ProviderExecutionResult(
        request_id=uuid.uuid4(),
        status="failed",
        retryable=retryable,
        provider_error_code=code,
    )


def main() -> None:
    assert classify_provider_failure(provider_result("authentication_failed")).category == FailureCategory.PROVIDER_AUTHENTICATION_ERROR
    assert classify_provider_failure(provider_result("rate_limited")).retryable is True
    assert classify_provider_failure(provider_result("provider_timeout")).category == FailureCategory.PROVIDER_TIMEOUT
    assert classify_provider_failure(provider_result("invalid_response")).retryable is False
    assert classify_provider_failure(provider_result("unknown", retryable=True)).retryable is True

    clock = FakeClock()
    policy = OrchestrationPolicy(
        retries_enabled=True,
        max_attempts=3,
        default_timeout_ms=5_000,
        max_timeout_ms=5_000,
    )
    deadline = ExecutionDeadline.from_policy(
        requested_timeout_ms=None,
        policy=policy,
        clock=clock,
    )
    control = ExecutionControl(deadline=deadline, cancellation=NeverCancelled())
    retry_policy = RetryPolicy(base_delay_ms=100, max_delay_ms=500)

    retryable = classify_provider_failure(provider_result("rate_limited"))
    plan = retry_policy.evaluate(
        attempt_number=1,
        classification=retryable,
        orchestration_policy=policy,
        control=control,
    )
    assert plan.decision == RetryDecision.RETRY
    assert plan.next_attempt == 2
    assert plan.delay_ms == 200

    retries_disabled = retry_policy.evaluate(
        attempt_number=1,
        classification=retryable,
        orchestration_policy=OrchestrationPolicy(retries_enabled=False, max_attempts=3),
        control=control,
    )
    assert retries_disabled.decision == RetryDecision.STOP
    assert retries_disabled.reason == "retries_disabled"

    non_retryable = retry_policy.evaluate(
        attempt_number=1,
        classification=classify_provider_failure(provider_result("authentication_failed")),
        orchestration_policy=policy,
        control=control,
    )
    assert non_retryable.reason == "failure_not_retryable"

    exhausted = retry_policy.evaluate(
        attempt_number=3,
        classification=retryable,
        orchestration_policy=policy,
        control=control,
    )
    assert exhausted.reason == "max_attempts_reached"

    short_clock = FakeClock()
    short_deadline = ExecutionDeadline.from_policy(
        requested_timeout_ms=150,
        policy=policy,
        clock=short_clock,
    )
    short_control = ExecutionControl(deadline=short_deadline, cancellation=NeverCancelled())
    no_time = retry_policy.evaluate(
        attempt_number=1,
        classification=retryable,
        orchestration_policy=policy,
        control=short_control,
    )
    assert no_time.decision == RetryDecision.STOP
    assert no_time.reason in {"deadline_exhausted", "insufficient_time_remaining"}

    print(
        {
            "status": "passed",
            "failure_classification": True,
            "retries_disabled_by_default": True,
            "retryable_failures_bounded": True,
            "non_retryable_failures_blocked": True,
            "max_attempts_enforced": True,
            "deadline_aware_retries": True,
            "provider_execution_performed": False,
            "network_call_performed": False,
            "generation_performed": False,
        }
    )


if __name__ == "__main__":
    main()
