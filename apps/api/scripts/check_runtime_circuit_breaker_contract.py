import json
import uuid

from app.services.runtime_capacity import RuntimeCapacityController, RuntimeCapacitySnapshot
from app.services.runtime_circuit_breaker import RuntimeCircuitBreaker
from app.services.runtime_worker_daemon import RuntimeWorkerDaemon


class Clock:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


class Session:
    def __init__(self, counters):
        self.counters = counters

    def commit(self):
        self.counters["commits"] += 1

    def rollback(self):
        self.counters["rollbacks"] += 1

    def close(self):
        self.counters["closes"] += 1


class Worker:
    worker_id = "circuit-contract"

    def __init__(self, counters, outcomes):
        self.counters = counters
        self.outcomes = outcomes

    def run_once(self, organization_id, *, execution_type=None):
        self.counters["worker_calls"] += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def main():
    counters = {
        "sessions": 0,
        "worker_calls": 0,
        "commits": 0,
        "rollbacks": 0,
        "closes": 0,
    }
    outcomes = [RuntimeError("first"), RuntimeError("second"), object()]
    clock = Clock()
    breaker = RuntimeCircuitBreaker(
        failure_threshold=2,
        recovery_timeout_seconds=10,
        clock=clock,
    )

    def session_factory():
        counters["sessions"] += 1
        return Session(counters)

    daemon = RuntimeWorkerDaemon(
        worker_id="circuit-contract",
        session_factory=session_factory,
        worker_factory=lambda session: Worker(counters, outcomes),
        circuit_breaker=breaker,
        capacity_controller=RuntimeCapacityController(
            lambda: RuntimeCapacitySnapshot(
                active_work=0,
                queued_work=1,
                cpu_utilization=0.20,
                memory_utilization=0.30,
            ),
            max_active_work=2,
            max_queued_work=10,
            max_cpu_utilization=0.90,
            max_memory_utilization=0.90,
        ),
    )

    organization_id = uuid.uuid4()
    failures_raised = 0
    for _ in range(2):
        try:
            daemon.run_cycle(organization_id)
        except RuntimeError:
            failures_raised += 1

    open_health = daemon.health()
    sessions_before_rejection = counters["sessions"]
    rejected = daemon.run_cycle(organization_id)
    sessions_after_rejection = counters["sessions"]

    clock.advance(10)
    recovered = daemon.run_cycle(organization_id)
    recovered_health = daemon.health()

    legacy_counters = {
        "sessions": 0,
        "worker_calls": 0,
        "commits": 0,
        "rollbacks": 0,
        "closes": 0,
    }

    def legacy_session_factory():
        legacy_counters["sessions"] += 1
        return Session(legacy_counters)

    legacy = RuntimeWorkerDaemon(
        worker_id="legacy-circuit-disabled",
        session_factory=legacy_session_factory,
        worker_factory=lambda session: Worker(legacy_counters, [object()]),
    )
    legacy_result = legacy.run_cycle(organization_id)
    legacy_health = legacy.health()

    checks = {
        "failures_propagated": failures_raised == 2,
        "failure_transactions_rolled_back": counters["rollbacks"] == 2,
        "circuit_opened_at_threshold": open_health.circuit_state == "open",
        "open_circuit_not_ready": open_health.ready is False,
        "open_circuit_rejects_without_session": rejected.outcome == "circuit_open"
        and sessions_before_rejection == sessions_after_rejection,
        "open_rejection_exposes_metrics": rejected.metrics.get("circuit_reason") == "circuit_open"
        and rejected.metrics.get("capacity_cpu_utilization") == 0.20,
        "recovery_probe_processed": recovered.outcome == "processed" and recovered.claimed is True,
        "successful_probe_closes_circuit": recovered_health.circuit_state == "closed"
        and recovered_health.ready is True,
        "failure_counter_reset": recovered_health.circuit_consecutive_failures == 0,
        "circuit_open_count_observable": recovered_health.circuit_opened_total == 1,
        "circuit_rejection_count_observable": recovered_health.circuit_rejected_total == 1,
        "resource_metrics_preserved": recovered.metrics.get("capacity_memory_utilization") == 0.30,
        "legacy_path_preserved": legacy_result.outcome == "processed" and legacy_health.circuit_state == "disabled",
    }
    passed = all(checks.values())
    print(json.dumps({"passed": passed, **checks}, indent=2, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
