from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, select

from app.api.routes.operational_health import _with_worker_control_plane
from app.db.session import SessionLocal
from app.models.core import Organization
from app.models.runtime_worker import RuntimeWorker
from app.services.operational_health import OperationalHealthService
from app.services.runtime_worker_registry import RuntimeWorkerRegistration, RuntimeWorkerRegistry


def main() -> int:
    if SessionLocal is None:
        raise RuntimeError("database url is not configured")

    suffix = uuid.uuid4().hex
    worker_key = f"health-failed-{suffix}"
    registry = RuntimeWorkerRegistry(SessionLocal)

    try:
        worker = registry.register(
            RuntimeWorkerRegistration(
                worker_key=worker_key,
                instance_id=f"instance-{suffix}",
                worker_type="runtime.test",
            )
        )
        with SessionLocal() as session:
            persisted = session.scalar(select(RuntimeWorker).where(RuntimeWorker.id == worker.id))
            assert persisted is not None
            persisted.observed_state = "failed"
            persisted.heartbeat_at = datetime.now(UTC)
            persisted.last_seen_at = persisted.heartbeat_at
            persisted.last_error_code = "synthetic_failure"
            session.commit()

        with SessionLocal() as session:
            organization = session.scalar(select(Organization).order_by(Organization.created_at.asc()))
            assert organization is not None
            service = OperationalHealthService(session)
            snapshot = _with_worker_control_plane(service.get_snapshot(organization.id), service)
            failed_issue = next(
                (item for item in snapshot.issues if item.code == "worker_failed" and item.resource_key == worker_key),
                None,
            )
            checks = {
                "worker_summary_present": snapshot.worker_control_plane is not None,
                "failed_worker_counted": bool(
                    snapshot.worker_control_plane and snapshot.worker_control_plane.failed_workers >= 1
                ),
                "overall_critical": snapshot.summary.overall_status == "critical",
                "issue_count_matches": snapshot.summary.active_issues == len(snapshot.issues),
                "failed_issue_present": failed_issue is not None,
                "failed_issue_critical": bool(failed_issue and failed_issue.severity == "critical"),
                "failed_issue_resource": bool(failed_issue and failed_issue.resource_type == "runtime.worker"),
                "failed_issue_value": bool(failed_issue and failed_issue.observed_value == "synthetic_failure"),
            }
    finally:
        with SessionLocal() as session:
            session.execute(delete(RuntimeWorker).where(RuntimeWorker.worker_key == worker_key))
            session.commit()

    result = {**checks, "passed": all(checks.values())}
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
