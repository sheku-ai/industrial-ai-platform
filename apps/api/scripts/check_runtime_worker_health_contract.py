from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVICE = ROOT / "app/services/runtime_worker_health.py"
MONITOR = ROOT / "app/workers/runtime_worker_monitor.py"


def main() -> int:
    service = SERVICE.read_text(encoding="utf-8")
    monitor = MONITOR.read_text(encoding="utf-8")
    checks = {
        "service_exists": SERVICE.exists(),
        "monitor_exists": MONITOR.exists(),
        "readiness_policy": "class RuntimeWorkerReadiness" in service,
        "evaluate_method": "def evaluate(" in service,
        "reconcile_method": "def reconcile_stale(" in service,
        "stale_error_code": '"heartbeat_stale"' in service,
        "skip_locked": "skip_locked=True" in service,
        "batch_limit": "batch_limit" in service,
        "last_seen_preserved": "worker.last_seen_at =" not in service,
        "monitor_interval_configurable": "WORKER_MONITOR_INTERVAL_SECONDS" in monitor,
        "stale_threshold_configurable": "WORKER_HEARTBEAT_STALE_SECONDS" in monitor,
        "monitor_batch_configurable": "WORKER_MONITOR_BATCH_LIMIT" in monitor,
        "monitor_runs_reconciliation": "service.reconcile_stale(" in monitor,
    }
    result = {**checks, "passed": all(checks.values())}
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
