from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT.parents[1]
RUNNER = PROJECT_ROOT / "scripts/run_sprint_27_4_resilience_tests.py"
GATE = PROJECT_ROOT / "scripts/run_sprint_27_4_gate.py"


def main() -> int:
    runner = RUNNER.read_text(encoding="utf-8")
    gate = GATE.read_text(encoding="utf-8")
    checks = {
        "bounded_runner_exists": RUNNER.exists(),
        "heartbeat_concurrency": ('"check_runtime_worker_heartbeat_reconciliation_concurrency_e2e.py"' in runner),
        "expired_lease_recovery": '"check_runtime_lease_retry_e2e.py"' in runner,
        "authorization_isolation": '"check_resource_scope_behavior.py"' in runner,
        "exactly_three_isolated_checks": runner.count('.py",') == 3,
        "disposable_database": "docker-compose.test.yml" in runner,
        "isolated_environment_disposed": "compose.down()" in runner,
        "dependency_recovery_inherited": "run_sprint_27_3_gate.py" in gate,
        "bounded_runner_invoked": "run_sprint_27_4_resilience_tests.py" in gate,
        "gate_has_skip_baseline": "--skip-baseline" in gate,
    }
    result = {**checks, "passed": all(checks.values())}
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
