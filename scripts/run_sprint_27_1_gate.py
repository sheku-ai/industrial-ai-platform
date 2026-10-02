#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Sprint 27.1 platform-scope authorization gate.")
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
        str(PROJECT_ROOT / "scripts/run_sprint_26_3_gate.py"),
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
    run([
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
        "/app/scripts/check_resource_scope_behavior.py",
    ])
    print("\nSprint 27.1 authorization gate passed.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
