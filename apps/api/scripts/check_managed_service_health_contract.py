from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / "scripts/check_managed_service_health.py"


def main() -> int:
    source = PROBE.read_text(encoding="utf-8")
    checks = {
        "probe_exists": PROBE.exists(),
        "worker_key_required": 'parser.add_argument("--worker-key", required=True)' in source,
        "max_age_configurable": 'parser.add_argument("--max-age", type=int, default=60)' in source,
        "database_lookup": "select(RuntimeWorker)" in source,
        "heartbeat_required": "worker.heartbeat_at is None" in source,
        "stale_rejected": "worker.heartbeat_at < cutoff" in source,
        "failed_rejected": 'worker.observed_state in {"failed", "offline"}' in source,
        "healthy_exit": "return 0" in source,
    }
    result = {**checks, "passed": all(checks.values())}
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
