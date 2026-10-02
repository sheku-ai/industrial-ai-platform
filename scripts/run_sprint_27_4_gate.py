#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the Sprint 27.4 bounded resilience closure gate."
    )
    parser.add_argument("--skip-build", action="store_true")
    parser.add_argument("--skip-portal-build", action="store_true")
    parser.add_argument("--skip-baseline", action="store_true")
    parser.add_argument("--health-timeout-seconds", type=int, default=120)
    parser.add_argument("--timeout-seconds", type=int, default=1200)
    return parser.parse_args()


def run(command: list[str]) -> None:
    subprocess.run(command, cwd=PROJECT_ROOT, check=True)


def main() -> int:
    args = parse_args()
    if not args.skip_baseline:
        baseline = [
            sys.executable,
            str(PROJECT_ROOT / "scripts/run_sprint_27_3_gate.py"),
            "--health-timeout-seconds",
            str(args.health_timeout_seconds),
            "--timeout-seconds",
            str(args.timeout_seconds),
        ]
        if args.skip_build:
            baseline.append("--skip-build")
        if args.skip_portal_build:
            baseline.append("--skip-portal-build")
        run(baseline)

    run(
        [
            sys.executable,
            str(
                PROJECT_ROOT
                / "apps/api/scripts/check_sprint_27_4_resilience_contract.py"
            ),
        ]
    )
    resilience = [
        sys.executable,
        str(PROJECT_ROOT / "scripts/run_sprint_27_4_resilience_tests.py"),
        "--timeout-seconds",
        str(args.timeout_seconds),
    ]
    if args.skip_build:
        resilience.append("--skip-build")
    run(resilience)
    print("\nSprint 27.4 bounded resilience gate passed.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
