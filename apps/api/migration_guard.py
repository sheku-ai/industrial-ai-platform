from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import asdict

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError

from app.services.migration_safety import MigrationSafetyReport, evaluate_migration_safety

LOCAL_DATABASE_URL = "postgresql+psycopg://industrial_ai:industrial_ai@127.0.0.1:5432/industrial_ai"


def resolve_database_url() -> str:
    configured = os.getenv("DATABASE_URL", "").strip()
    return configured or LOCAL_DATABASE_URL


def alembic_config() -> Config:
    config = Config("alembic.ini")
    database_url = resolve_database_url()
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def migration_report(config: Config | None = None) -> MigrationSafetyReport:
    config = config or alembic_config()
    script = ScriptDirectory.from_config(config)
    repository_heads = tuple(script.get_heads())
    known_revisions = tuple(revision.revision for revision in script.walk_revisions())

    engine = create_engine(config.get_main_option("sqlalchemy.url"), pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            database_heads = tuple(MigrationContext.configure(connection).get_current_heads())
    finally:
        engine.dispose()

    pending_revisions: tuple[str, ...] = ()
    if len(repository_heads) == 1 and len(database_heads) == 1 and database_heads[0] in known_revisions:
        current = database_heads[0]
        target = repository_heads[0]
        try:
            pending_revisions = tuple(
                revision.revision
                for revision in reversed(list(script.iterate_revisions(target, current)))
                if revision.revision != current
            )
        except Exception:
            pending_revisions = ()

    return evaluate_migration_safety(
        repository_heads=repository_heads,
        database_heads=database_heads,
        known_revisions=known_revisions,
        pending_revisions=pending_revisions,
    )


def print_report(report: MigrationSafetyReport, *, duration_seconds: float | None = None) -> None:
    payload = asdict(report)
    payload["startup_compatible"] = report.startup_compatible
    payload["migration_required"] = report.migration_required
    if duration_seconds is not None:
        payload["duration_seconds"] = round(duration_seconds, 3)
    print(json.dumps(payload, indent=2, sort_keys=True))


def print_connection_error(exc: Exception) -> None:
    print(
        json.dumps(
            {
                "compatibility": "database_unavailable",
                "startup_compatible": False,
                "migration_required": False,
                "database_url_source": "DATABASE_URL" if os.getenv("DATABASE_URL", "").strip() else "local_default",
                "detail": str(exc),
            },
            indent=2,
            sort_keys=True,
        )
    )


def check() -> int:
    try:
        report = migration_report()
    except SQLAlchemyError as exc:
        print_connection_error(exc)
        return 1
    print_report(report)
    return 0 if report.startup_compatible else 1


def apply() -> int:
    config = alembic_config()
    try:
        before = migration_report(config)
    except SQLAlchemyError as exc:
        print_connection_error(exc)
        return 1

    if before.compatibility in {
        "multiple_repository_heads",
        "multiple_database_heads",
        "unknown_database_revision",
        "database_ahead_or_diverged",
    }:
        print_report(before)
        return 1

    started = time.monotonic()
    command.upgrade(config, "head")
    duration = time.monotonic() - started

    after = migration_report(config)
    print_report(after, duration_seconds=duration)
    return 0 if after.startup_compatible else 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate and apply safe forward-only Alembic migrations")
    parser.add_argument("command", choices=("check", "apply"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    return check() if args.command == "check" else apply()


if __name__ == "__main__":
    raise SystemExit(main())
