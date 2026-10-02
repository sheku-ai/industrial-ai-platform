#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import signal
import sys
import time
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve()
PROJECT_ROOT = SCRIPT_PATH.parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.lib.docker_compose import DockerCompose, DockerComposeUnavailableError
from scripts.lib.process_runner import ProcessExecutionError, run_process

CONTRACT_CHECKS = (
    "check_platform_scope_authorization_contract.py",
    "check_runtime_production_alignment_contract.py",
    "check_runtime_worker_control_contract.py",
    "check_runtime_worker_health_contract.py",
    "check_runtime_worker_readiness_api_contract.py",
    "check_runtime_worker_audit_contract.py",
    "check_runtime_worker_history_api_contract.py",
    "check_runtime_lease_reconciliation_contract.py",
    "check_runtime_managed_services_contract.py",
    "check_managed_service_health_contract.py",
    "check_runtime_worker_summary_contract.py",
    "check_organization_health_scope_contract.py",
)
MANAGED_SERVICES = {"worker-monitor", "lease-reconciler"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the portable Sprint 26.3 validation gate.")
    parser.add_argument("--skip-build", action="store_true", help="Reuse existing container images.")
    parser.add_argument("--skip-portal-build", action="store_true", help="Skip portal contracts and build.")
    parser.add_argument("--health-timeout-seconds", type=int, default=120)
    parser.add_argument("--timeout-seconds", type=int, default=1200)
    return parser.parse_args()


def install_signal_handlers() -> None:
    def _handle_signal(signum: int, _frame) -> None:
        raise KeyboardInterrupt(f"received signal {signum}")

    signal.signal(signal.SIGINT, _handle_signal)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _handle_signal)


def step(name: str) -> None:
    print(f"\n=== {name} ===", flush=True)


def count_test_organizations(compose: DockerCompose) -> int:
    result = compose.run(
        [
            "exec",
            "-T",
            "-e",
            "PYTHONPATH=/app",
            "api",
            "python",
            "/app/scripts/count_test_organizations.py",
            "--value-only",
        ],
        stream=False,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(
            f"failed to count test organizations with exit code {result.returncode}: {detail}"
        )
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError("test organization counter returned no output")
    return int(lines[-1])


def compose_statuses(compose: DockerCompose) -> list[dict[str, object]]:
    result = compose.run(["ps", "--format", "json"], stream=False)
    output = result.stdout.strip()
    if not output:
        return []
    try:
        parsed = json.loads(output)
        return parsed if isinstance(parsed, list) else [parsed]
    except json.JSONDecodeError:
        return [json.loads(line) for line in output.splitlines() if line.strip()]


def wait_service_healthy(compose: DockerCompose, service: str, timeout_seconds: int) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        status = next(
            (
                item
                for item in compose_statuses(compose)
                if str(item.get("Service")) == service
            ),
            None,
        )
        if status is not None:
            health = str(status.get("Health", ""))
            state = str(status.get("State", ""))
            if health == "healthy":
                return
            if health == "unhealthy" or state in {"exited", "dead"}:
                raise RuntimeError(f"service {service} failed readiness: state={state} health={health}")
            print(f"Waiting for {service}: state={state or 'unknown'} health={health or 'starting'}", flush=True)
        else:
            print(f"Waiting for {service} to appear", flush=True)
        time.sleep(3)
    compose.run(["ps"], check=False)
    raise RuntimeError(f"service {service} did not become healthy within {timeout_seconds} seconds")


def wait_managed_services_healthy(compose: DockerCompose, timeout_seconds: int) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        statuses = {
            str(item.get("Service")): str(item.get("Health", ""))
            for item in compose_statuses(compose)
            if str(item.get("Service")) in MANAGED_SERVICES
        }
        unhealthy = {name: health for name, health in statuses.items() if health == "unhealthy"}
        if unhealthy:
            detail = ", ".join(f"{name}={health}" for name, health in sorted(unhealthy.items()))
            raise RuntimeError(f"Managed service healthcheck failed: {detail}")
        if set(statuses) == MANAGED_SERVICES and all(value == "healthy" for value in statuses.values()):
            compose.run(["ps"])
            return
        detail = ", ".join(f"{name}={statuses.get(name, 'missing')}" for name in sorted(MANAGED_SERVICES))
        print(f"Waiting for managed services: {detail}", flush=True)
        time.sleep(5)
    compose.run(["ps"], check=False)
    raise RuntimeError(f"Managed services did not become healthy within {timeout_seconds} seconds")


def run_python_runner(path: Path, args: argparse.Namespace) -> None:
    command = [sys.executable, str(path), "--timeout-seconds", str(args.timeout_seconds)]
    if args.skip_build:
        command.append("--skip-build")
    run_process(command, cwd=PROJECT_ROOT, timeout_seconds=args.timeout_seconds)


def main() -> int:
    args = parse_args()
    if args.health_timeout_seconds <= 0 or args.timeout_seconds <= 0:
        print("ERROR: timeout values must be positive", file=sys.stderr)
        return 2

    install_signal_handlers()
    try:
        compose = DockerCompose(
            project_root=PROJECT_ROOT,
            compose_files=[PROJECT_ROOT / "docker-compose.yml"],
            profiles=["ingestion"],
            timeout_seconds=args.timeout_seconds,
        )
    except DockerComposeUnavailableError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    try:
        if not args.skip_build:
            step("Build runtime control plane")
            compose.run(["build", "api", "worker-monitor", "lease-reconciler"])

        step("Start Redis")
        compose.run(["up", "-d", "redis"])
        wait_service_healthy(compose, "redis", args.health_timeout_seconds)

        step("Start API control plane")
        compose.run(["up", "-d", "--force-recreate", "api"])
        wait_service_healthy(compose, "api", args.health_timeout_seconds)

        step("Start managed runtime services")
        compose.run(["up", "-d", "--force-recreate", "worker-monitor", "lease-reconciler"])

        baseline = count_test_organizations(compose)
        print(f"Persistent test organization baseline: {baseline}", flush=True)

        step("Canonical Compose exclusivity")
        run_process(
            [sys.executable, str(PROJECT_ROOT / "apps/api/scripts/check_canonical_compose_exclusivity.py")],
            cwd=PROJECT_ROOT,
            timeout_seconds=args.timeout_seconds,
        )

        step("Compose contract")
        run_process(
            [
                sys.executable,
                str(PROJECT_ROOT / "apps/api/scripts/check_runtime_control_plane_compose_contract.py"),
                "--compose-file",
                str(PROJECT_ROOT / "docker-compose.yml"),
            ],
            cwd=PROJECT_ROOT,
            timeout_seconds=args.timeout_seconds,
        )

        for check in CONTRACT_CHECKS:
            step(check)
            compose.run(["exec", "-T", "-e", "PYTHONPATH=/app", "api", "python", f"/app/scripts/{check}"])

        step("Managed services E2E")
        compose.run([
            "exec", "-T", "-e", "PYTHONPATH=/app", "api", "python",
            "/app/scripts/check_runtime_managed_services_e2e.py",
        ])

        step("Isolated runtime domains")
        run_python_runner(PROJECT_ROOT / "scripts/run_runtime_isolated_domain_tests.py", args)

        step("Isolated ingestion and multimodal domains")
        run_python_runner(PROJECT_ROOT / "scripts/run_ingestion_multimodal_isolated_tests.py", args)

        step("Managed service health")
        wait_managed_services_healthy(compose, args.health_timeout_seconds)

        if not args.skip_portal_build:
            portal = PROJECT_ROOT / "apps/admin-portal"
            step("Portal contracts and build")
            run_process(["npm", "run", "check:operations"], cwd=portal, timeout_seconds=args.timeout_seconds)
            run_process(
                ["node", "scripts/check-organization-health-scope-contract.mjs"],
                cwd=portal,
                timeout_seconds=args.timeout_seconds,
            )
            run_process(["npm", "run", "build"], cwd=portal, timeout_seconds=args.timeout_seconds)

        final_count = count_test_organizations(compose)
        print(f"Persistent test organization final count: {final_count}", flush=True)
        if final_count != baseline:
            raise RuntimeError(
                f"Persistent test organization count changed during gate: before={baseline} after={final_count}"
            )

        print("\nSprint 26.3 gate passed.", flush=True)
        return 0
    except KeyboardInterrupt:
        print("\nSprint 26.3 gate interrupted.", file=sys.stderr, flush=True)
        return 130
    except ProcessExecutionError as exc:
        print(f"\nERROR: {exc}", file=sys.stderr, flush=True)
        return exc.result.returncode or 1
    except Exception as exc:
        print(f"\nERROR: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
