from __future__ import annotations

import json
import uuid

from sqlalchemy import delete

from app.api.dependencies.runtime_context import RuntimeRequestContext
from app.api.routes.runtime_workers import list_worker_events, list_worker_history
from app.db.session import SessionLocal
from app.models.audit import AuditEvent, AuditHistory
from app.models.runtime_worker import RuntimeWorker
from app.services.runtime_worker_control import RuntimeWorkerControl
from app.services.runtime_worker_registry import RuntimeWorkerRegistration, RuntimeWorkerRegistry


def main() -> int:
    if SessionLocal is None:
        raise RuntimeError("database url is not configured")

    suffix = uuid.uuid4().hex
    worker_key = f"history-api-{suffix}"
    worker_id = None
    context = RuntimeRequestContext(
        scope_type="platform",
        organization_id=None,
        actor_reference="history-api-e2e",
        permissions=frozenset({"control_plane.workers:read"}),
    )

    try:
        worker = RuntimeWorkerRegistry(SessionLocal).register(
            RuntimeWorkerRegistration(
                worker_key=worker_key,
                instance_id=f"instance-{suffix}",
                worker_type="runtime.execution",
            )
        )
        worker_id = str(worker.id)
        RuntimeWorkerControl(SessionLocal).set_desired_state(
            worker_key=worker_key,
            desired_state="paused",
            actor_id="history-api-e2e",
        )
        RuntimeWorkerControl(SessionLocal).set_desired_state(
            worker_key=worker_key,
            desired_state="active",
            actor_id="history-api-e2e",
        )

        with SessionLocal() as session:
            events = list_worker_events(
                worker_key=worker_key,
                limit=50,
                context=context,
                db=session,
            )
            history = list_worker_history(
                worker_key=worker_key,
                limit=50,
                context=context,
                db=session,
            )

        checks = {
            "events_returned": len(events) == 2,
            "history_returned": len(history) == 2,
            "events_newest_first": events[0].created_at >= events[1].created_at,
            "history_newest_first": history[0].created_at >= history[1].created_at,
            "events_scoped_to_worker": all(item.resource_id == worker_id for item in events),
            "history_scoped_to_worker": all(item.entity_id == worker_id for item in history),
            "events_are_platform_global": all(item.organization_id is None for item in events),
            "history_is_platform_global": all(item.organization_id is None for item in history),
            "actions_exposed": all(item.action == "desired_state_changed" for item in history),
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
