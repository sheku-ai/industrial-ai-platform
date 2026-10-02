import json
import uuid

from app.services.runtime_capacity import RuntimeCapacityController, RuntimeCapacitySnapshot
from app.services.runtime_worker_daemon import RuntimeWorkerDaemon


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
    worker_id = "capacity-contract"

    def __init__(self, counters, item):
        self.counters = counters
        self.item = item

    def run_once(self, organization_id, *, execution_type=None):
        self.counters["worker_calls"] += 1
        return self.item


def _daemon(snapshot, *, item=object(), thresholds=None):
    counters = {
        "sessions": 0,
        "worker_calls": 0,
        "commits": 0,
        "rollbacks": 0,
        "closes": 0,
    }

    def session_factory():
        counters["sessions"] += 1
        return Session(counters)

    controller = RuntimeCapacityController(
        lambda: snapshot,
        **(thresholds or {}),
    )
    daemon = RuntimeWorkerDaemon(
        worker_id="capacity-contract",
        session_factory=session_factory,
        worker_factory=lambda session: Worker(counters, item),
        capacity_controller=controller,
    )
    return daemon, counters


def main():
    organization_id = uuid.uuid4()

    active_daemon, active_counters = _daemon(
        RuntimeCapacitySnapshot(active_work=1),
        thresholds={"max_active_work": 1},
    )
    active_result = active_daemon.run_cycle(organization_id)

    queue_daemon, queue_counters = _daemon(
        RuntimeCapacitySnapshot(active_work=0, queued_work=11),
        thresholds={"max_active_work": 2, "max_queued_work": 10},
    )
    queue_result = queue_daemon.run_cycle(organization_id)

    cpu_daemon, cpu_counters = _daemon(
        RuntimeCapacitySnapshot(active_work=0, cpu_utilization=0.91),
        thresholds={"max_active_work": 2, "max_cpu_utilization": 0.90},
    )
    cpu_result = cpu_daemon.run_cycle(organization_id)

    memory_daemon, memory_counters = _daemon(
        RuntimeCapacitySnapshot(active_work=0, memory_utilization=0.86),
        thresholds={"max_active_work": 2, "max_memory_utilization": 0.85},
    )
    memory_result = memory_daemon.run_cycle(organization_id)

    disk_daemon, disk_counters = _daemon(
        RuntimeCapacitySnapshot(active_work=0, disk_utilization=0.96),
        thresholds={"max_active_work": 2, "max_disk_utilization": 0.95},
    )
    disk_result = disk_daemon.run_cycle(organization_id)

    gpu_daemon, gpu_counters = _daemon(
        RuntimeCapacitySnapshot(active_work=0, gpu_utilization=0.92),
        thresholds={"max_active_work": 2, "max_gpu_utilization": 0.90},
    )
    gpu_result = gpu_daemon.run_cycle(organization_id)

    admitted_daemon, admitted_counters = _daemon(
        RuntimeCapacitySnapshot(
            active_work=0,
            queued_work=2,
            cpu_utilization=0.25,
            memory_utilization=0.35,
            disk_utilization=0.45,
            gpu_utilization=None,
        ),
        thresholds={
            "max_active_work": 2,
            "max_queued_work": 10,
            "max_cpu_utilization": 0.90,
            "max_memory_utilization": 0.85,
            "max_disk_utilization": 0.95,
            "max_gpu_utilization": 0.90,
        },
    )
    admitted_result = admitted_daemon.run_cycle(organization_id)
    admitted_health = admitted_daemon.health()

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

    legacy_daemon = RuntimeWorkerDaemon(
        worker_id="legacy-compatible",
        session_factory=legacy_session_factory,
        worker_factory=lambda session: Worker(legacy_counters, object()),
    )
    legacy_result = legacy_daemon.run_cycle(organization_id)

    blocked_counters = (
        active_counters,
        queue_counters,
        cpu_counters,
        memory_counters,
        disk_counters,
        gpu_counters,
    )
    checks = {
        "active_limit_backpressure": active_result.outcome == "backpressure"
        and active_result.metrics.get("capacity_reason") == "active_work_limit",
        "queue_backpressure": queue_result.outcome == "backpressure"
        and queue_result.metrics.get("capacity_reason") == "queue_backpressure",
        "cpu_backpressure": cpu_result.outcome == "backpressure"
        and cpu_result.metrics.get("capacity_reason") == "cpu_backpressure",
        "memory_backpressure": memory_result.outcome == "backpressure"
        and memory_result.metrics.get("capacity_reason") == "memory_backpressure",
        "disk_backpressure": disk_result.outcome == "backpressure"
        and disk_result.metrics.get("capacity_reason") == "disk_backpressure",
        "gpu_backpressure": gpu_result.outcome == "backpressure"
        and gpu_result.metrics.get("capacity_reason") == "gpu_backpressure",
        "blocked_cycles_open_no_sessions": all(counters["sessions"] == 0 for counters in blocked_counters),
        "blocked_cycles_claim_no_work": all(counters["worker_calls"] == 0 for counters in blocked_counters),
        "admitted_cycle_processed": admitted_result.outcome == "processed" and admitted_result.claimed is True,
        "admitted_cycle_committed": admitted_counters["commits"] == 1 and admitted_counters["closes"] == 1,
        "capacity_metrics_propagated": admitted_result.metrics
        == {
            "capacity_admitted": True,
            "capacity_reason": "admitted",
            "capacity_active_work": 0,
            "capacity_queued_work": 2,
            "capacity_cpu_utilization": 0.25,
            "capacity_memory_utilization": 0.35,
            "capacity_disk_utilization": 0.45,
            "capacity_gpu_utilization": None,
        },
        "health_exposes_capacity": admitted_health.last_capacity_metrics.get("capacity_reason") == "admitted",
        "health_counts_backpressure": active_daemon.health().backpressure_total == 1,
        "legacy_path_preserved": legacy_result.outcome == "processed" and legacy_counters["commits"] == 1,
    }
    passed = all(checks.values())
    print(json.dumps({"passed": passed, **checks}, indent=2, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
