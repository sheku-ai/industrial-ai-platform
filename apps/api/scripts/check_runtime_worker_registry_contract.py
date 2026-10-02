from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Index, UniqueConstraint

from app.db.base import Base
from app.models.runtime_worker import RuntimeWorker

ROOT = Path(__file__).resolve().parents[1]
MODEL_MIGRATION = ROOT / "alembic" / "versions" / "20260623_262a_runtime_worker_registry.py"
FK_MIGRATION = ROOT / "alembic" / "versions" / "20260623_262a1_worker_configuration_revision_fk.py"


def names(table, kind):
    return {item.name or "" for item in table.constraints if isinstance(item, kind)}


def contains_name(values: set[str], expected: str) -> bool:
    return any(value == expected or value.endswith(expected) for value in values)


def main() -> int:
    worker = RuntimeWorker.__table__
    model_migration_text = MODEL_MIGRATION.read_text(encoding="utf-8")
    fk_migration_text = FK_MIGRATION.read_text(encoding="utf-8")
    checks_set = names(worker, CheckConstraint)
    uniques = names(worker, UniqueConstraint)
    foreign_keys = names(worker, ForeignKeyConstraint)
    indexes = {item.name or "" for item in worker.indexes if isinstance(item, Index)}

    checks = {
        "table_registered": "runtime.workers" in Base.metadata.tables,
        "worker_key_required": not worker.c.worker_key.nullable,
        "instance_id_required": not worker.c.instance_id.nullable,
        "worker_type_required": not worker.c.worker_type.nullable,
        "worker_key_unique": "uq_runtime_workers_worker_key" in uniques,
        "instance_id_unique": "uq_runtime_workers_instance_id" in uniques,
        "active_revision_foreign_key": "fk_runtime_workers_active_configuration_revision" in foreign_keys,
        "worker_key_not_blank": contains_name(checks_set, "ck_runtime_workers_worker_key_not_blank"),
        "instance_id_not_blank": contains_name(checks_set, "ck_runtime_workers_instance_id_not_blank"),
        "worker_type_not_blank": contains_name(checks_set, "ck_runtime_workers_worker_type_not_blank"),
        "desired_state_constraint": contains_name(checks_set, "ck_runtime_workers_desired_state"),
        "observed_state_constraint": contains_name(checks_set, "ck_runtime_workers_observed_state"),
        "capabilities_array": contains_name(checks_set, "ck_runtime_workers_capabilities_array"),
        "queue_keys_array": contains_name(checks_set, "ck_runtime_workers_queue_keys_array"),
        "workload_classes_array": contains_name(checks_set, "ck_runtime_workers_workload_classes_array"),
        "metadata_object": contains_name(checks_set, "ck_runtime_workers_metadata_object"),
        "metrics_object": contains_name(checks_set, "ck_runtime_workers_metrics_object"),
        "ready_at_constraint": contains_name(checks_set, "ck_runtime_workers_ready_at"),
        "heartbeat_at_constraint": contains_name(checks_set, "ck_runtime_workers_heartbeat_at"),
        "last_seen_at_constraint": contains_name(checks_set, "ck_runtime_workers_last_seen_at"),
        "type_state_index": "ix_runtime_workers_type_state" in indexes,
        "heartbeat_index": "ix_runtime_workers_heartbeat" in indexes,
        "desired_observed_index": "ix_runtime_workers_desired_observed" in indexes,
        "model_migration_exists": MODEL_MIGRATION.exists(),
        "model_migration_revision": 'revision = "20260623_262a"' in model_migration_text,
        "model_migration_parent": 'down_revision = "20260623_261a1"' in model_migration_text,
        "fk_migration_exists": FK_MIGRATION.exists(),
        "fk_migration_revision": 'revision = "20260623_262a1"' in fk_migration_text,
        "fk_migration_parent": 'down_revision = "20260623_262a"' in fk_migration_text,
        "fk_migration_constraint": "fk_runtime_workers_active_configuration_revision" in fk_migration_text,
        "migration_downgrades": "def downgrade() -> None:" in model_migration_text
        and "def downgrade() -> None:" in fk_migration_text,
    }

    result = {**checks, "passed": all(checks.values()), "columns": sorted(worker.c.keys())}
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
