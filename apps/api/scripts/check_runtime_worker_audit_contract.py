from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "app/services/runtime_worker_audit.py"
CONTROL = ROOT / "app/services/runtime_worker_control.py"
HEALTH = ROOT / "app/services/runtime_worker_health.py"
ROUTE = ROOT / "app/api/routes/runtime_workers.py"


def main() -> int:
    audit = AUDIT.read_text(encoding="utf-8")
    control = CONTROL.read_text(encoding="utf-8")
    health = HEALTH.read_text(encoding="utf-8")
    route = ROUTE.read_text(encoding="utf-8")
    checks = {
        "audit_recorder_exists": AUDIT.exists(),
        "audit_event_recorded": "AuditEvent(" in audit,
        "audit_history_recorded": "AuditHistory(" in audit,
        "worker_resource_type": 'resource_type="runtime.worker"' in audit,
        "command_audited": 'action="desired_state_changed"' in control,
        "command_audit_before_commit": control.find("record_worker_transition(") < control.find("session.commit()"),
        "no_op_command_not_audited": "if previous != desired_state:" in control,
        "request_actor_forwarded": "actor_id=context.actor_reference" in route,
        "platform_audit_without_organization": (
            "WORKER_RESOURCE_SCOPE = ResourceScope.platform()" in route
            and "organization_id=WORKER_RESOURCE_SCOPE.organization_id" in route
        ),
        "stale_reconciliation_audited": 'action="heartbeat_stale_reconciled"' in health,
        "stale_system_actor": 'actor_id="runtime-worker-monitor"' in health,
        "stale_audit_before_commit": health.find("record_worker_transition(") < health.find("session.commit()"),
    }
    result = {**checks, "passed": all(checks.values())}
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
