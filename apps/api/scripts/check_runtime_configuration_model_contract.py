from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import CheckConstraint, Index, UniqueConstraint

from app.db.base import Base
from app.models.runtime_configuration import (
    RuntimeConfiguration,
    RuntimeConfigurationRevision,
    RuntimeConfigurationRevisionStatus,
    RuntimeConfigurationScope,
)

ROOT = Path(__file__).resolve().parents[1]
MODEL_MIGRATION = ROOT / "alembic" / "versions" / "20260623_261a_runtime_configuration_model.py"
INDEX_MIGRATION = ROOT / "alembic" / "versions" / "20260623_261a1_runtime_configuration_scope_indexes.py"


def names(table, kind):
    return {item.name or "" for item in table.constraints if isinstance(item, kind)}


def contains_name(values: set[str], expected: str) -> bool:
    return any(value == expected or value.endswith(expected) for value in values)


def main() -> int:
    configuration = RuntimeConfiguration.__table__
    revision = RuntimeConfigurationRevision.__table__
    model_migration_text = MODEL_MIGRATION.read_text(encoding="utf-8")
    index_migration_text = INDEX_MIGRATION.read_text(encoding="utf-8")

    configuration_checks = names(configuration, CheckConstraint)
    configuration_uniques = names(configuration, UniqueConstraint)
    revision_checks = names(revision, CheckConstraint)
    revision_uniques = names(revision, UniqueConstraint)
    configuration_indexes = {item.name or "" for item in configuration.indexes if isinstance(item, Index)}
    revision_indexes = {item.name or "" for item in revision.indexes if isinstance(item, Index)}

    checks = {
        "configuration_table_registered": "runtime.configurations" in Base.metadata.tables,
        "revision_table_registered": "runtime.configuration_revisions" in Base.metadata.tables,
        "organization_nullable": configuration.c.organization_id.nullable,
        "configuration_type_required": not configuration.c.configuration_type.nullable,
        "configuration_key_required": not configuration.c.configuration_key.nullable,
        "positive_revision": contains_name(revision_checks, "ck_runtime_configuration_revisions_positive_revision"),
        "positive_schema_version": contains_name(
            revision_checks, "ck_runtime_configuration_revisions_positive_schema_version"
        ),
        "effective_window": contains_name(revision_checks, "ck_runtime_configuration_revisions_effective_window"),
        "payload_object": contains_name(revision_checks, "ck_runtime_configuration_revisions_payload_object"),
        "status_constraint": contains_name(revision_checks, "ck_runtime_configuration_revisions_status"),
        "type_not_blank": contains_name(configuration_checks, "ck_runtime_configurations_type_not_blank"),
        "key_not_blank": contains_name(configuration_checks, "ck_runtime_configurations_key_not_blank"),
        "scope_shape": contains_name(configuration_checks, "ck_runtime_configurations_scope_shape"),
        "scope_identity_unique": "uq_runtime_configurations_scope_key" in configuration_uniques,
        "revision_number_unique": "uq_runtime_configuration_revisions_number" in revision_uniques,
        "platform_scope_guard": "uq_runtime_configurations_platform_scope" in configuration_indexes,
        "organization_scope_guard": "uq_runtime_configurations_organization_scope" in configuration_indexes,
        "named_platform_scope_guard": "uq_runtime_configurations_named_platform_scope" in configuration_indexes,
        "named_organization_scope_guard": "uq_runtime_configurations_named_organization_scope" in configuration_indexes,
        "single_active_guard": "uq_runtime_configuration_revisions_active" in revision_indexes,
        "scope_enum": {item.value for item in RuntimeConfigurationScope}
        == {"platform", "organization", "worker", "workload_class"},
        "status_enum": {item.value for item in RuntimeConfigurationRevisionStatus}
        == {"draft", "active", "superseded", "disabled"},
        "model_migration_exists": MODEL_MIGRATION.exists(),
        "model_migration_revision": 'revision = "20260623_261a"' in model_migration_text,
        "model_migration_parent": 'down_revision = "20260623_25113"' in model_migration_text,
        "model_migration_active_guard": "uq_runtime_configuration_revisions_active" in model_migration_text,
        "index_migration_exists": INDEX_MIGRATION.exists(),
        "index_migration_revision": 'revision = "20260623_261a1"' in index_migration_text,
        "index_migration_parent": 'down_revision = "20260623_261a"' in index_migration_text,
        "index_migration_platform_guard": "uq_runtime_configurations_named_platform_scope" in index_migration_text,
        "index_migration_organization_guard": "uq_runtime_configurations_named_organization_scope"
        in index_migration_text,
    }

    result = {
        **checks,
        "passed": all(checks.values()),
        "configuration_columns": sorted(configuration.c.keys()),
        "revision_columns": sorted(revision.c.keys()),
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
