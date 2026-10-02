#!/usr/bin/env python3
from __future__ import annotations

import argparse
import platform
import signal
import sys
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve()
PROJECT_ROOT = SCRIPT_PATH.parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.lib.docker_compose import DockerCompose, DockerComposeUnavailableError
from scripts.lib.process_runner import ProcessExecutionError, run_process


CHECKS = (
    "check_runtime_worker_control_e2e.py",
    "check_runtime_worker_health_e2e.py",
    "check_runtime_worker_readiness_api_e2e.py",
    "check_runtime_worker_command_audit_e2e.py",
    "check_runtime_worker_stale_audit_e2e.py",
    "check_runtime_worker_history_api_e2e.py",
    "check_runtime_worker_summary_e2e.py",
    "check_runtime_lease_retry_e2e.py",
    "check_runtime_lease_exhaustion_e2e.py",
    "check_runtime_lease_invalid_payload_e2e.py",
    "check_runtime_lease_concurrency_e2e.py",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run runtime-domain E2E tests against disposable PostgreSQL infrastructure."
    )
    parser.add_argument("--skip-build", action="store_true", help="Reuse existing test images.")
    parser.add_argument(
        "--skip-portal-build",
        action="store_true",
        help="Accepted for gate CLI compatibility; this runner does not build the portal.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=900,
        help="Default timeout for each subprocess or Docker Compose command.",
    )
    return parser.parse_args()


def install_signal_handlers() -> None:
    def _handle_signal(signum: int, _frame) -> None:
        raise KeyboardInterrupt(f"received signal {signum}")

    signal.signal(signal.SIGINT, _handle_signal)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _handle_signal)


def step(name: str) -> None:
    print(f"\n=== {name} ===", flush=True)


def main() -> int:
    args = parse_args()
    if args.timeout_seconds <= 0:
        print("ERROR: --timeout-seconds must be positive", file=sys.stderr)
        return 2

    install_signal_handlers()
    compose_file = PROJECT_ROOT / "docker-compose.test.yml"
    lifecycle_contract = PROJECT_ROOT / "apps" / "api" / "scripts" / "check_test_lifecycle_foundation_contract.py"

    print(
        f"Portable runtime test orchestration: system={platform.system()} architecture={platform.machine()}",
        flush=True,
    )

    try:
        compose = DockerCompose(
            project_root=PROJECT_ROOT,
            compose_files=[compose_file],
            timeout_seconds=args.timeout_seconds,
        )
    except DockerComposeUnavailableError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    failed = False
    try:
        step("Reset isolated runtime test environment")
        compose.down()

        if not args.skip_build:
            step("Build isolated runtime test image")
            compose.run(["build", "migrator-test", "api-test"])

        step("Start disposable PostgreSQL")
        compose.run(["up", "-d", "postgres-test"])

        step("Apply migrations to disposable database")
        compose.run(["run", "--rm", "migrator-test"])

        step("Test lifecycle foundation contract")
        run_process(
            [sys.executable, str(lifecycle_contract)],
            cwd=PROJECT_ROOT,
            timeout_seconds=args.timeout_seconds,
        )

        for check in CHECKS:
            step(check)
            compose.run(["run", "--rm", "api-test", "python", f"/app/scripts/{check}"])

        print("\nIsolated runtime domain tests passed.", flush=True)
        return 0
    except KeyboardInterrupt:
        failed = True
        print("\nRuntime isolated test execution interrupted.", file=sys.stderr, flush=True)
        return 130
    except ProcessExecutionError as exc:
        failed = True
        print(f"\nERROR: {exc}", file=sys.stderr, flush=True)
        return exc.result.returncode or 1
    except Exception as exc:
        failed = True
        print(f"\nERROR: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        return 1
    finally:
        if failed:
            compose.diagnostic_logs(["postgres-test", "migrator-test", "api-test"])
        step("Dispose isolated runtime test environment")
        compose.down()


if __name__ == "__main__":
    raise SystemExit(main())
