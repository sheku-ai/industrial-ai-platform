from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SMOKES = (
    "smoke_sprint_17_runtime_orchestrator_contract.py",
    "smoke_sprint_17_execution_state_machine.py",
    "smoke_sprint_17_timeout_cancellation.py",
    "smoke_sprint_17_retry_failure_classification.py",
    "smoke_sprint_17_idempotency.py",
    "smoke_sprint_17_runtime_audit.py",
    "smoke_sprint_17_provider_readiness.py",
    "smoke_sprint_17_response_normalization.py",
    "smoke_sprint_17_execution_activation.py",
    "smoke_sprint_17_edition_boundary.py",
)


def main() -> None:
    completed: list[str] = []
    for smoke in SMOKES:
        path = REPO_ROOT / "scripts" / smoke
        result = subprocess.run(
            [sys.executable, str(path)],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"Sprint 17 smoke failed: {smoke}\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
            )
        completed.append(smoke)

    print(
        {
            "status": "passed",
            "sprint": "17",
            "validated_work_packages": len(completed),
            "provider_execution_enabled": False,
            "provider_execution_performed": False,
            "secret_resolution_performed": False,
            "network_call_performed": False,
            "generation_performed": False,
        }
    )


if __name__ == "__main__":
    main()
