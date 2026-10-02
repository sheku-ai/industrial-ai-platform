from __future__ import annotations

import json
import uuid

from sqlalchemy import delete, func, select

from app.db.session import SessionLocal
from app.models.runtime_worker import RuntimeWorker
from app.models.scheduler_worker import SchedulerWorkerState
from app.services.scheduler_daemon import SchedulerDaemon, SchedulerDaemonConfig


def main() -> int:
    if SessionLocal is None:
        raise RuntimeError("database url is not configured")

    suffix = uuid.uuid4().hex
    worker_key = f"scheduler-consolidation-{suffix}"
    instance_id = f"scheduler-instance-{suffix}"

    try:
        with SessionLocal() as session:
            legacy_before = int(
                session.scalar(
                    select(func.count()).select_from(SchedulerWorkerState).where(SchedulerWorkerState.id == worker_key)
                )
                or 0
            )

        daemon = SchedulerDaemon(
            config=SchedulerDaemonConfig(
                poll_interval_seconds=0.5,
                batch_limit=1,
                owner_id=worker_key,
            ),
            session_factory=SessionLocal,
            instance_id=instance_id,
        )
        daemon._work_organizations = lambda _now: ()
        processed, created = daemon.run_cycle()

        with SessionLocal() as session:
            worker = session.scalar(select(RuntimeWorker).where(RuntimeWorker.worker_key == worker_key))
            legacy_after = int(
                session.scalar(
                    select(func.count()).select_from(SchedulerWorkerState).where(SchedulerWorkerState.id == worker_key)
                )
                or 0
            )

        checks = {
            "empty_cycle_completed": processed == 0 and created == 0,
            "canonical_worker_created": worker is not None,
            "canonical_instance": bool(worker and worker.instance_id == instance_id),
            "canonical_type": bool(worker and worker.worker_type == "runtime.scheduler"),
            "canonical_state": bool(worker and worker.observed_state == "ready"),
            "canonical_heartbeat": bool(worker and worker.heartbeat_at is not None),
            "canonical_cycle_metrics": bool(
                worker
                and worker.metrics.get("cycles_completed") == 1
                and worker.metrics.get("organizations_processed") == 0
                and worker.metrics.get("runs_created") == 0
                and worker.metrics.get("last_cycle_completed_at")
            ),
            "legacy_table_not_written": legacy_before == 0 and legacy_after == 0,
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
