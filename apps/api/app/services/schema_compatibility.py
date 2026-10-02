from __future__ import annotations

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine

from app.services.migration_safety import evaluate_migration_safety


def assert_database_schema_compatible(database_url: str) -> None:
    if not database_url.strip():
        raise RuntimeError("database url is not configured")

    config = Config("alembic.ini")
    script = ScriptDirectory.from_config(config)
    repository_heads = tuple(script.get_heads())
    known_revisions = tuple(revision.revision for revision in script.walk_revisions())

    engine = create_engine(database_url, pool_pre_ping=True)
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
                item.revision
                for item in reversed(list(script.iterate_revisions(target, current)))
                if item.revision != current
            )
        except Exception:
            pending_revisions = ()

    report = evaluate_migration_safety(
        repository_heads=repository_heads,
        database_heads=database_heads,
        known_revisions=known_revisions,
        pending_revisions=pending_revisions,
    )
    if not report.startup_compatible:
        raise RuntimeError(f"database schema is not startup-compatible: {report.compatibility}; {report.detail}")
