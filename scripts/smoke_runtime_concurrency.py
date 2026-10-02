#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Barrier

import psycopg
from psycopg import sql
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "apps" / "api"
sys.path.insert(0, str(API_DIR))

from app.models.runtime import RuntimeExecution, RuntimeExecutionAttempt, RuntimeExecutionEvent  # noqa: E402
from app.services.runtime_lifecycle import InvalidLeaseError, RuntimeLifecycleService  # noqa: E402

ADMIN_URL = os.environ.get(
    "RUNTIME_CONCURRENCY_ADMIN_URL",
    "postgresql://industrial_ai:industrial_ai@localhost:5432/postgres",
)


def _run_alembic(database_url: str) -> None:
    env = os.environ.copy()
    env["DATABASE_URL"] = database_url
    completed = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=API_DIR,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stdout + completed.stderr)


def _insert_organization(database_url: str, organization_id: uuid.UUID) -> None:
    plain_url = database_url.replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(plain_url) as connection:
        connection.execute(
            """
            INSERT INTO core.organizations
                (id, slug, name, description, status, config, created_by, updated_by)
            VALUES
                (%s, %s, %s, %s, 'active', '{}'::jsonb, 'sprint-19-4', 'sprint-19-4')
            """,
            (
                organization_id,
                f"runtime-concurrency-{organization_id.hex[:8]}",
                "Runtime Concurrency Validation",
                "Temporary tenant for runtime concurrency validation",
            ),
        )
        connection.commit()


def main() -> int:
    database_name = f"industrial_ai_runtime_concurrency_{uuid.uuid4().hex[:10]}"
    database_url = f"postgresql+psycopg://industrial_ai:industrial_ai@localhost:5432/{database_name}"
    organization_id = uuid.uuid4()
    subject_id = uuid.uuid4()
    result: dict[str, object] = {
        "contract": "RuntimeConcurrencyValidation",
        "provider_execution_enabled": False,
    }

    try:
        with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
            admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))

        _run_alembic(database_url)
        _insert_organization(database_url, organization_id)

        engine = create_engine(database_url, pool_size=8, max_overflow=8)
        SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

        idempotency_barrier = Barrier(2)

        def create_same_execution(worker: int) -> tuple[uuid.UUID, bool]:
            with SessionLocal() as session:
                idempotency_barrier.wait()
                execution, created = RuntimeLifecycleService(session).create_or_get(
                    organization_id=organization_id,
                    execution_type="generic.concurrent",
                    subject_type="generic.subject",
                    subject_id=subject_id,
                    idempotency_key="same-request",
                    requested_by=f"requester-{worker}",
                )
                return execution.id, created

        with ThreadPoolExecutor(max_workers=2) as pool:
            create_results = list(pool.map(create_same_execution, (1, 2)))

        canonical_ids = {item[0] for item in create_results}
        result["one_canonical_execution"] = len(canonical_ids) == 1
        execution_id = next(iter(canonical_ids))

        claim_barrier = Barrier(2)

        def claim_same_execution(worker_id: str):
            with SessionLocal() as session:
                claim_barrier.wait()
                return RuntimeLifecycleService(session).claim(
                    organization_id=organization_id,
                    worker_id=worker_id,
                    lease_duration=timedelta(seconds=30),
                    execution_type="generic.concurrent",
                )

        with ThreadPoolExecutor(max_workers=2) as pool:
            claims = list(pool.map(claim_same_execution, ("worker-a", "worker-b")))

        successful_claims = [claim for claim in claims if claim is not None]
        result["one_active_lease"] = len(successful_claims) == 1
        claimed_execution, first_attempt = successful_claims[0]

        with SessionLocal() as session:
            active_attempts = session.scalar(
                select(func.count()).select_from(RuntimeExecutionAttempt).where(
                    RuntimeExecutionAttempt.organization_id == organization_id,
                    RuntimeExecutionAttempt.execution_id == execution_id,
                    RuntimeExecutionAttempt.status.in_(("leased", "running")),
                )
            )
            result["active_lease_constraint_holds"] = active_attempts == 1

        with SessionLocal() as session:
            service = RuntimeLifecycleService(session)
            stale_token_rejected = False
            try:
                service.heartbeat(
                    organization_id,
                    claimed_execution.id,
                    lease_token=uuid.uuid4(),
                    extend_by=timedelta(seconds=30),
                )
            except InvalidLeaseError:
                stale_token_rejected = True
            result["stale_heartbeat_rejected"] = stale_token_rejected

        expiry_time = datetime.now(timezone.utc) + timedelta(minutes=2)
        with SessionLocal() as session:
            RuntimeLifecycleService(session).expire(
                organization_id,
                execution_id,
                now=expiry_time,
            )

        with SessionLocal() as session:
            reclaimed = RuntimeLifecycleService(session).claim(
                organization_id=organization_id,
                worker_id="worker-c",
                lease_duration=timedelta(seconds=30),
                execution_type="generic.concurrent",
                now=expiry_time + timedelta(seconds=1),
            )
            result["expired_execution_reclaimed"] = reclaimed is not None
            second_attempt = reclaimed[1] if reclaimed else None

        with SessionLocal() as session:
            attempts = session.scalars(
                select(RuntimeExecutionAttempt)
                .where(
                    RuntimeExecutionAttempt.organization_id == organization_id,
                    RuntimeExecutionAttempt.execution_id == execution_id,
                )
                .order_by(RuntimeExecutionAttempt.attempt_number)
            ).all()
            attempt_numbers = [attempt.attempt_number for attempt in attempts]
            result["attempt_numbers_unique"] = attempt_numbers == sorted(set(attempt_numbers))

            event_sequences = session.scalars(
                select(RuntimeExecutionEvent.sequence_number)
                .where(
                    RuntimeExecutionEvent.organization_id == organization_id,
                    RuntimeExecutionEvent.execution_id == execution_id,
                )
                .order_by(RuntimeExecutionEvent.sequence_number)
            ).all()
            result["event_sequences_unique"] = list(event_sequences) == sorted(set(event_sequences))

        rollback_preserved = False
        with SessionLocal() as session:
            try:
                with session.begin():
                    execution = session.scalar(
                        select(RuntimeExecution)
                        .where(
                            RuntimeExecution.organization_id == organization_id,
                            RuntimeExecution.id == execution_id,
                        )
                        .with_for_update()
                    )
                    original_status = execution.status
                    execution.status = "running"
                    session.add(
                        RuntimeExecutionEvent(
                            organization_id=organization_id,
                            execution_id=execution_id,
                            attempt_id=second_attempt.id if second_attempt else first_attempt.id,
                            event_type="validation.duplicate",
                            sequence_number=1,
                            occurred_at=datetime.now(timezone.utc),
                            actor_type="system",
                            payload={},
                        )
                    )
                    session.flush()
            except IntegrityError:
                session.rollback()
                persisted_status = session.scalar(
                    select(RuntimeExecution.status).where(
                        RuntimeExecution.organization_id == organization_id,
                        RuntimeExecution.id == execution_id,
                    )
                )
                rollback_preserved = persisted_status == original_status
        result["partial_failure_rolled_back"] = rollback_preserved

        engine.dispose()
    finally:
        with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
            admin.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s",
                (database_name,),
            )
            admin.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(database_name)))
            removed = admin.execute(
                "SELECT 1 FROM pg_database WHERE datname = %s",
                (database_name,),
            ).fetchone() is None
        result["temporary_database_removed"] = removed

    checks = [value for key, value in result.items() if key not in {"contract", "provider_execution_enabled"}]
    passed = all(value is True for value in checks) and result["provider_execution_enabled"] is False
    result["status"] = "passed" if passed else "failed"
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
