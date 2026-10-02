from __future__ import annotations

import json
import uuid
from concurrent.futures import ThreadPoolExecutor
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
    worker_key = f"heartbeat-reconciliation-{suffix}"
    instance_id = f"instance-{suffix}"
    registry = RuntimeWorkerRegistry(SessionLocal, clock=lambda: now)
    health = RuntimeWorkerHealthService(
        SessionLocal,
        stale_after_seconds=30,
        clock=lambda: now,
    )
    worker_id: str | None = None

    try:
        worker = registry.register(
            RuntimeWorkerRegistration(
                worker_key=worker_key,
                instance_id=instance_id,
                worker_type="runtime.test",
            )
        )
        worker_id = str(worker.id)
        stale_at = now - timedelta(seconds=60)
        with SessionLocal() as session:
            persisted = session.scalar(select(RuntimeWorker).where(RuntimeWorker.worker_key == worker_key))
            assert persisted is not None
            persisted.started_at = stale_at - timedelta(seconds=5)
            persisted.observed_state = "ready"
            persisted.heartbeat_at = stale_at
            persisted.last_seen_at = stale_at
            session.commit()

        with ThreadPoolExecutor(max_workers=2) as pool:
            heartbeat_future = pool.submit(
                registry.heartbeat,
                worker_key=worker_key,
                instance_id=instance_id,
                observed_state="ready",
                metrics={"concurrency_probe": True},
            )
            reconciliation_future = pool.submit(
                health.reconcile_stale,
                batch_limit=10,
            )
            heartbeat = heartbeat_future.result()
            reconciled = reconciliation_future.result()

        with SessionLocal() as session:
            persisted = session.scalar(select(RuntimeWorker).where(RuntimeWorker.worker_key == worker_key))
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
            assert persisted is not None
            stale_events = [item for item in events if item.metadata_json.get("action") == "heartbeat_stale_reconciled"]
            stale_history = [item for item in history if item.action == "heartbeat_stale_reconciled"]
            checks = {
                "heartbeat_completed": heartbeat.heartbeat_at == now,
                "latest_heartbeat_preserved": persisted.heartbeat_at == now,
                "latest_seen_preserved": persisted.last_seen_at == now,
                "worker_ready_after_race": persisted.observed_state == "ready",
                "heartbeat_metrics_preserved": persisted.metrics.get("concurrency_probe") is True,
                "reconciled_at_most_once": reconciled in ([], [worker_key]),
                "audit_at_most_once": len(stale_events) <= 1 and len(stale_history) <= 1,
            }
    finally:
        with SessionLocal() as session:
            if worker_id:
                session.execute(delete(AuditEvent).where(AuditEvent.resource_id == worker_id))
                session.execute(delete(AuditHistory).where(AuditHistory.entity_id == worker_id))
            session.execute(delete(RuntimeWorker).where(RuntimeWorker.worker_key == worker_key))
            session.commit()

    result = {**checks, "passed": all(checks.values())}
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
