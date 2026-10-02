from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTROL = ROOT / "app/services/runtime_worker_control.py"
WORKER = ROOT / "app/workers/runtime_controlled_ingestion_worker.py"


def main() -> int:
    control = CONTROL.read_text(encoding="utf-8")
    worker = WORKER.read_text(encoding="utf-8")
    checks = {
        "control_exists": CONTROL.exists(),
        "worker_exists": WORKER.exists(),
        "states": all(value in control for value in ("active", "paused", "draining", "disabled")),
        "command": "def set_desired_state(" in control,
        "decision": "def decision(" in control,
        "row_lock": ".with_for_update()" in control,
        "pause_blocks": 'desired_state="paused"' in control and "accepts_work=False" in control,
        "drain_blocks": 'desired_state="draining"' in control,
        "disabled_blocks_without_exit": 'desired_state="disabled"' in control
        and 'observed_state="offline"' in control
        and "should_exit=False" in control,
        "worker_uses_control": "RuntimeWorkerControl(SessionLocal)" in worker,
        "worker_checks": "decision = control.decision" in worker,
        "worker_blocks": "if not decision.accepts_work:" in worker,
        "worker_rechecks": "post_run = control.decision" in worker,
        "worker_entrypoint": "def main() -> int:" in worker,
    }
    result = {**checks, "passed": all(checks.values())}
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
