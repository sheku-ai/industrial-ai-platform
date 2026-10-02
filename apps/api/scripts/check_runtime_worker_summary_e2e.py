from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select

from app.db.session import SessionLocal
from app.models.runtime_worker import RuntimeWorker
from app.services.runtime_worker_health import RuntimeWorkerHealthService
from app.services.runtime_worker_registry import RuntimeWorkerRegistration, RuntimeWorkerRegistry
from app.services.runtime_worker_summary import build_runtime_worker_summary


def main() -> int:
    if SessionLocal is None:
        raise RuntimeError("database url is not configured")

    now = datetime.now(UTC)
    suffix = uuid.uuid4().hex
    keys = [f"summary-fresh-{suffix}", f"summary-stale-{suffix}"]
    registry = RuntimeWorkerRegistry(SessionLocal, clock=lambda: now)

    try:
        for key in keys:
            registry.register(
                RuntimeWorkerRegistration(
                    worker_key=key,
                    instance_id=f"instance-{key}",
                    worker_type="runtime.test",
                )
            )
        stale_at = now - timedelta(seconds=60)
        with SessionLocal() as session:
            workers = list(session.scalars(select(RuntimeWorker).where(RuntimeWorker.worker_key.in_(keys))).all())
            workers[0].observed_state = "ready"
            workers[0].heartbeat_at = now
            workers[1].started_at = stale_at - timedelta(seconds=5)
            workers[1].observed_state = "ready"
            workers[1].heartbeat_at = stale_at
            session.commit()

        with SessionLocal() as session:
            workers = list(session.scalars(select(RuntimeWorker).where(RuntimeWorker.worker_key.in_(keys))).all())
            summary = build_runtime_worker_summary(
                workers,
                health_service=RuntimeWorkerHealthService(SessionLocal, stale_after_seconds=30, clock=lambda: now),
            )
        checks = {
            "two_workers": summary.total_workers == 2,
            "one_ready": summary.ready_workers == 1,
            "one_accepting": summary.accepting_work == 1,
            "one_stale": summary.stale_workers == 1,
            "one_degraded": summary.degraded_workers == 1,
            "half_capacity": summary.available_capacity_ratio == 0.5,
        }
    finally:
        with SessionLocal() as session:
            session.execute(delete(RuntimeWorker).where(RuntimeWorker.worker_key.in_(keys)))
            session.commit()

    result = {**checks, "passed": all(checks.values())}
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
