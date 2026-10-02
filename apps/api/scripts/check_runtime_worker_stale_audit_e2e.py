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
    worker_key = f"stale-audit-{suffix}"
    instance_id = f"instance-{suffix}"
    registry = RuntimeWorkerRegistry(SessionLocal, clock=lambda: now)
    health = RuntimeWorkerHealthService(SessionLocal, stale_after_seconds=30, clock=lambda: now)
    worker_id = None

    try:
        worker = registry.register(
            RuntimeWorkerRegistration(
                worker_key=worker_key,
                instance_id=instance_id,
                worker_type="runtime.execution",
            )
        )
        worker_id = str(worker.id)
        stale_heartbeat = now - timedelta(seconds=60)
        with SessionLocal() as session:
            persisted = session.scalar(select(RuntimeWorker).where(RuntimeWorker.worker_key == worker_key))
            assert persisted is not None
            persisted.started_at = stale_heartbeat - timedelta(seconds=5)
            persisted.observed_state = "ready"
            persisted.heartbeat_at = stale_heartbeat
            persisted.last_seen_at = stale_heartbeat
            session.commit()

        first = health.reconcile_stale(batch_limit=10)
        second = health.reconcile_stale(batch_limit=10)

        with SessionLocal() as session:
            events = list(
                session.scalars(
                    select(AuditEvent).where(
                        AuditEvent.resource_type == "runtime.worker",
                        AuditEvent.resource_id == worker_id,
                    )
                ).all()
            )
            history = list(
                session.scalars(
                    select(AuditHistory).where(
                        AuditHistory.entity_type == "runtime.worker",
                        AuditHistory.entity_id == worker_id,
                    )
                ).all()
            )

        stale_events = [item for item in events if item.metadata_json.get("action") == "heartbeat_stale_reconciled"]
        stale_history = [item for item in history if item.action == "heartbeat_stale_reconciled"]
        checks = {
            "reconciled_once": first == [worker_key],
            "repeat_idempotent": second == [],
            "event_once": len(stale_events) == 1,
            "history_once": len(stale_history) == 1,
            "system_actor": bool(stale_events) and stale_events[0].actor_id == "runtime-worker-monitor",
            "after_offline": bool(stale_history) and stale_history[0].after_state.get("observed_state") == "offline",
        }
    finally:
        with SessionLocal() as session:
            if worker_id:
                session.execute(delete(AuditEvent).where(AuditEvent.resource_id == worker_id))
                session.execute(delete(AuditHistory).where(AuditHistory.entity_id == worker_id))
            session.execute(delete(RuntimeWorker).where(RuntimeWorker.worker_key == worker_key))
            session.commit()

    result = {**checks, "passed": all(checks.values())}
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
