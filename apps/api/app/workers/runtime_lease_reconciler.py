from __future__ import annotations

import os

from app.db.session import SessionLocal
from app.services.runtime_lease_reconciliation import RuntimeLeaseReconciliationService
from app.services.runtime_managed_service import (
    RuntimeManagedService,
    RuntimeManagedServiceConfiguration,
)


class RuntimeLeaseReconcilerConfigurationError(RuntimeError):
    pass


def run_forever() -> int:
    if SessionLocal is None:
        raise RuntimeLeaseReconcilerConfigurationError("database url is not configured")

    poll_interval = max(float(os.getenv("LEASE_RECONCILER_INTERVAL_SECONDS", "10")), 1.0)
    heartbeat_interval = max(float(os.getenv("LEASE_RECONCILER_HEARTBEAT_INTERVAL_SECONDS", "10")), 1.0)
    batch_limit = max(int(os.getenv("LEASE_RECONCILER_BATCH_LIMIT", "100")), 1)
    max_attempts = max(int(os.getenv("LEASE_RECONCILER_DEFAULT_MAX_ATTEMPTS", "3")), 1)
    retry_delay = max(int(os.getenv("LEASE_RECONCILER_DEFAULT_RETRY_DELAY_SECONDS", "0")), 0)
    worker_key = os.getenv("LEASE_RECONCILER_ID", "platform-lease-reconciler")
    service = RuntimeLeaseReconciliationService(
        SessionLocal,
        default_max_attempts=max_attempts,
        default_retry_delay_seconds=retry_delay,
    )

    def cycle() -> dict[str, int]:
        reconciled = service.reconcile(batch_limit=batch_limit)
        return {"reconciled_leases": len(reconciled)}

    return RuntimeManagedService(
        SessionLocal,
        RuntimeManagedServiceConfiguration(
            worker_key=worker_key,
            worker_type="runtime.control_plane",
            capabilities=("runtime.execution.lease_reconciliation",),
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
