from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select

from app.api.routes.runtime_workers import _read_worker
from app.db.session import SessionLocal
from app.models.runtime_worker import RuntimeWorker
from app.services.runtime_worker_registry import RuntimeWorkerRegistration, RuntimeWorkerRegistry


def main() -> int:
    if SessionLocal is None:
        raise RuntimeError("database url is not configured")

    previous_threshold = os.environ.get("WORKER_HEARTBEAT_STALE_SECONDS")
    os.environ["WORKER_HEARTBEAT_STALE_SECONDS"] = "30"
    now = datetime.now(UTC)
    suffix = uuid.uuid4().hex
    fresh_key = f"api-fresh-worker-{suffix}"
    stale_key = f"api-stale-worker-{suffix}"
    registry = RuntimeWorkerRegistry(SessionLocal, clock=lambda: now)

    try:
        registry.register(
            RuntimeWorkerRegistration(
                worker_key=fresh_key,
                instance_id=f"fresh-instance-{suffix}",
                worker_type="runtime.execution",
            )
        )
        registry.register(
            RuntimeWorkerRegistration(
                worker_key=stale_key,
                instance_id=f"stale-instance-{suffix}",
                worker_type="runtime.execution",
            )
        )

        stale_heartbeat = now - timedelta(seconds=60)
        with SessionLocal() as session:
            fresh = session.scalar(select(RuntimeWorker).where(RuntimeWorker.worker_key == fresh_key))
            stale = session.scalar(select(RuntimeWorker).where(RuntimeWorker.worker_key == stale_key))
            assert fresh is not None and stale is not None
            fresh.observed_state = "ready"
            fresh.heartbeat_at = now
            fresh.last_seen_at = now
            stale.started_at = stale_heartbeat - timedelta(seconds=5)
            stale.observed_state = "ready"
            stale.heartbeat_at = stale_heartbeat
            stale.last_seen_at = stale_heartbeat
            session.commit()

        with SessionLocal() as session:
            fresh = session.scalar(select(RuntimeWorker).where(RuntimeWorker.worker_key == fresh_key))
            stale = session.scalar(select(RuntimeWorker).where(RuntimeWorker.worker_key == stale_key))
            assert fresh is not None and stale is not None
            fresh_read = _read_worker(fresh)
            stale_read = _read_worker(stale)

        checks = {
            "fresh_not_stale": not fresh_read.heartbeat_stale,
            "fresh_accepting_work": fresh_read.accepting_work,
            "fresh_ready": fresh_read.ready,
            "stale_detected": stale_read.heartbeat_stale,
            "stale_not_accepting_work": not stale_read.accepting_work,
            "stale_not_ready": not stale_read.ready,
            "threshold_exposed": fresh_read.heartbeat_stale_after_seconds == 30
            and stale_read.heartbeat_stale_after_seconds == 30,
            "persistent_state_preserved": stale_read.observed_state == "ready",
        }
    finally:
        if previous_threshold is None:
            os.environ.pop("WORKER_HEARTBEAT_STALE_SECONDS", None)
        else:
            os.environ["WORKER_HEARTBEAT_STALE_SECONDS"] = previous_threshold
        with SessionLocal() as session:
            session.execute(delete(RuntimeWorker).where(RuntimeWorker.worker_key.in_([fresh_key, stale_key])))
            session.commit()

    result = {**checks, "passed": all(checks.values())}
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
