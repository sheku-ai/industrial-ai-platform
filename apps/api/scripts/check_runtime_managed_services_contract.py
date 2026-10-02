from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANAGED = ROOT / "app/services/runtime_managed_service.py"
MONITOR = ROOT / "app/workers/runtime_worker_monitor.py"
RECONCILER = ROOT / "app/workers/runtime_lease_reconciler.py"


def main() -> int:
    managed = MANAGED.read_text(encoding="utf-8")
    monitor = MONITOR.read_text(encoding="utf-8")
    reconciler = RECONCILER.read_text(encoding="utf-8")
    checks = {
        "managed_service_exists": MANAGED.exists(),
        "persistent_registration": "RuntimeWorkerRegistration(" in managed,
        "heartbeat_publication": ".heartbeat(" in managed,
        "desired_state_control": ".decision(" in managed,
        "paused_work_blocked": "if not decision.accepts_work:" in managed,
        "busy_state": 'observed_state="busy"' in managed,
        "failure_state": ".mark_offline(" in managed and "error_code=type(exc).__name__" in managed,
        "cycle_metrics": '"cycle_count"' in managed,
        "monitor_managed": "RuntimeManagedService(" in monitor,
        "monitor_worker_type": 'worker_type="runtime.control_plane"' in monitor,
        "monitor_capability": '"runtime.worker.reconciliation"' in monitor,
        "reconciler_managed": "RuntimeManagedService(" in reconciler,
        "reconciler_worker_type": 'worker_type="runtime.control_plane"' in reconciler,
        "reconciler_capability": '"runtime.execution.lease_reconciliation"' in reconciler,
    }
    result = {**checks, "passed": all(checks.values())}
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
