from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEDULER = ROOT / "app/services/scheduler_daemon.py"
CONTRACTS = ROOT / "app/services/runtime_worker_contracts.py"
SCHEDULER_HEALTH = ROOT / "app/services/scheduler_health.py"
PLATFORM_HEALTH = ROOT / "app/services/platform_health.py"
LEGACY_MODEL = ROOT / "app/models/scheduler_worker.py"
MIGRATION = ROOT / "alembic/versions/20260625_272a_runtime_worker_registry_consolidation.py"


def main() -> int:
    scheduler = SCHEDULER.read_text(encoding="utf-8")
    contracts = CONTRACTS.read_text(encoding="utf-8")
    scheduler_health = SCHEDULER_HEALTH.read_text(encoding="utf-8")
    platform_health = PLATFORM_HEALTH.read_text(encoding="utf-8")
    legacy_model = LEGACY_MODEL.read_text(encoding="utf-8")
    migration = MIGRATION.read_text(encoding="utf-8")

    active_sources = scheduler + scheduler_health + platform_health
    checks = {
        "scheduler_registers_canonically": "RuntimeWorkerRegistration(" in scheduler,
        "scheduler_heartbeats_canonically": "self._registry.heartbeat(" in scheduler,
        "scheduler_marks_offline_canonically": "self._registry.mark_offline(" in scheduler,
        "scheduler_worker_type": '"runtime.scheduler"' in contracts,
        "scheduler_capabilities_published": (
            "SCHEDULER_CAPABILITIES" in scheduler
            and "control_plane.schedule.evaluation" in contracts
            and "control_plane.schedule.dispatch" in contracts
            and "control_plane.schedule.runtime_sync" in contracts
        ),
        "registry_failure_stops_scheduler": (
            'logger.exception("failed to persist scheduler worker state")\n            raise'
        )
        in scheduler,
        "legacy_model_not_used_by_active_services": "SchedulerWorkerState" not in active_sources,
        "legacy_upsert_removed": "pg_insert" not in scheduler,
        "scheduler_health_reads_runtime_workers": "RuntimeWorker" in scheduler_health,
        "platform_health_reads_runtime_workers": "RuntimeWorker" in platform_health,
        "legacy_history_model_retained": "class SchedulerWorkerState" in legacy_model,
        "legacy_history_marked_read_only": "Read-only legacy scheduler history" in legacy_model,
        "migration_revision": 'revision = "20260625_272a"' in migration,
        "migration_parent": 'down_revision = "20260623_262a1"' in migration,
        "migration_reads_legacy": "FROM control_plane.scheduler_workers AS legacy" in migration,
        "migration_writes_canonical": "INSERT INTO runtime.workers" in migration,
        "migration_is_deterministic": "md5('legacy-scheduler-worker:' || legacy.id)" in migration,
        "migration_bounds_legacy_as_offline": "'offline'" in migration,
        "migration_preserves_metrics": "cycles_completed" in migration and "runs_created" in migration,
        "migration_idempotent": "ON CONFLICT (worker_key) DO NOTHING" in migration,
        "legacy_table_not_dropped": "drop_table" not in migration,
    }
    result = {**checks, "passed": all(checks.values())}
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
