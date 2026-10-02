from __future__ import annotations

import json
from pathlib import Path

OBSOLETE = (
    "docker-compose.worker-monitor.yml",
    "docker-compose.lease-reconciler.yml",
    "docker-compose.runtime-control-plane.yml",
)


def main() -> int:
    root = Path.cwd()
    compose = root / "docker-compose.yml"
    checks = {
        "canonical_compose_present": compose.exists(),
        "obsolete_worker_monitor_absent": not (root / OBSOLETE[0]).exists(),
        "obsolete_lease_reconciler_absent": not (root / OBSOLETE[1]).exists(),
        "obsolete_runtime_control_plane_absent": not (root / OBSOLETE[2]).exists(),
    }
    result = {**checks, "passed": all(checks.values())}
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
