from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = REPO_ROOT / "apps" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.orchestration import (
    CancellationToken,
    ExecutionCancelled,
    ExecutionControl,
    ExecutionDeadline,
    ExecutionTimedOut,
    NeverCancelled,
    OrchestrationPolicy,
)


class FakeClock:
    def __init__(self, value: float = 100.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value

    def advance_ms(self, milliseconds: int) -> None:
        self.value += milliseconds / 1000.0


def assert_raises(expected, fn) -> None:
    try:
        fn()
    except expected:
        return
    raise AssertionError(f"{expected.__name__} was not raised")


def main() -> None:
    policy = OrchestrationPolicy(default_timeout_ms=1_000, max_timeout_ms=2_000)

    clock = FakeClock()
    deadline = ExecutionDeadline.from_policy(
        requested_timeout_ms=None,
        policy=policy,
        clock=clock,
    )
    assert deadline.timeout_ms == 1_000
    assert deadline.remaining_ms() == 1_000

    clock.advance_ms(250)
    assert 749 <= deadline.remaining_ms() <= 750
    assert 250 <= deadline.elapsed_ms() <= 251
    assert deadline.require_remaining() > 0

    capped_clock = FakeClock()
    capped = ExecutionDeadline.from_policy(
        requested_timeout_ms=10_000,
        policy=policy,
        clock=capped_clock,
    )
    assert capped.timeout_ms == 2_000

    control = ExecutionControl(deadline=deadline, cancellation=NeverCancelled())
    bounded = control.remaining_timeout_ms(maximum_ms=300)
    assert 1 <= bounded <= 300

    token = CancellationToken()
    cancellable = ExecutionControl(deadline=deadline, cancellation=token)
    assert cancellable.checkpoint() > 0
    token.cancel()
    assert token.is_cancelled() is True
    assert_raises(ExecutionCancelled, cancellable.checkpoint)

    timeout_clock = FakeClock()
    expired = ExecutionDeadline.from_policy(
        requested_timeout_ms=100,
        policy=policy,
        clock=timeout_clock,
    )
    timeout_clock.advance_ms(100)
    assert expired.is_expired() is True
    assert expired.remaining_ms() == 0
    assert_raises(ExecutionTimedOut, expired.require_remaining)

    assert_raises(
        ValueError,
        lambda: ExecutionDeadline.from_policy(
            requested_timeout_ms=0,
            policy=policy,
            clock=FakeClock(),
        ),
    )

    print(
        {
            "status": "passed",
            "deadline_policy": True,
            "timeout_capped": True,
            "remaining_time_propagation": True,
            "cooperative_cancellation": True,
            "expired_deadline_blocked": True,
            "provider_execution_performed": False,
            "network_call_performed": False,
            "generation_performed": False,
        }
    )


if __name__ == "__main__":
    main()
