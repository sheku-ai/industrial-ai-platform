from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVICE = ROOT / "app/services/runtime_lease_reconciliation.py"
WORKER = ROOT / "app/workers/runtime_lease_reconciler.py"


def main() -> int:
    service = SERVICE.read_text(encoding="utf-8")
    worker = WORKER.read_text(encoding="utf-8")
    checks = {
        "service_exists": SERVICE.exists(),
        "worker_exists": WORKER.exists(),
        "expired_active_query": 'status.in_(["leased", "running"])' in service,
        "expiry_cutoff": "lease_expires_at <= now" in service,
        "skip_locked": "skip_locked=True" in service,
        "atomic_lifecycle_expire": "lifecycle.expire(" in service,
        "retry_scheduling": "lifecycle.retry(" in service,
        "retry_exhaustion": 'reason_code="lease_retry_exhausted"' in service,
        "invalid_payload_dead_letter": 'reason_code="invalid_execution_payload"' in service,
        "attempt_metrics": '"lease_reconciled": True' in service,
        "execution_metrics": '"lease_reconciliation"' in service,
        "policy_max_attempts": 'retry.get("max_attempts"' in service,
        "policy_retry_delay": 'retry.get("delay_seconds"' in service,
        "monitor_interval": "LEASE_RECONCILER_INTERVAL_SECONDS" in worker,
        "monitor_batch": "LEASE_RECONCILER_BATCH_LIMIT" in worker,
        "monitor_runs": "service.reconcile(" in worker,
    }
    result = {**checks, "passed": all(checks.values())}
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
