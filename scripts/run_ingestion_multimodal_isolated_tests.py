#!/usr/bin/env python3
from __future__ import annotations

import argparse
import platform
import signal
import sys
import time
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve()
PROJECT_ROOT = SCRIPT_PATH.parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.lib.docker_compose import DockerCompose, DockerComposeUnavailableError
from scripts.lib.environment_scope import EnvironmentScope
from scripts.lib.process_runner import ProcessExecutionError


EMBEDDED_WORKER_CHECKS = (
    "check_worker_multimodal_full_chain_contract_e2e.py",
    "check_worker_multimodal_full_chain_e2e.py",
    "check_worker_multimodal_publication_e2e.py",
    "check_worker_visual_enrichment_producer_e2e.py",
    "check_worker_visual_enrichment_producer_e2e_v2.py",
)

DAEMON_WORKER_CHECKS = (
    "smoke_pdf_ingestion_e2e.py",
    "smoke_pdf_multisegment_resume.py",
    "smoke_protected_pdf_detection_e2e.py",
    "smoke_protected_pdf_retry_e2e.py",
    "smoke_text_ingestion_e2e.py",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run ingestion and multimodal E2E tests against disposable platform services."
    )
    parser.add_argument("--skip-build", action="store_true", help="Reuse existing test images.")
    parser.add_argument(
        "--startup-delay-seconds",
        type=int,
        default=8,
        help="Additional delay after API and worker health checks complete.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=1200,
        help="Default timeout for each Docker Compose command.",
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
    if args.startup_delay_seconds < 0:
        print("ERROR: --startup-delay-seconds must not be negative", file=sys.stderr)
        return 2
    if args.timeout_seconds <= 0:
        print("ERROR: --timeout-seconds must be positive", file=sys.stderr)
        return 2

    install_signal_handlers()
    compose_files = [
        PROJECT_ROOT / "docker-compose.test.yml",
        PROJECT_ROOT / "docker-compose.ingestion-test.yml",
    ]

    print(
        f"Portable ingestion test orchestration: system={platform.system()} architecture={platform.machine()}",
        flush=True,
    )

    with EnvironmentScope() as environment:
        environment.ensure_ephemeral("TEST_MINIO_ACCESS_KEY", length=24, prefix="test")
        environment.ensure_ephemeral("TEST_MINIO_SECRET_KEY", length=48)

        try:
            compose = DockerCompose(
                project_root=PROJECT_ROOT,
                compose_files=compose_files,
                timeout_seconds=args.timeout_seconds,
            )
        except DockerComposeUnavailableError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2

        failed = False
        try:
            step("Reset isolated ingestion environment")
            compose.down()

            if not args.skip_build:
                step("Build isolated ingestion runtime")
                compose.run(
                    [
                        "build",
                        "migrator-test",
                        "api-test",
                        "api-server-test",
                        "ingestion-worker-test",
                    ]
                )

            step("Start isolated infrastructure")
            compose.run(["up", "-d", "postgres-test", "redis-test", "minio-test"])

            step("Apply migrations to disposable database")
            compose.run(["run", "--rm", "migrator-test"])

            for check in EMBEDDED_WORKER_CHECKS:
                step(check)
                compose.run(["run", "--rm", "api-test", "python", f"/app/scripts/{check}"])

            step("Start isolated API and ingestion worker")
            compose.run(["up", "-d", "--wait", "api-server-test", "ingestion-worker-test"])

            if args.startup_delay_seconds:
                time.sleep(args.startup_delay_seconds)

            for check in DAEMON_WORKER_CHECKS:
                step(check)
                compose.run(["run", "--rm", "api-test", "python", f"/app/scripts/{check}"])

            print("\nIsolated ingestion and multimodal tests passed.", flush=True)
            return 0
        except KeyboardInterrupt:
            failed = True
            print("\nIngestion isolated test execution interrupted.", file=sys.stderr, flush=True)
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
                compose.diagnostic_logs(
                    [
                        "postgres-test",
                        "redis-test",
                        "minio-test",
                        "api-server-test",
                        "ingestion-worker-test",
                    ]
                )
            step("Dispose isolated ingestion environment")
            compose.down()


if __name__ == "__main__":
    raise SystemExit(main())
