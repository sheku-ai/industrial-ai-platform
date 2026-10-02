from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from app.services.runtime_capacity import RuntimeCapacityController, capacity_metrics
from app.services.runtime_circuit_breaker import RuntimeCircuitBreaker
from app.services.runtime_organization_quota import (
    OrganizationQuotaController,
    organization_quota_metrics,
)


class WorkerCycle(Protocol):
    worker_id: str

    def run_once(self, organization_id: UUID, *, execution_type: str | None = None): ...


@dataclass(frozen=True)
class RuntimeWorkerDaemonHealth:
    worker_id: str
    live: bool
    ready: bool
    stop_requested: bool
    active: bool
    cycles_total: int
    claimed_total: int
    idle_total: int
    failed_cycles_total: int
    backpressure_total: int
    quota_rejected_total: int
    circuit_rejected_total: int
    circuit_state: str
    circuit_consecutive_failures: int
    circuit_opened_total: int
    last_cycle_started_at: datetime | None
    last_cycle_finished_at: datetime | None
    last_error_code: str | None
    last_backpressure_reason: str | None
    last_quota_reason: str | None
    last_circuit_reason: str | None
    last_capacity_metrics: Mapping[str, object] = field(default_factory=dict)
    last_quota_metrics: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class RuntimeWorkerCycleResult:
    outcome: str
    claimed: bool
    metrics: Mapping[str, object] = field(default_factory=dict)


class RuntimeWorkerDaemon:
    """Deployment-neutral host boundary for one transactional worker cycle."""

    def __init__(
        self,
        *,
        worker_id: str,
        session_factory: Callable[[], object],
        worker_factory: Callable[[object], WorkerCycle],
        capacity_controller: RuntimeCapacityController | None = None,
        quota_controller: OrganizationQuotaController | None = None,
        circuit_breaker: RuntimeCircuitBreaker | None = None,
    ) -> None:
        canonical_worker_id = worker_id.strip() if isinstance(worker_id, str) else ""
        if not canonical_worker_id:
            raise ValueError("worker_id is required")
        if not callable(session_factory):
            raise ValueError("session_factory is required")
        if not callable(worker_factory):
            raise ValueError("worker_factory is required")

        self.worker_id = canonical_worker_id
        self.session_factory = session_factory
        self.worker_factory = worker_factory
        self.capacity_controller = capacity_controller
        self.quota_controller = quota_controller
        self.circuit_breaker = circuit_breaker
        self._stop_requested = False
        self._active = False
        self._cycles_total = 0
        self._claimed_total = 0
        self._idle_total = 0
        self._failed_cycles_total = 0
        self._backpressure_total = 0
        self._quota_rejected_total = 0
        self._last_cycle_started_at: datetime | None = None
        self._last_cycle_finished_at: datetime | None = None
        self._last_error_code: str | None = None
        self._last_backpressure_reason: str | None = None
        self._last_quota_reason: str | None = None
        self._last_circuit_reason: str | None = None
        self._last_capacity_metrics: dict[str, object] = {}
        self._last_quota_metrics: dict[str, object] = {}

    @staticmethod
    def _utcnow() -> datetime:
        return datetime.now(UTC)

    def request_stop(self) -> None:
        self._stop_requested = True

    def run_cycle(
        self,
        organization_id: UUID,
        *,
        execution_type: str | None = None,
    ) -> RuntimeWorkerCycleResult:
        if self._stop_requested:
            return RuntimeWorkerCycleResult(outcome="stopped", claimed=False)
        if self._active:
            raise RuntimeError("worker daemon cycle is already active")

        metrics: dict[str, object] = {}
        if self.capacity_controller is not None:
            decision = self.capacity_controller.evaluate()
            metrics.update(capacity_metrics(decision))
            self._last_capacity_metrics = dict(metrics)
            if not decision.admitted:
                self._backpressure_total += 1
                self._last_backpressure_reason = decision.reason
                return RuntimeWorkerCycleResult(
                    outcome="backpressure",
                    claimed=False,
                    metrics=metrics,
                )
            self._last_backpressure_reason = None
        else:
            self._last_capacity_metrics = {}

        if self.quota_controller is not None:
            quota_decision = self.quota_controller.evaluate(organization_id)
            quota_values = organization_quota_metrics(quota_decision)
            metrics.update(quota_values)
            self._last_quota_metrics = dict(quota_values)
            self._last_quota_reason = quota_decision.reason
            if not quota_decision.admitted:
                self._quota_rejected_total += 1
                return RuntimeWorkerCycleResult(
                    outcome="quota_rejected",
                    claimed=False,
                    metrics=metrics,
                )
        else:
            self._last_quota_metrics = {}
            self._last_quota_reason = None

        if self.circuit_breaker is not None:
            circuit_decision = self.circuit_breaker.before_call()
            self._last_circuit_reason = circuit_decision.reason
            metrics.update(
                {
                    "circuit_allowed": circuit_decision.allowed,
                    "circuit_state": circuit_decision.state,
                    "circuit_reason": circuit_decision.reason,
                    "circuit_consecutive_failures": circuit_decision.consecutive_failures,
                }
            )
            if not circuit_decision.allowed:
                return RuntimeWorkerCycleResult(
                    outcome="circuit_open",
                    claimed=False,
                    metrics=metrics,
                )
        else:
            self._last_circuit_reason = None

        self._active = True
        self._cycles_total += 1
        self._last_cycle_started_at = self._utcnow()
        session = self.session_factory()
        try:
            worker = self.worker_factory(session)
            item = worker.run_once(organization_id, execution_type=execution_type)
            session.commit()
            self._last_error_code = None
            if self.circuit_breaker is not None:
                self.circuit_breaker.record_success()
                metrics["circuit_state_after"] = "closed"
            if item is None:
                self._idle_total += 1
                return RuntimeWorkerCycleResult(
                    outcome="idle",
                    claimed=False,
                    metrics=metrics,
                )
            self._claimed_total += 1
            return RuntimeWorkerCycleResult(
                outcome="processed",
                claimed=True,
                metrics=metrics,
            )
        except Exception as exc:
            self._failed_cycles_total += 1
            self._last_error_code = getattr(exc, "code", None) or exc.__class__.__name__
            if self.circuit_breaker is not None:
                self.circuit_breaker.record_failure(self._last_error_code)
            session.rollback()
            raise
        finally:
            session.close()
            self._active = False
            self._last_cycle_finished_at = self._utcnow()

    def health(self) -> RuntimeWorkerDaemonHealth:
        if self.circuit_breaker is None:
            circuit_state = "disabled"
            circuit_failures = 0
            circuit_opened_total = 0
            circuit_rejected_total = 0
        else:
            snapshot = self.circuit_breaker.snapshot()
            circuit_state = snapshot.state
            circuit_failures = snapshot.consecutive_failures
            circuit_opened_total = snapshot.opened_total
            circuit_rejected_total = snapshot.rejected_total
        return RuntimeWorkerDaemonHealth(
            worker_id=self.worker_id,
            live=True,
            ready=(not self._stop_requested and not self._active and circuit_state not in {"open"}),
            stop_requested=self._stop_requested,
            active=self._active,
            cycles_total=self._cycles_total,
            claimed_total=self._claimed_total,
            idle_total=self._idle_total,
            failed_cycles_total=self._failed_cycles_total,
            backpressure_total=self._backpressure_total,
            quota_rejected_total=self._quota_rejected_total,
            circuit_rejected_total=circuit_rejected_total,
            circuit_state=circuit_state,
            circuit_consecutive_failures=circuit_failures,
            circuit_opened_total=circuit_opened_total,
            last_cycle_started_at=self._last_cycle_started_at,
            last_cycle_finished_at=self._last_cycle_finished_at,
            last_error_code=self._last_error_code,
            last_backpressure_reason=self._last_backpressure_reason,
            last_quota_reason=self._last_quota_reason,
            last_circuit_reason=self._last_circuit_reason,
            last_capacity_metrics=dict(self._last_capacity_metrics),
            last_quota_metrics=dict(self._last_quota_metrics),
        )
