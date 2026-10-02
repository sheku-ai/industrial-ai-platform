import json
import uuid

from app.services.runtime_circuit_breaker import RuntimeCircuitBreaker
from app.services.runtime_organization_quota import OrganizationQuota, OrganizationQuotaController, OrganizationUsage
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
    worker_id = "quota-contract"

    def __init__(self, counters):
        self.counters = counters

    def run_once(self, organization_id, *, execution_type=None):
        self.counters["worker_calls"] += 1
        return object()


def main():
    allowed_org = uuid.uuid4()
    active_org = uuid.uuid4()
    queue_org = uuid.uuid4()
    rate_org = uuid.uuid4()
    volume_org = uuid.uuid4()
    default_org = uuid.uuid4()

    quotas = {
        allowed_org: OrganizationQuota(2, 10, 100, 1_000_000),
        active_org: OrganizationQuota(max_active_work=1),
        queue_org: OrganizationQuota(max_queued_work=5),
        rate_org: OrganizationQuota(max_started_in_window=3),
        volume_org: OrganizationQuota(max_source_bytes_in_window=1000),
    }
    usage = {
        allowed_org: OrganizationUsage(1, 2, 5, 500),
        active_org: OrganizationUsage(active_work=1),
        queue_org: OrganizationUsage(queued_work=6),
        rate_org: OrganizationUsage(started_in_window=3),
        volume_org: OrganizationUsage(source_bytes_in_window=1000),
        default_org: OrganizationUsage(),
    }
    controller = OrganizationQuotaController(quotas.get, usage.__getitem__)

    counters = {"sessions": 0, "worker_calls": 0, "commits": 0, "rollbacks": 0, "closes": 0}

    def session_factory():
        counters["sessions"] += 1
        return Session(counters)

    daemon = RuntimeWorkerDaemon(
        worker_id="quota-contract",
        session_factory=session_factory,
        worker_factory=lambda session: Worker(counters),
        quota_controller=controller,
        circuit_breaker=RuntimeCircuitBreaker(failure_threshold=1, recovery_timeout_seconds=30),
    )

    allowed = daemon.run_cycle(allowed_org)
    sessions_before_rejections = counters["sessions"]
    active = daemon.run_cycle(active_org)
    queue = daemon.run_cycle(queue_org)
    rate = daemon.run_cycle(rate_org)
    volume = daemon.run_cycle(volume_org)
    sessions_after_rejections = counters["sessions"]
    default = daemon.run_cycle(default_org)
    health = daemon.health()

    checks = {
        "allowed_organization_processed": allowed.outcome == "processed" and allowed.claimed,
        "active_quota_rejected": active.metrics.get("organization_quota_reason") == "organization_active_work_limit",
        "queue_quota_rejected": queue.metrics.get("organization_quota_reason") == "organization_queue_limit",
        "rate_quota_rejected": rate.metrics.get("organization_quota_reason") == "organization_execution_rate_limit",
        "volume_quota_rejected": volume.metrics.get("organization_quota_reason") == "organization_source_bytes_limit",
        "quota_rejections_open_no_sessions": sessions_before_rejections == sessions_after_rejections,
        "quota_rejections_claim_no_work": counters["worker_calls"] == 2,
        "default_organization_allowed": default.outcome == "processed",
        "usage_metrics_propagated": allowed.metrics.get("organization_usage_started_in_window") == 5,
        "quota_rejections_observable": health.quota_rejected_total == 4,
        "quota_does_not_open_circuit": health.circuit_state == "closed" and health.circuit_opened_total == 0,
        "transactions_preserved": counters["commits"] == 2 and counters["rollbacks"] == 0 and counters["closes"] == 2,
    }
    passed = all(checks.values())
    print(json.dumps({"passed": passed, **checks}, indent=2, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
