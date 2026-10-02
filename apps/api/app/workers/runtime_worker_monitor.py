from __future__ import annotations

import os

from app.db.session import SessionLocal
from app.services.runtime_managed_service import (
    RuntimeManagedService,
    RuntimeManagedServiceConfiguration,
)
from app.services.runtime_worker_health import RuntimeWorkerHealthService


class RuntimeWorkerMonitorConfigurationError(RuntimeError):
    pass


def run_forever() -> int:
    if SessionLocal is None:
        raise RuntimeWorkerMonitorConfigurationError("database url is not configured")

    poll_interval = max(float(os.getenv("WORKER_MONITOR_INTERVAL_SECONDS", "10")), 1.0)
    heartbeat_interval = max(float(os.getenv("WORKER_MONITOR_HEARTBEAT_INTERVAL_SECONDS", "10")), 1.0)
    stale_after = max(int(os.getenv("WORKER_HEARTBEAT_STALE_SECONDS", "30")), 1)
    batch_limit = max(int(os.getenv("WORKER_MONITOR_BATCH_LIMIT", "100")), 1)
    worker_key = os.getenv("WORKER_MONITOR_ID", "platform-worker-monitor")
    service = RuntimeWorkerHealthService(
        SessionLocal,
        stale_after_seconds=stale_after,
    )

    def cycle() -> dict[str, int]:
        reconciled = service.reconcile_stale(batch_limit=batch_limit)
        return {"reconciled_workers": len(reconciled)}

    return RuntimeManagedService(
        SessionLocal,
        RuntimeManagedServiceConfiguration(
            worker_key=worker_key,
            worker_type="runtime.control_plane",
            capabilities=("runtime.worker.health", "runtime.worker.reconciliation"),
            poll_interval_seconds=poll_interval,
            heartbeat_interval_seconds=heartbeat_interval,
            runtime_version=os.getenv("BUILD_COMMIT"),
        ),
        cycle,
    ).run_forever()


def main() -> int:
    return run_forever()


if __name__ == "__main__":
    raise SystemExit(main())
