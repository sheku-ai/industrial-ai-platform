#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import psycopg
from psycopg import sql

ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "apps" / "api"
ADMIN_URL = os.environ.get(
    "RUNTIME_INTEGRITY_ADMIN_URL",
    "postgresql://industrial_ai:industrial_ai@localhost:5432/postgres",
)

EXPECTED_CONSTRAINTS = {
    "fk_runtime_executions_organization",
    "pk_runtime_executions",
    "uq_runtime_executions_tenant_id",
    "fk_runtime_execution_attempts_execution",
    "pk_runtime_execution_attempts",
    "uq_runtime_execution_attempts_tenant_execution_id",
    "uq_runtime_execution_attempts_number",
    "fk_runtime_execution_events_execution",
    "fk_runtime_execution_events_attempt",
    "pk_runtime_execution_events",
    "uq_runtime_execution_events_sequence",
    "fk_runtime_execution_artifacts_execution",
    "fk_runtime_execution_artifacts_attempt",
    "pk_runtime_execution_artifacts",
}

EXPECTED_INDEXES = {
    "ix_runtime_executions_queue",
    "ix_runtime_executions_type_status",
    "ix_runtime_executions_subject",
    "ix_runtime_executions_correlation",
    "uq_runtime_executions_idempotency",
    "ix_runtime_execution_attempts_lease",
    "ix_runtime_execution_attempts_worker",
    "uq_runtime_execution_attempts_active",
    "ix_runtime_execution_events_timeline",
    "ix_runtime_execution_artifacts_type",
}


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


def _rejected(plain_url: str, statement: str, params: tuple[object, ...]) -> bool:
    try:
        with psycopg.connect(plain_url) as connection:
            connection.execute(statement, params)
            connection.commit()
    except psycopg.Error:
        return True
    return False


def main() -> int:
    database_name = f"industrial_ai_runtime_integrity_{uuid.uuid4().hex[:10]}"
    database_url = f"postgresql+psycopg://industrial_ai:industrial_ai@localhost:5432/{database_name}"
    plain_url = database_url.replace("postgresql+psycopg://", "postgresql://")
    result: dict[str, object] = {
        "contract": "RuntimePersistenceIntegrityValidation",
        "provider_execution_enabled": False,
    }

    org_a, org_b = uuid.uuid4(), uuid.uuid4()
    execution_a, execution_b = uuid.uuid4(), uuid.uuid4()
    attempt_a, attempt_b = uuid.uuid4(), uuid.uuid4()
    event_a = uuid.uuid4()

    try:
        with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
            admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))

        _run_alembic(database_url)

        with psycopg.connect(plain_url) as connection:
            for organization_id, suffix in ((org_a, "a"), (org_b, "b")):
                connection.execute(
                    """
                    INSERT INTO core.organizations
                        (id, slug, name, description, status, config, created_by, updated_by)
                    VALUES
                        (%s, %s, %s, %s, 'active', '{}'::jsonb, 'sprint-19-5', 'sprint-19-5')
                    """,
                    (
                        organization_id,
                        f"runtime-integrity-{suffix}-{organization_id.hex[:8]}",
                        f"Runtime Integrity Tenant {suffix.upper()}",
                        "Temporary tenant for runtime integrity validation",
                    ),
                )

            for organization_id, execution_id, suffix in (
                (org_a, execution_a, "a"),
                (org_b, execution_b, "b"),
            ):
                connection.execute(
                    """
                    INSERT INTO runtime.executions
                        (id, organization_id, execution_type, subject_type, subject_id,
                         idempotency_key, status, input_payload, policy_snapshot, metrics)
                    VALUES
                        (%s, %s, 'generic.integrity', 'generic.subject', %s,
                         %s, 'pending', '{}'::jsonb, '{}'::jsonb, '{}'::jsonb)
                    """,
                    (execution_id, organization_id, uuid.uuid4(), f"integrity-{suffix}"),
                )

            for organization_id, execution_id, attempt_id, worker_id in (
                (org_a, execution_a, attempt_a, "worker-a"),
                (org_b, execution_b, attempt_b, "worker-b"),
            ):
                connection.execute(
                    """
                    INSERT INTO runtime.execution_attempts
                        (id, organization_id, execution_id, attempt_number, status,
                         worker_id, lease_token, leased_at, lease_expires_at,
                         provider_reference, metrics)
                    VALUES
                        (%s, %s, %s, 1, 'leased', %s, %s, now(), now() + interval '5 minutes',
                         '{}'::jsonb, '{}'::jsonb)
                    """,
                    (attempt_id, organization_id, execution_id, worker_id, uuid.uuid4()),
                )

            connection.execute(
                """
                INSERT INTO runtime.execution_events
                    (id, organization_id, execution_id, attempt_id, event_type,
                     sequence_number, actor_type, payload)
                VALUES
                    (%s, %s, %s, %s, 'execution.leased', 1, 'worker', '{}'::jsonb)
                """,
                (event_a, org_a, execution_a, attempt_a),
            )
            connection.commit()

        result["tenant_mismatch_rejected"] = _rejected(
            plain_url,
            """
            INSERT INTO runtime.execution_attempts
                (id, organization_id, execution_id, attempt_number, status,
                 worker_id, lease_token, leased_at, lease_expires_at,
                 provider_reference, metrics)
            VALUES
                (%s, %s, %s, 2, 'leased', 'invalid-worker', %s, now(),
                 now() + interval '5 minutes', '{}'::jsonb, '{}'::jsonb)
            """,
            (uuid.uuid4(), org_b, execution_a, uuid.uuid4()),
        )

        result["cross_execution_attempt_reference_rejected"] = _rejected(
            plain_url,
            """
            INSERT INTO runtime.execution_events
                (id, organization_id, execution_id, attempt_id, event_type,
                 sequence_number, actor_type, payload)
            VALUES
                (%s, %s, %s, %s, 'invalid.reference', 2, 'system', '{}'::jsonb)
            """,
            (uuid.uuid4(), org_a, execution_a, attempt_b),
        )

        result["event_update_rejected"] = _rejected(
            plain_url,
            "UPDATE runtime.execution_events SET event_type = 'mutated' WHERE id = %s",
            (event_a,),
        )
        result["event_delete_rejected"] = _rejected(
            plain_url,
            "DELETE FROM runtime.execution_events WHERE id = %s",
            (event_a,),
        )

        with psycopg.connect(plain_url) as connection:
            constraints = {
                row[0]
                for row in connection.execute(
                    """
                    SELECT c.conname
                    FROM pg_constraint c
                    JOIN pg_namespace n ON n.oid = c.connamespace
                    WHERE n.nspname = 'runtime'
                    """
                ).fetchall()
            }
            indexes = {
                row[0]
                for row in connection.execute(
                    "SELECT indexname FROM pg_indexes WHERE schemaname = 'runtime'"
                ).fetchall()
            }
            event_count = connection.execute(
                "SELECT COUNT(*) FROM runtime.execution_events WHERE id = %s",
                (event_a,),
            ).fetchone()[0]
            organization_count = connection.execute(
                "SELECT COUNT(*) FROM core.organizations WHERE id IN (%s, %s)",
                (org_a, org_b),
            ).fetchone()[0]

        result["deterministic_constraints_present"] = EXPECTED_CONSTRAINTS.issubset(constraints)
        result["deterministic_indexes_present"] = EXPECTED_INDEXES.issubset(indexes)
        result["append_only_event_preserved"] = event_count == 1
        result["existing_core_data_preserved"] = organization_count == 2

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

    checks = [
        value
        for key, value in result.items()
        if key not in {"contract", "provider_execution_enabled"}
    ]
    passed = all(value is True for value in checks) and result["provider_execution_enabled"] is False
    result["status"] = "passed" if passed else "failed"
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
