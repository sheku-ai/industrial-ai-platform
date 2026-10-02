from __future__ import annotations

import json
import uuid

from sqlalchemy import delete, select

from app.db.session import SessionLocal
from app.models.runtime_worker import RuntimeWorker
from app.services.runtime_worker_registry import (
    RuntimeWorkerRegistration,
    RuntimeWorkerRegistry,
    RuntimeWorkerRegistryError,
)


def main() -> int:
    if SessionLocal is None:
        raise RuntimeError("database url is not configured")

    suffix = uuid.uuid4().hex
    worker_key = f"worker-e2e-{suffix}"
    first_instance = f"instance-a-{suffix}"
    second_instance = f"instance-b-{suffix}"
    registry = RuntimeWorkerRegistry(SessionLocal)

    try:
        first = registry.register(
            RuntimeWorkerRegistration(
                worker_key=worker_key,
                instance_id=first_instance,
                worker_type="runtime.execution",
                runtime_version="e2e",
                capabilities=("runtime.execution", "document.ingestion"),
                queue_keys=("platform-default",),
                workload_classes=("document_ingestion",),
                metadata={"test": True},
            )
        )
        first_id = first.id

        replacement = registry.register(
            RuntimeWorkerRegistration(
                worker_key=worker_key,
                instance_id=second_instance,
                worker_type="runtime.execution",
                runtime_version="e2e-2",
                capabilities=("document.ingestion", "runtime.execution"),
                queue_keys=("platform-default", "platform-default"),
                workload_classes=("document_ingestion",),
                metadata={"test": True, "replacement": True},
            )
        )

        heartbeat = registry.heartbeat(
            worker_key=worker_key,
            instance_id=second_instance,
            observed_state="ready",
            metrics={"processed": 3},
        )

        mismatch_rejected = False
        try:
            registry.heartbeat(
                worker_key=worker_key,
                instance_id=first_instance,
            )
        except RuntimeWorkerRegistryError:
            mismatch_rejected = True

        offline = registry.mark_offline(
            worker_key=worker_key,
            instance_id=second_instance,
        )

        with SessionLocal() as session:
            persisted = session.scalar(select(RuntimeWorker).where(RuntimeWorker.worker_key == worker_key))
            checks = {
                "first_registration_created": first_id is not None,
                "reregistration_preserved_identity": replacement.id == first_id,
                "instance_replaced": replacement.instance_id == second_instance,
                "runtime_version_updated": replacement.runtime_version == "e2e-2",
                "capabilities_normalized": replacement.capabilities
                == [
                    "document.ingestion",
                    "runtime.execution",
                ],
                "queue_keys_deduplicated": replacement.queue_keys == ["platform-default"],
                "heartbeat_ready": heartbeat.observed_state == "ready",
                "ready_timestamp_set": heartbeat.ready_at is not None,
                "heartbeat_timestamp_set": heartbeat.heartbeat_at is not None,
                "metrics_persisted": heartbeat.metrics == {"processed": 3},
                "instance_mismatch_rejected": mismatch_rejected,
                "offline_transitioned": offline.observed_state == "offline",
                "persisted_worker_exists": persisted is not None,
                "persisted_offline": persisted is not None and persisted.observed_state == "offline",
            }
    finally:
        with SessionLocal() as session:
            session.execute(delete(RuntimeWorker).where(RuntimeWorker.worker_key == worker_key))
            session.commit()

    result = {**checks, "passed": all(checks.values())}
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
