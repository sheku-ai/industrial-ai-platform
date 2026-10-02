#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine

API_ROOT = Path(__file__).resolve().parents[1] / "apps" / "api"


def inspect_chain(name: str, config_name: str, environment_name: str) -> dict[str, object]:
    database_url = os.environ.get(environment_name, "").strip()
    if not database_url:
        raise RuntimeError(f"{environment_name} is required")

    config = Config(str(API_ROOT / config_name))
    config.set_main_option("script_location", str(API_ROOT / config.get_main_option("script_location")))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    script = ScriptDirectory.from_config(config)
    repository_heads = tuple(script.get_heads())
    revisions = tuple(script.walk_revisions())

    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            database_heads = tuple(MigrationContext.configure(connection).get_current_heads())
    finally:
        engine.dispose()

    revision_ids = [revision.revision for revision in revisions]
    passed = (
        len(repository_heads) == 1
        and len(database_heads) == 1
        and database_heads == repository_heads
        and len(revision_ids) == len(set(revision_ids))
    )
    return {
        "name": name,
        "repository_heads": list(repository_heads),
        "database_heads": list(database_heads),
        "revision_count": len(revision_ids),
        "single_repository_head": len(repository_heads) == 1,
        "single_database_head": len(database_heads) == 1,
        "database_at_head": database_heads == repository_heads,
        "unique_revision_ids": len(revision_ids) == len(set(revision_ids)),
        "passed": passed,
    }


def main() -> int:
    result: dict[str, object] = {"schema_version": 1}
    try:
        result["platform"] = inspect_chain("platform", "alembic.ini", "DATABASE_URL")
        result["identity"] = inspect_chain("identity", "identity_alembic.ini", "IDENTITY_DATABASE_URL")
        result["passed"] = bool(result["platform"]["passed"] and result["identity"]["passed"])
    except Exception as exc:
        result["passed"] = False
        result["error"] = f"{type(exc).__name__}: {exc}"
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
