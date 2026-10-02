from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.runtime_worker import RuntimeWorker


def main() -> int:
    if SessionLocal is None:
        raise RuntimeError("database url is not configured")

    expected = {
        "platform-worker-monitor": "runtime.worker.reconciliation",
        "platform-lease-reconciler": "runtime.execution.lease_reconciliation",
    }
    now = datetime.now(UTC)
    with SessionLocal() as session:
        workers = list(
            session.scalars(select(RuntimeWorker).where(RuntimeWorker.worker_key.in_(expected.keys()))).all()
        )

    by_key = {worker.worker_key: worker for worker in workers}
    checks = {"all_registered": set(by_key) == set(expected)}
    for key, capability in expected.items():
        worker = by_key.get(key)
        name = key.replace("-", "_")
        checks[f"{name}_type"] = bool(worker and worker.worker_type == "runtime.control_plane")
        checks[f"{name}_capability"] = bool(worker and capability in worker.capabilities)
        checks[f"{name}_heartbeat"] = bool(
            worker and worker.heartbeat_at and worker.heartbeat_at >= now - timedelta(seconds=60)
        )
        checks[f"{name}_state"] = bool(
            worker and worker.desired_state == "active" and worker.observed_state in {"ready", "busy"}
        )
        checks[f"{name}_metrics"] = bool(worker and "cycle_count" in worker.metrics)

    result = {**checks, "passed": all(checks.values())}
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
