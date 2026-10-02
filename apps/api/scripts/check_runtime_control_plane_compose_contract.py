from __future__ import annotations

import argparse
import json
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--compose-file",
        default="docker-compose.yml",
        help="Path to the canonical platform Compose file",
    )
    return parser.parse_args()


def service_block(source: str, service_name: str) -> str:
    marker = f"  {service_name}:\n"
    start = source.find(marker)
    if start < 0:
        return ""
    next_service = source.find("\n  ", start + len(marker))
    while next_service >= 0:
        line_end = source.find("\n", next_service + 1)
        line = source[next_service + 1 : line_end if line_end >= 0 else len(source)]
        if line.startswith("  ") and not line.startswith("    ") and line.endswith(":"):
            return source[start:next_service]
        next_service = source.find("\n  ", next_service + 3)
    return source[start:]


def main() -> int:
    args = parse_args()
    compose = Path(args.compose_file).resolve()
    source = compose.read_text(encoding="utf-8") if compose.exists() else ""
    monitor = service_block(source, "worker-monitor")
    reconciler = service_block(source, "lease-reconciler")
    api = service_block(source, "api")

    checks = {
        "compose_exists": compose.exists(),
        "worker_monitor_service": bool(monitor),
        "lease_reconciler_service": bool(reconciler),
        "api_threshold_alignment": "WORKER_HEARTBEAT_STALE_SECONDS" in api,
        "worker_monitor_identity": "WORKER_MONITOR_ID" in monitor,
        "lease_reconciler_identity": "LEASE_RECONCILER_ID" in reconciler,
        "worker_monitor_healthcheck": "$${WORKER_MONITOR_ID}" in monitor,
        "lease_reconciler_healthcheck": "$${LEASE_RECONCILER_ID}" in reconciler,
        "worker_monitor_probe": "check_managed_service_health.py" in monitor,
        "lease_reconciler_probe": "check_managed_service_health.py" in reconciler,
        "worker_monitor_restart": "restart: unless-stopped" in monitor,
        "lease_reconciler_restart": "restart: unless-stopped" in reconciler,
        "worker_monitor_migrator_dependency": "condition: service_completed_successfully" in monitor,
        "lease_reconciler_migrator_dependency": "condition: service_completed_successfully" in reconciler,
        "worker_monitor_profile": 'profiles: ["ingestion"]' in monitor,
        "lease_reconciler_profile": 'profiles: ["ingestion"]' in reconciler,
    }
    result = {
        **checks,
        "compose_file": str(compose),
        "passed": all(checks.values()),
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
