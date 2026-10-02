from __future__ import annotations

import json
import uuid

from sqlalchemy import delete, select

from app.db.session import SessionLocal
from app.models.audit import AuditEvent, AuditHistory
from app.models.runtime_worker import RuntimeWorker
from app.services.runtime_worker_control import RuntimeWorkerControl
from app.services.runtime_worker_registry import RuntimeWorkerRegistration, RuntimeWorkerRegistry


def main() -> int:
    if SessionLocal is None:
        raise RuntimeError("database url is not configured")

    suffix = uuid.uuid4().hex
    worker_key = f"command-audit-{suffix}"
    instance_id = f"instance-{suffix}"
    registry = RuntimeWorkerRegistry(SessionLocal)
    control = RuntimeWorkerControl(SessionLocal)
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
        control.set_desired_state(
            worker_key=worker_key,
            desired_state="paused",
            actor_id="audit-e2e-principal",
        )
        control.set_desired_state(
            worker_key=worker_key,
            desired_state="paused",
            actor_id="audit-e2e-principal",
        )

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

        command_events = [item for item in events if item.metadata_json.get("action") == "desired_state_changed"]
        command_history = [item for item in history if item.action == "desired_state_changed"]
        checks = {
            "event_once": len(command_events) == 1,
            "history_once": len(command_history) == 1,
            "actor_recorded": bool(command_events) and command_events[0].actor_id == "audit-e2e-principal",
            "before_after": bool(command_history)
            and command_history[0].before_state == {"desired_state": "active"}
            and command_history[0].after_state == {"desired_state": "paused"},
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
