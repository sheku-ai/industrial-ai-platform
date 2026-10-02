from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.runtime import RuntimeExecution, RuntimeExecutionAttempt
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
            slug_prefix="lease-invalid",
            name="Lease Invalid Payload E2E",
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
            idempotency_key=f"lease-invalid-{organization_id.hex}",
            input_payload={"valid": True},
            policy_snapshot={"retry": {"max_attempts": 3}},
        )
        execution_id = execution.id
        execution.input_payload = ["invalid"]
        session.commit()

    claim_at = datetime.now(UTC) + timedelta(seconds=1)
    with SessionLocal() as session:
        claimed = RuntimeLifecycleService(session).claim(
            organization_id=organization_id,
            worker_id="lease-invalid-worker",
            lease_duration=timedelta(seconds=5),
            execution_type="runtime.test",
            now=claim_at,
        )
        session.commit()
    assert claimed is not None

    result_batch = RuntimeLeaseReconciliationService(
        SessionLocal,
        clock=lambda: claim_at + timedelta(seconds=30),
    ).reconcile(batch_limit=10)

    with SessionLocal() as session:
        execution = session.scalar(select(RuntimeExecution).where(RuntimeExecution.id == execution_id))
        attempt = session.scalar(
            select(RuntimeExecutionAttempt).where(RuntimeExecutionAttempt.execution_id == execution_id)
        )
        assert execution is not None and attempt is not None
        checks = {
            "invalid_payload_detected": len(result_batch) == 1
            and result_batch[0].outcome == "dead_lettered_invalid_payload",
            "execution_dead_lettered": execution.status == "dead_lettered",
            "invalid_payload_error": execution.error_code == "invalid_execution_payload",
            "attempt_expired": attempt.status == "expired",
            "not_rescheduled": execution.status != "scheduled",
        }

    result = {**checks, "passed": all(checks.values()), "execution_id": str(execution_id)}
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
