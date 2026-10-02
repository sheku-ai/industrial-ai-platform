from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class HeartbeatFaultPlan:
    operation: str
    occurrence: int
    exception_factory: Callable[[], Exception]


class FaultInjectingHeartbeat:
    """Test-only deterministic wrapper for runtime heartbeat operations."""

    def __init__(self, delegate, plan: HeartbeatFaultPlan):
        self._delegate = delegate
        self._plan = plan
        self._counts = {"pulse": 0, "checkpoint": 0, "cancellation_check": 0}

    def _raise_if_planned(self, operation: str) -> None:
        self._counts[operation] += 1
        if operation == self._plan.operation and self._counts[operation] == self._plan.occurrence:
            raise self._plan.exception_factory()

    def pulse(self):
        self._raise_if_planned("pulse")
        return self._delegate.pulse()

    def is_cancellation_requested(self) -> bool:
        self._raise_if_planned("cancellation_check")
        return self._delegate.is_cancellation_requested()

    def raise_if_cancellation_requested(self) -> None:
        self._raise_if_planned("cancellation_check")
        return self._delegate.raise_if_cancellation_requested()

    def checkpoint(self):
        self._raise_if_planned("checkpoint")
        return self._delegate.checkpoint()


class FaultInjectingHeartbeatFactory:
    def __init__(self, delegate_factory, plan: HeartbeatFaultPlan):
        self._delegate_factory = delegate_factory
        self._plan = plan
        self.last_instance: FaultInjectingHeartbeat | None = None

    def __call__(self, **kwargs):
        delegate = self._delegate_factory(**kwargs)
        instance = FaultInjectingHeartbeat(delegate, self._plan)
        self.last_instance = instance
        return instance
