from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select

from app.db.session import SessionLocal
from app.models.audit import AuditEvent, AuditHistory
from app.models.runtime_worker import RuntimeWorker
from app.services.runtime_worker_health import RuntimeWorkerHealthService
from app.services.runtime_worker_registry import RuntimeWorkerRegistration, RuntimeWorkerRegistry


def main() -> int:
    if SessionLocal is None:
        raise RuntimeError("database url is not configured")

    now = datetime.now(UTC)
    suffix = uuid.uuid4().hex
    stale_key = f"stale-worker-{suffix}"
    fresh_key = f"fresh-worker-{suffix}"
    registry = RuntimeWorkerRegistry(SessionLocal, clock=lambda: now)
    service = RuntimeWorkerHealthService(
        SessionLocal,
        stale_after_seconds=30,
        clock=lambda: now,
    )
    worker_ids: list[str] = []

    try:
        stale_worker = registry.register(
            RuntimeWorkerRegistration(
                worker_key=stale_key,
                instance_id=f"stale-instance-{suffix}",
                worker_type="runtime.execution",
            )
        )
        fresh_worker = registry.register(
            RuntimeWorkerRegistration(
                worker_key=fresh_key,
                instance_id=f"fresh-instance-{suffix}",
                worker_type="runtime.execution",
            )
        )
        worker_ids = [str(stale_worker.id), str(fresh_worker.id)]

        stale_heartbeat = now - timedelta(seconds=60)
        stale_started_at = stale_heartbeat - timedelta(seconds=5)
        with SessionLocal() as session:
            stale = session.scalar(select(RuntimeWorker).where(RuntimeWorker.worker_key == stale_key))
            fresh = session.scalar(select(RuntimeWorker).where(RuntimeWorker.worker_key == fresh_key))
            assert stale is not None and fresh is not None
            stale.started_at = stale_started_at
            stale.observed_state = "ready"
            stale.heartbeat_at = stale_heartbeat
            stale.last_seen_at = stale_heartbeat
            fresh.observed_state = "ready"
            fresh.heartbeat_at = now
            fresh.last_seen_at = now
            session.commit()

        first = service.reconcile_stale(batch_limit=10)
        second = service.reconcile_stale(batch_limit=10)

        with SessionLocal() as session:
            stale = session.scalar(select(RuntimeWorker).where(RuntimeWorker.worker_key == stale_key))
            fresh = session.scalar(select(RuntimeWorker).where(RuntimeWorker.worker_key == fresh_key))
            assert stale is not None and fresh is not None
            stale_readiness = service.evaluate(stale)
            fresh_readiness = service.evaluate(fresh)
            checks = {
                "stale_reconciled_once": first == [stale_key],
                "repeat_idempotent": second == [],
                "stale_offline": stale.observed_state == "offline",
                "stale_error_code": stale.last_error_code == "heartbeat_stale",
                "last_seen_preserved": stale.last_seen_at == stale_heartbeat,
                "fresh_unchanged": fresh.observed_state == "ready",
                "stale_not_ready": stale_readiness.heartbeat_stale and not stale_readiness.ready,
                "fresh_ready": not fresh_readiness.heartbeat_stale and fresh_readiness.ready,
            }
    finally:
        with SessionLocal() as session:
            if worker_ids:
                session.execute(delete(AuditEvent).where(AuditEvent.resource_id.in_(worker_ids)))
                session.execute(delete(AuditHistory).where(AuditHistory.entity_id.in_(worker_ids)))
            session.execute(delete(RuntimeWorker).where(RuntimeWorker.worker_key.in_([stale_key, fresh_key])))
            session.commit()

    result = {**checks, "passed": all(checks.values())}
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
