#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.lib.docker_compose import DockerCompose
from scripts.lib.process_runner import ProcessExecutionError


CHECKS = (
    "check_runtime_worker_heartbeat_reconciliation_concurrency_e2e.py",
    "check_runtime_lease_retry_e2e.py",
    "check_resource_scope_behavior.py",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the bounded Sprint 27.4 resilience checks."
    )
    parser.add_argument("--skip-build", action="store_true")
    parser.add_argument("--timeout-seconds", type=int, default=900)
    return parser.parse_args()


def step(name: str) -> None:
    print(f"\n=== {name} ===", flush=True)


def main() -> int:
    args = parse_args()
    compose = DockerCompose(
        project_root=PROJECT_ROOT,
        compose_files=[PROJECT_ROOT / "docker-compose.test.yml"],
        timeout_seconds=args.timeout_seconds,
    )
    failed = False
    try:
        step("Reset bounded resilience environment")
        compose.down()
        if not args.skip_build:
            step("Build bounded resilience runtime")
            compose.run(["build", "migrator-test", "api-test"])
        step("Start disposable PostgreSQL")
        compose.run(["up", "-d", "postgres-test"])
        step("Apply migrations")
        compose.run(["run", "--rm", "migrator-test"])
        for check in CHECKS:
            step(check)
            compose.run(
                ["run", "--rm", "api-test", "python", f"/app/scripts/{check}"]
            )
        print("\nSprint 27.4 bounded resilience tests passed.", flush=True)
        return 0
    except ProcessExecutionError as exc:
        failed = True
        return exc.result.returncode or 1
    except Exception as exc:
        failed = True
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    finally:
        if failed:
            compose.diagnostic_logs(["postgres-test", "migrator-test", "api-test"])
        step("Dispose bounded resilience environment")
        compose.down()


if __name__ == "__main__":
    raise SystemExit(main())
