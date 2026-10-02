from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVICE = ROOT / "app" / "services" / "runtime_worker_registry.py"
WORKER = ROOT / "app" / "workers" / "runtime_ingestion_worker.py"


def main() -> int:
    service_text = SERVICE.read_text(encoding="utf-8")
    worker_text = WORKER.read_text(encoding="utf-8")

    checks = {
        "service_exists": SERVICE.exists(),
        "worker_entrypoint_exists": WORKER.exists(),
        "registration_contract_present": "class RuntimeWorkerRegistration" in service_text,
        "registry_service_present": "class RuntimeWorkerRegistry" in service_text,
        "register_method_present": "def register(" in service_text,
        "heartbeat_method_present": "def heartbeat(" in service_text,
        "offline_method_present": "def mark_offline(" in service_text,
        "registration_uses_row_lock": ".with_for_update()" in service_text,
        "registration_commits": "session.commit()" in service_text,
        "instance_mismatch_guard": "worker instance mismatch" in service_text,
        "entrypoint_builds_registry": "RuntimeWorkerRegistry(SessionLocal)" in worker_text,
        "entrypoint_registers": "lifecycle.register(" in worker_text,
        "entrypoint_heartbeats_ready": 'observed_state="ready"' in worker_text,
        "entrypoint_heartbeats_busy": 'observed_state="busy"' in worker_text,
        "entrypoint_marks_offline": "lifecycle.mark_offline(" in worker_text,
        "heartbeat_interval_configurable": "WORKER_HEARTBEAT_INTERVAL_SECONDS" in worker_text,
        "instance_id_configurable": "WORKER_INSTANCE_ID" in worker_text,
        "runtime_version_traceable": "WORKER_RUNTIME_VERSION" in worker_text,
        "capabilities_published": "capabilities=(" in worker_text,
        "queue_ownership_published": "queue_keys=published_queue_keys" in worker_text,
        "workload_ownership_published": "workload_classes=(" in worker_text,
    }

    result = {**checks, "passed": all(checks.values())}
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
