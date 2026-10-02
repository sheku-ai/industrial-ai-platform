from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from app.orchestration.base import TERMINAL_STATES, ExecutionState


class InvalidExecutionTransition(ValueError):
    """Raised when an execution lifecycle transition is not permitted."""


ALLOWED_TRANSITIONS: dict[ExecutionState, frozenset[ExecutionState]] = {
    ExecutionState.RECEIVED: frozenset(
        {ExecutionState.VALIDATED, ExecutionState.REJECTED, ExecutionState.CANCELLED, ExecutionState.TIMED_OUT}
    ),
    ExecutionState.VALIDATED: frozenset(
        {
            ExecutionState.PREPARING,
            ExecutionState.REJECTED,
            ExecutionState.FALLBACK_COMPLETED,
            ExecutionState.CANCELLED,
            ExecutionState.TIMED_OUT,
        }
    ),
    ExecutionState.PREPARING: frozenset(
        {
            ExecutionState.PROMPT_RENDERED,
            ExecutionState.FALLBACK_COMPLETED,
            ExecutionState.FAILED,
            ExecutionState.CANCELLED,
            ExecutionState.TIMED_OUT,
        }
    ),
    ExecutionState.PROMPT_RENDERED: frozenset(
        {
            ExecutionState.PRE_GUARDRAIL_PASSED,
            ExecutionState.FALLBACK_COMPLETED,
            ExecutionState.FAILED,
            ExecutionState.CANCELLED,
            ExecutionState.TIMED_OUT,
        }
    ),
    ExecutionState.PRE_GUARDRAIL_PASSED: frozenset(
        {
            ExecutionState.SECRET_RESOLVED,
            ExecutionState.PROVIDER_READY,
            ExecutionState.FALLBACK_COMPLETED,
            ExecutionState.FAILED,
            ExecutionState.CANCELLED,
            ExecutionState.TIMED_OUT,
        }
    ),
    ExecutionState.SECRET_RESOLVED: frozenset(
        {
            ExecutionState.PROVIDER_READY,
            ExecutionState.FALLBACK_COMPLETED,
            ExecutionState.FAILED,
            ExecutionState.CANCELLED,
            ExecutionState.TIMED_OUT,
        }
    ),
    ExecutionState.PROVIDER_READY: frozenset(
        {
            ExecutionState.EXECUTING,
            ExecutionState.FALLBACK_COMPLETED,
            ExecutionState.FAILED,
            ExecutionState.CANCELLED,
            ExecutionState.TIMED_OUT,
        }
    ),
    ExecutionState.EXECUTING: frozenset(
        {
            ExecutionState.PROVIDER_COMPLETED,
            ExecutionState.FALLBACK_COMPLETED,
            ExecutionState.FAILED,
            ExecutionState.CANCELLED,
            ExecutionState.TIMED_OUT,
        }
    ),
    ExecutionState.PROVIDER_COMPLETED: frozenset(
        {
            ExecutionState.POST_GUARDRAIL_PASSED,
            ExecutionState.COMPLETED,
            ExecutionState.FALLBACK_COMPLETED,
            ExecutionState.FAILED,
            ExecutionState.CANCELLED,
            ExecutionState.TIMED_OUT,
        }
    ),
    ExecutionState.POST_GUARDRAIL_PASSED: frozenset(
        {
            ExecutionState.COMPLETED,
            ExecutionState.FALLBACK_COMPLETED,
            ExecutionState.FAILED,
            ExecutionState.CANCELLED,
            ExecutionState.TIMED_OUT,
        }
    ),
}


@dataclass(frozen=True)
class ExecutionTransition:
    sequence: int
    from_state: ExecutionState | None
    to_state: ExecutionState
    occurred_at: datetime
    reason_code: str | None = None


class ExecutionStateMachine:
    def __init__(self, initial_state: ExecutionState = ExecutionState.RECEIVED) -> None:
        self._state = initial_state
        self._history: list[ExecutionTransition] = [
            ExecutionTransition(0, None, initial_state, datetime.now(UTC), "execution_received")
        ]

    @property
    def state(self) -> ExecutionState:
        return self._state

    @property
    def is_terminal(self) -> bool:
        return self._state in TERMINAL_STATES

    @property
    def transitions(self) -> tuple[ExecutionTransition, ...]:
        return tuple(self._history)

    def allowed_transitions(self) -> frozenset[ExecutionState]:
        if self.is_terminal:
            return frozenset()
        return ALLOWED_TRANSITIONS.get(self._state, frozenset())

    def can_transition_to(self, target: ExecutionState) -> bool:
        return target in self.allowed_transitions()

    def transition(self, target: ExecutionState, *, reason_code: str | None = None) -> ExecutionTransition:
        if self.is_terminal:
            raise InvalidExecutionTransition(f"terminal state {self._state.value} cannot transition")
        if target == self._state:
            raise InvalidExecutionTransition(f"duplicate transition to {target.value}")
        if not self.can_transition_to(target):
            raise InvalidExecutionTransition(f"transition {self._state.value} -> {target.value} is not allowed")

        item = ExecutionTransition(
            len(self._history),
            self._state,
            target,
            datetime.now(UTC),
            reason_code,
        )
        self._state = target
        self._history.append(item)
        return item
