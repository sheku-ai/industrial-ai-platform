#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the Sprint 27.2 runtime registry consolidation gate."
    )
    parser.add_argument("--skip-build", action="store_true")
    parser.add_argument("--skip-portal-build", action="store_true")
    parser.add_argument("--health-timeout-seconds", type=int, default=120)
    parser.add_argument("--timeout-seconds", type=int, default=1200)
    return parser.parse_args()


def run(command: list[str]) -> None:
    subprocess.run(command, cwd=PROJECT_ROOT, check=True)


def main() -> int:
    args = parse_args()
    baseline = [
        sys.executable,
        str(PROJECT_ROOT / "scripts/run_sprint_27_1_gate.py"),
        "--health-timeout-seconds",
        str(args.health_timeout_seconds),
        "--timeout-seconds",
        str(args.timeout_seconds),
    ]
    if args.skip_build:
        baseline.append("--skip-build")
    if args.skip_portal_build:
        baseline.append("--skip-portal-build")

    compose = ["docker", "compose", "--profile", "ingestion"]
    if not args.skip_build:
        run([*compose, "build", "migrator"])
    run(baseline)
    if not args.skip_build:
        run([*compose, "build", "scheduler"])
    run(
        [
            *compose,
            "up",
            "-d",
            "--force-recreate",
            "--wait",
            "--wait-timeout",
            str(args.health_timeout_seconds),
            "scheduler",
        ]
    )
    for check in (
        "check_runtime_worker_registry_consolidation_contract.py",
        "check_runtime_worker_registry_consolidation_e2e.py",
    ):
        run(
            [
                "docker",
                "compose",
                "--profile",
                "ingestion",
                "exec",
                "-T",
                "-e",
                "PYTHONPATH=/app",
                "api",
                "python",
                f"/app/scripts/{check}",
            ]
        )
    print("\nSprint 27.2 runtime registry consolidation gate passed.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
