from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "app/schemas/operational_health.py"
SERVICE = ROOT / "app/services/operational_health.py"
ISSUES = ROOT / "app/services/operational_health_issues.py"
ROUTE = ROOT / "app/api/routes/operational_health.py"


def main() -> int:
    schema = SCHEMA.read_text(encoding="utf-8")
    service = SERVICE.read_text(encoding="utf-8")
    issues = ISSUES.read_text(encoding="utf-8")
    route = ROUTE.read_text(encoding="utf-8")

    checks = {
        "organization_route_required": 'context.is_scope("organization")' in route,
        "worker_summary_absent": "RuntimeWorkerSummaryRead" not in schema,
        "worker_control_plane_absent": "worker_control_plane" not in schema,
        "scheduler_worker_schema_absent": "latest_worker_status" not in schema,
        "scheduler_worker_model_absent": "SchedulerWorkerState" not in service,
        "worker_health_not_in_evaluator": "scheduler_worker_issue" not in service,
        "worker_timestamp_not_in_freshness": "SchedulerWorkerState.heartbeat_at" not in service,
        "worker_issues_excluded": "worker_failed" not in issues,
    }
    result = {**checks, "passed": all(checks.values())}
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
