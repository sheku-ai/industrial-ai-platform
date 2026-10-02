from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.runtime import RuntimeExecution, RuntimeExecutionAttempt, RuntimeExecutionEvent
from app.services.runtime_lease_reconciliation import RuntimeLeaseReconciliationService
from app.services.runtime_lifecycle import RuntimeLifecycleService
from app.testing.test_data import create_ephemeral_organization


def main() -> int:
    if SessionLocal is None:
        raise RuntimeError("database url is not configured")

    organization_id = uuid.uuid4()
    with SessionLocal() as session:
        create_ephemeral_organization(
            session,
            organization_id=organization_id,
            slug_prefix="lease-retry",
            name="Lease Retry E2E",
            test_suite="runtime-lease",
        )
        session.commit()

    with SessionLocal() as session:
        lifecycle = RuntimeLifecycleService(session)
        execution, _ = lifecycle.create_or_get(
            organization_id=organization_id,
            execution_type="runtime.test",
            subject_type="runtime.subject",
            subject_id=uuid.uuid4(),
            idempotency_key=f"lease-retry-{organization_id.hex}",
            input_payload={"valid": True},
            policy_snapshot={"retry": {"max_attempts": 2, "delay_seconds": 0}},
        )
        execution_id = execution.id
        session.commit()

    claim_at = datetime.now(UTC) + timedelta(seconds=1)
    with SessionLocal() as session:
        claimed = RuntimeLifecycleService(session).claim(
            organization_id=organization_id,
            worker_id="lease-retry-worker",
            lease_duration=timedelta(seconds=10),
            execution_type="runtime.test",
            now=claim_at,
        )
        session.commit()
    assert claimed is not None

    reconcile_at = claim_at + timedelta(seconds=60)
    service = RuntimeLeaseReconciliationService(SessionLocal, clock=lambda: reconcile_at)
    first = service.reconcile(batch_limit=10)
    repeat = service.reconcile(batch_limit=10)

    with SessionLocal() as session:
        execution = session.scalar(select(RuntimeExecution).where(RuntimeExecution.id == execution_id))
        attempt = session.scalar(
            select(RuntimeExecutionAttempt).where(RuntimeExecutionAttempt.execution_id == execution_id)
        )
        events = list(
            session.scalars(
                select(RuntimeExecutionEvent).where(RuntimeExecutionEvent.execution_id == execution_id)
            ).all()
        )
        assert execution is not None and attempt is not None
        checks = {
            "reconciled_once": len(first) == 1 and first[0].outcome == "retry_scheduled",
            "repeat_idempotent": repeat == [],
            "execution_scheduled": execution.status == "scheduled",
            "attempt_expired": attempt.status == "expired",
            "attempt_error": attempt.error_code == "lease_expired",
            "expiry_event": any(item.event_type == "execution.expired" for item in events),
            "retry_event": any(item.event_type == "execution.retry_scheduled" for item in events),
        }

    result = {**checks, "passed": all(checks.values()), "execution_id": str(execution_id)}
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
