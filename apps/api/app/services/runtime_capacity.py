from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class RuntimeCapacitySnapshot:
    active_work: int = 0
    queued_work: int = 0
    cpu_utilization: float | None = None
    memory_utilization: float | None = None
    disk_utilization: float | None = None
    gpu_utilization: float | None = None


@dataclass(frozen=True)
class RuntimeCapacityDecision:
    admitted: bool
    reason: str
    snapshot: RuntimeCapacitySnapshot


class RuntimeCapacityController:
    """Provider-neutral admission control for bounded worker execution."""

    def __init__(
        self,
        snapshot_provider: Callable[[], RuntimeCapacitySnapshot],
        *,
        max_active_work: int = 1,
        max_queued_work: int | None = None,
        max_cpu_utilization: float | None = None,
        max_memory_utilization: float | None = None,
        max_disk_utilization: float | None = None,
        max_gpu_utilization: float | None = None,
    ) -> None:
        if not callable(snapshot_provider):
            raise ValueError("snapshot_provider is required")
        if max_active_work < 1:
            raise ValueError("max_active_work must be greater than zero")
        if max_queued_work is not None and max_queued_work < 0:
            raise ValueError("max_queued_work must be zero or greater")
        _validate_ratio(max_cpu_utilization, "max_cpu_utilization")
        _validate_ratio(max_memory_utilization, "max_memory_utilization")
        _validate_ratio(max_disk_utilization, "max_disk_utilization")
        _validate_ratio(max_gpu_utilization, "max_gpu_utilization")
        self._snapshot_provider = snapshot_provider
        self.max_active_work = max_active_work
        self.max_queued_work = max_queued_work
        self.max_cpu_utilization = max_cpu_utilization
        self.max_memory_utilization = max_memory_utilization
        self.max_disk_utilization = max_disk_utilization
        self.max_gpu_utilization = max_gpu_utilization

    def evaluate(self) -> RuntimeCapacityDecision:
        snapshot = self._snapshot_provider()
        if snapshot.active_work >= self.max_active_work:
            return RuntimeCapacityDecision(False, "active_work_limit", snapshot)
        if self.max_queued_work is not None and snapshot.queued_work > self.max_queued_work:
            return RuntimeCapacityDecision(False, "queue_backpressure", snapshot)
        if _at_or_above(snapshot.cpu_utilization, self.max_cpu_utilization):
            return RuntimeCapacityDecision(False, "cpu_backpressure", snapshot)
        if _at_or_above(snapshot.memory_utilization, self.max_memory_utilization):
            return RuntimeCapacityDecision(False, "memory_backpressure", snapshot)
        if _at_or_above(snapshot.disk_utilization, self.max_disk_utilization):
            return RuntimeCapacityDecision(False, "disk_backpressure", snapshot)
        if _at_or_above(snapshot.gpu_utilization, self.max_gpu_utilization):
            return RuntimeCapacityDecision(False, "gpu_backpressure", snapshot)
        return RuntimeCapacityDecision(True, "admitted", snapshot)


def capacity_metrics(decision: RuntimeCapacityDecision) -> Mapping[str, int | float | str | bool | None]:
    snapshot = decision.snapshot
    return {
        "capacity_admitted": decision.admitted,
        "capacity_reason": decision.reason,
        "capacity_active_work": snapshot.active_work,
        "capacity_queued_work": snapshot.queued_work,
        "capacity_cpu_utilization": snapshot.cpu_utilization,
        "capacity_memory_utilization": snapshot.memory_utilization,
        "capacity_disk_utilization": snapshot.disk_utilization,
        "capacity_gpu_utilization": snapshot.gpu_utilization,
    }


def _at_or_above(value: float | None, threshold: float | None) -> bool:
    return threshold is not None and value is not None and value >= threshold


def _validate_ratio(value: float | None, name: str) -> None:
    if value is not None and not 0 < value <= 1:
        raise ValueError(f"{name} must be greater than zero and at most one")
