from __future__ import annotations

import json
import uuid
from concurrent.futures import ThreadPoolExecutor
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
            slug_prefix="lease-concurrency",
            name="Lease Concurrency E2E",
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
            idempotency_key=f"lease-concurrency-{organization_id.hex}",
            input_payload={"valid": True},
            policy_snapshot={"retry": {"max_attempts": 2}},
        )
        execution_id = execution.id
        session.commit()

    claim_at = datetime.now(UTC) + timedelta(seconds=1)
    with SessionLocal() as session:
        claimed = RuntimeLifecycleService(session).claim(
            organization_id=organization_id,
            worker_id="lease-concurrency-worker",
            lease_duration=timedelta(seconds=5),
            execution_type="runtime.test",
            now=claim_at,
        )
        session.commit()
    assert claimed is not None

    reconcile_at = claim_at + timedelta(seconds=30)

    def run_once() -> list:
        return RuntimeLeaseReconciliationService(
            SessionLocal,
            clock=lambda: reconcile_at,
        ).reconcile(batch_limit=10)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: run_once(), range(2)))

    flattened = [item for batch in results for item in batch]
    with SessionLocal() as session:
        execution = session.scalar(select(RuntimeExecution).where(RuntimeExecution.id == execution_id))
        attempts = list(
            session.scalars(
                select(RuntimeExecutionAttempt).where(RuntimeExecutionAttempt.execution_id == execution_id)
            ).all()
        )
        assert execution is not None
        checks = {
            "processed_once": len(flattened) == 1,
            "single_expired_attempt": len(attempts) == 1 and attempts[0].status == "expired",
            "execution_scheduled": execution.status == "scheduled",
            "one_empty_result": sum(1 for batch in results if not batch) == 1,
        }

    result = {**checks, "passed": all(checks.values()), "execution_id": str(execution_id)}
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
