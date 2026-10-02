from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = REPO_ROOT / "apps" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.orchestration import (
    ExecutionState,
    ExecutionStateMachine,
    InvalidExecutionTransition,
    TERMINAL_STATES,
)


def assert_raises_invalid(fn) -> None:
    try:
        fn()
    except InvalidExecutionTransition:
        return
    raise AssertionError("InvalidExecutionTransition was not raised")


def main() -> None:
    machine = ExecutionStateMachine()
    expected_path = [
        ExecutionState.RECEIVED,
        ExecutionState.VALIDATED,
        ExecutionState.PREPARING,
        ExecutionState.PROMPT_RENDERED,
        ExecutionState.PRE_GUARDRAIL_PASSED,
        ExecutionState.PROVIDER_READY,
        ExecutionState.EXECUTING,
        ExecutionState.PROVIDER_COMPLETED,
        ExecutionState.POST_GUARDRAIL_PASSED,
        ExecutionState.COMPLETED,
    ]

    for state in expected_path[1:]:
        transition = machine.transition(state, reason_code=f"smoke_{state.value}")
        assert transition.to_state == state
        assert transition.sequence == len(machine.transitions) - 1

    assert machine.state == ExecutionState.COMPLETED
    assert machine.is_terminal is True
    assert machine.state in TERMINAL_STATES
    assert tuple(item.to_state for item in machine.transitions) == tuple(expected_path)
    assert machine.allowed_transitions() == frozenset()
    assert_raises_invalid(lambda: machine.transition(ExecutionState.FAILED))

    fallback = ExecutionStateMachine()
    fallback.transition(ExecutionState.VALIDATED)
    fallback.transition(ExecutionState.FALLBACK_COMPLETED, reason_code="execution_not_enabled")
    assert fallback.is_terminal is True
    assert fallback.state == ExecutionState.FALLBACK_COMPLETED

    invalid = ExecutionStateMachine()
    assert_raises_invalid(lambda: invalid.transition(ExecutionState.EXECUTING))
    assert_raises_invalid(lambda: invalid.transition(ExecutionState.RECEIVED))

    cancelled = ExecutionStateMachine()
    cancelled.transition(ExecutionState.CANCELLED, reason_code="cancel_requested")
    assert cancelled.is_terminal is True

    print(
        {
            "status": "passed",
            "state_machine": True,
            "happy_path_states": len(expected_path),
            "terminal_states": sorted(state.value for state in TERMINAL_STATES),
            "invalid_transitions_blocked": True,
            "provider_execution_performed": False,
            "network_call_performed": False,
            "generation_performed": False,
        }
    )


if __name__ == "__main__":
    main()
