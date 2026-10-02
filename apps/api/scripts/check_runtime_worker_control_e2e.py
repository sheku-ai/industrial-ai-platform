from __future__ import annotations

import json
import uuid

from sqlalchemy import delete

from app.db.session import SessionLocal
from app.models.audit import AuditEvent, AuditHistory
from app.models.runtime_worker import RuntimeWorker
from app.services.runtime_worker_control import RuntimeWorkerControl
from app.services.runtime_worker_registry import RuntimeWorkerRegistration, RuntimeWorkerRegistry


def main() -> int:
    if SessionLocal is None:
        raise RuntimeError("database url is not configured")

    suffix = uuid.uuid4().hex
    worker_key = f"control-e2e-{suffix}"
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

        active = control.decision(worker_key=worker_key, instance_id=instance_id)
        control.set_desired_state(worker_key=worker_key, desired_state="paused")
        paused = control.decision(worker_key=worker_key, instance_id=instance_id)
        control.set_desired_state(worker_key=worker_key, desired_state="draining")
        draining = control.decision(worker_key=worker_key, instance_id=instance_id)
        control.set_desired_state(worker_key=worker_key, desired_state="disabled")
        disabled = control.decision(worker_key=worker_key, instance_id=instance_id)
        control.set_desired_state(worker_key=worker_key, desired_state="active")
        resumed = control.decision(worker_key=worker_key, instance_id=instance_id)

        checks = {
            "active_accepts": active.accepts_work and not active.should_exit,
            "paused_blocks": not paused.accepts_work and paused.observed_state == "paused",
            "draining_blocks": not draining.accepts_work and draining.observed_state == "draining",
            "disabled_blocks_without_exit": not disabled.accepts_work
            and not disabled.should_exit
            and disabled.observed_state == "offline",
            "resume_accepts": resumed.accepts_work and resumed.desired_state == "active",
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
