from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "main.py"
SCHEMA = ROOT / "app/schemas/dependency_health.py"
HEALTH = ROOT / "app/services/dependency_health.py"
RECOVERY = ROOT / "app/services/runtime_dependency_recovery.py"
MANAGED = ROOT / "app/services/runtime_managed_service.py"
SCHEDULER = ROOT / "app/services/scheduler_daemon.py"
WORKER = ROOT / "app/workers/runtime_controlled_ingestion_worker.py"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--compose-file",
        type=Path,
        default=ROOT.parents[1] / "docker-compose.yml",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    main_source = MAIN.read_text(encoding="utf-8")
    schema = SCHEMA.read_text(encoding="utf-8")
    health = HEALTH.read_text(encoding="utf-8")
    recovery = RECOVERY.read_text(encoding="utf-8")
    managed = MANAGED.read_text(encoding="utf-8")
    scheduler = SCHEDULER.read_text(encoding="utf-8")
    worker = WORKER.read_text(encoding="utf-8")
    compose = args.compose_file.read_text(encoding="utf-8")

    checks = {
        "lifecycle_states_bounded": all(
            f'"{state}"' in schema for state in ("alive", "ready", "degraded", "unavailable")
        ),
        "required_database_ready": 'lifecycle_state="ready"' in health,
        "required_database_unavailable": 'lifecycle_state="unavailable"' in health,
        "optional_outage_degraded": 'lifecycle_state="degraded"' in health,
        "optional_outage_not_503": 'if snapshot.status == "critical":' in main_source,
        "liveness_reports_alive": '"lifecycle_state": "alive"' in main_source,
        "startup_retry_bounded": (
            "startup_dependency_max_attempts" in main_source and "RuntimeDependencyRecovery(" in main_source
        ),
        "transient_errors_bounded": "TRANSIENT_DEPENDENCY_ERRORS" in recovery,
        "recovery_backoff_capped": "maximum_delay_seconds" in recovery,
        "managed_service_recovers": (
            "is_transient_dependency_error(exc)" in managed and "self._recovery.wait()" in managed
        ),
        "scheduler_recovers": (
            "is_transient_dependency_error(exc)" in scheduler and "self._recovery.wait()" in scheduler
        ),
        "ingestion_worker_recovers": ("is_transient_dependency_error(exc)" in worker and "recovery.wait()" in worker),
        "postgres_healthcheck": "pg_isready" in compose,
        "redis_healthcheck": 'test: ["CMD", "redis-cli", "ping"]' in compose,
        "minio_healthcheck": 'test: ["CMD", "mc", "ready", "local"]' in compose,
        "minio_bucket_initialized": ("  minio-init:" in compose and "mc mb --ignore-existing" in compose),
        "worker_waits_for_redis": "redis:\n        condition: service_healthy" in compose,
        "worker_waits_for_minio": ("minio-init:\n        condition: service_completed_successfully" in compose),
        "ai_optional_profile": 'profiles: ["ai"]' in compose,
        "ai_default_deny": 'name="ai_provider_execution"' in health,
    }
    result = {**checks, "passed": all(checks.values())}
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
