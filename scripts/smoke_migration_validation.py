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
    "MIGRATION_VALIDATION_ADMIN_URL",
    "postgresql://industrial_ai:industrial_ai@localhost:5432/postgres",
)
REQUIRED_SCHEMAS = {"core", "documents", "security", "connectors", "ai", "audit", "runtime"}
REQUIRED_RUNTIME_TABLES = {
    "executions",
    "execution_attempts",
    "execution_events",
    "execution_artifacts",
}
RUNTIME_APPEND_ONLY_TRIGGER = "trg_runtime_execution_events_append_only"
RUNTIME_APPEND_ONLY_FUNCTION = "fn_runtime_reject_event_mutation"


def _run_alembic(database_url: str, *args: str) -> str:
    env = os.environ.copy()
    env["DATABASE_URL"] = database_url
    completed = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=API_DIR,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"alembic {' '.join(args)} failed\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    return completed.stdout.strip() or completed.stderr.strip()


def _database_url(database_name: str) -> str:
    return f"postgresql+psycopg://industrial_ai:industrial_ai@localhost:5432/{database_name}"


def _plain_database_url(database_name: str) -> str:
    return f"postgresql://industrial_ai:industrial_ai@localhost:5432/{database_name}"


def _inspect_runtime_objects(cursor: psycopg.Cursor) -> dict[str, bool]:
    cursor.execute(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'runtime'
          AND table_name = ANY(%s)
        """,
        (list(REQUIRED_RUNTIME_TABLES),),
    )
    runtime_tables = {row[0] for row in cursor.fetchall()}

    cursor.execute(
        """
        SELECT EXISTS (
            SELECT 1
            FROM pg_trigger t
            JOIN pg_class c ON c.oid = t.tgrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'runtime'
              AND c.relname = 'execution_events'
              AND t.tgname = %s
              AND NOT t.tgisinternal
        )
        """,
        (RUNTIME_APPEND_ONLY_TRIGGER,),
    )
    append_only_trigger_present = cursor.fetchone()[0]

    cursor.execute(
        """
        SELECT EXISTS (
            SELECT 1
            FROM pg_proc p
            JOIN pg_namespace n ON n.oid = p.pronamespace
            WHERE n.nspname = 'runtime'
              AND p.proname = %s
        )
        """,
        (RUNTIME_APPEND_ONLY_FUNCTION,),
    )
    append_only_function_present = cursor.fetchone()[0]

    return {
        "runtime_tables_present": runtime_tables == REQUIRED_RUNTIME_TABLES,
        "append_only_trigger_present": append_only_trigger_present,
        "append_only_function_present": append_only_function_present,
    }


def main() -> int:
    database_name = f"industrial_ai_migration_validation_{uuid.uuid4().hex[:10]}"
    database_url = _database_url(database_name)
    plain_database_url = _plain_database_url(database_name)
    sentinel_id = uuid.uuid4()
    result: dict[str, object] = {
        "contract": "MigrationValidation",
        "provider_execution_enabled": False,
    }
    temporary_database_removed = False

    try:
        with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
            admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))

        _run_alembic(database_url, "upgrade", "head")

        with psycopg.connect(plain_database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT version_num FROM alembic_version")
                heads = [row[0] for row in cursor.fetchall()]
                single_head = len(heads) == 1

                cursor.execute(
                    "SELECT schema_name FROM information_schema.schemata WHERE schema_name = ANY(%s)",
                    (list(REQUIRED_SCHEMAS),),
                )
                present_schemas = {row[0] for row in cursor.fetchall()}
                required_schemas_present = present_schemas == REQUIRED_SCHEMAS
                runtime_objects = _inspect_runtime_objects(cursor)

                cursor.execute(
                    """
                    INSERT INTO core.organizations
                        (id, slug, name, description, status, config, created_by, updated_by)
                    VALUES
                        (%s, %s, %s, %s, %s, %s::jsonb, %s, %s)
                    """,
                    (
                        sentinel_id,
                        f"migration-validation-{sentinel_id.hex[:8]}",
                        "Migration Validation Sentinel",
                        "Temporary migration preservation record",
                        "active",
                        json.dumps({"validation": True}),
                        "sprint-19-1",
                        "sprint-19-1",
                    ),
                )
            connection.commit()

        _run_alembic(database_url, "downgrade", "-1")
        _run_alembic(database_url, "upgrade", "head")

        with psycopg.connect(plain_database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT COUNT(*) FROM core.organizations WHERE id = %s",
                    (sentinel_id,),
                )
                data_preserved = cursor.fetchone()[0] == 1
                cursor.execute("SELECT COUNT(*) FROM alembic_version")
                downgrade_upgrade_cycle = cursor.fetchone()[0] == 1
                runtime_objects_after_reupgrade = _inspect_runtime_objects(cursor)

        result.update(
            {
                "data_preserved": data_preserved,
                "downgrade_upgrade_cycle": downgrade_upgrade_cycle,
                "empty_upgrade": True,
                "required_schemas_present": required_schemas_present,
                "runtime_tables_present": runtime_objects["runtime_tables_present"],
                "append_only_trigger_present": runtime_objects["append_only_trigger_present"],
                "append_only_function_present": runtime_objects["append_only_function_present"],
                "runtime_objects_restored_after_reupgrade": all(runtime_objects_after_reupgrade.values()),
                "single_head": single_head,
            }
        )
    finally:
        with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
            admin.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s",
                (database_name,),
            )
            admin.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(database_name)))
            remaining = admin.execute(
                "SELECT 1 FROM pg_database WHERE datname = %s",
                (database_name,),
            ).fetchone()
            temporary_database_removed = remaining is None

    result["temporary_database_removed"] = temporary_database_removed
    passed = all(
        (
            result.get("data_preserved") is True,
            result.get("downgrade_upgrade_cycle") is True,
            result.get("empty_upgrade") is True,
            result.get("required_schemas_present") is True,
            result.get("runtime_tables_present") is True,
            result.get("append_only_trigger_present") is True,
            result.get("append_only_function_present") is True,
            result.get("runtime_objects_restored_after_reupgrade") is True,
            result.get("single_head") is True,
            result.get("temporary_database_removed") is True,
        )
    )
    result["status"] = "passed" if passed else "failed"
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
