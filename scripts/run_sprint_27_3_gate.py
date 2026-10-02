#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen


PROJECT_ROOT = Path(__file__).resolve().parents[1]
API_URL = "http://127.0.0.1:8000"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the Sprint 27.3 deterministic startup and readiness gate."
    )
    parser.add_argument("--skip-build", action="store_true")
    parser.add_argument("--skip-portal-build", action="store_true")
    parser.add_argument("--skip-baseline", action="store_true")
    parser.add_argument("--health-timeout-seconds", type=int, default=120)
    parser.add_argument("--timeout-seconds", type=int, default=1200)
    return parser.parse_args()


def run(command: list[str]) -> None:
    subprocess.run(command, cwd=PROJECT_ROOT, check=True)


def wait_command(command: list[str], timeout_seconds: int) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        result = subprocess.run(command, cwd=PROJECT_ROOT, check=False)
        if result.returncode == 0:
            return
        time.sleep(2)
    raise RuntimeError(f"command did not recover: {' '.join(command)}")


def get_json(path: str) -> tuple[int, dict[str, object]]:
    try:
        with urlopen(f"{API_URL}{path}", timeout=10) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def wait_dependency(name: str, lifecycle_state: str, timeout_seconds: int) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            status_code, payload = get_json("/health/dependencies")
            dependencies = {
                item["name"]: item
                for item in payload.get("dependencies", [])
                if isinstance(item, dict)
            }
            item = dependencies.get(name)
            if isinstance(item, dict) and item.get("lifecycle_state") == lifecycle_state:
                return
        except Exception:
            pass
        time.sleep(2)
    raise RuntimeError(
        f"dependency {name} did not reach lifecycle state {lifecycle_state}"
    )


def container_id(compose: list[str], service: str) -> str:
    result = subprocess.run(
        [*compose, "ps", "-q", service],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    value = result.stdout.strip()
    if not value:
        raise RuntimeError(f"service {service} has no running container")
    return value


def wait_ready(expected_status: int, timeout_seconds: int) -> dict[str, object]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            status_code, payload = get_json("/health/ready")
            if status_code == expected_status:
                return payload
        except Exception:
            pass
        time.sleep(2)
    raise RuntimeError(f"readiness did not reach HTTP {expected_status}")


def main() -> int:
    args = parse_args()
    baseline = [
        sys.executable,
        str(PROJECT_ROOT / "scripts/run_sprint_27_2_gate.py"),
        "--health-timeout-seconds",
        str(args.health_timeout_seconds),
        "--timeout-seconds",
        str(args.timeout_seconds),
    ]
    if args.skip_build:
        baseline.append("--skip-build")
    if args.skip_portal_build:
        baseline.append("--skip-portal-build")
    if not args.skip_baseline:
        run(baseline)

    compose = ["docker", "compose", "--profile", "ingestion"]
    run([*compose, "up", "-d", "--wait", "minio", "redis"])
    run([*compose, "run", "--rm", "minio-init"])
    wait_dependency("object_storage", "ready", args.health_timeout_seconds)
    wait_dependency("redis_secret_store", "ready", args.health_timeout_seconds)

    run(
        [
            sys.executable,
            str(
                PROJECT_ROOT
                / "apps/api/scripts/check_dependency_startup_recovery_contract.py"
            ),
            "--compose-file",
            str(PROJECT_ROOT / "docker-compose.yml"),
        ]
    )
    run(
        [
            *compose,
            "exec",
            "-T",
            "-e",
            "PYTHONPATH=/app",
            "api",
            "python",
            "/app/scripts/check_dependency_lifecycle_behavior.py",
        ]
    )

    persistent_services = ("api", "scheduler", "worker-monitor", "lease-reconciler")
    before_ids = {name: container_id(compose, name) for name in persistent_services}
    run([*compose, "stop", "postgres"])
    live_status, live = get_json("/health/live")
    if live_status != 200 or live.get("lifecycle_state") != "alive":
        raise RuntimeError("API liveness failed during PostgreSQL interruption")
    not_ready = wait_ready(503, args.health_timeout_seconds)
    if not_ready.get("lifecycle_state") != "unavailable":
        raise RuntimeError("required dependency outage was not reported unavailable")
    run([*compose, "start", "postgres"])
    wait_dependency("postgresql", "ready", args.health_timeout_seconds)
    ready = wait_ready(200, args.health_timeout_seconds)
    if ready.get("lifecycle_state") != "ready":
        raise RuntimeError("core readiness did not recover after PostgreSQL restart")
    after_ids = {name: container_id(compose, name) for name in persistent_services}
    if before_ids != after_ids:
        raise RuntimeError("persistent services restarted during dependency recovery")
    wait_command(
        [
            *compose,
            "exec",
            "-T",
            "-e",
            "PYTHONPATH=/app",
            "api",
            "python",
            "/app/scripts/check_runtime_managed_services_e2e.py",
        ],
        args.health_timeout_seconds,
    )
    wait_command(
        [*compose, "exec", "-T", "scheduler", "python", "scheduler_healthcheck.py"],
        args.health_timeout_seconds,
    )

    run([*compose, "stop", "redis"])
    wait_dependency("redis_secret_store", "degraded", args.health_timeout_seconds)
    ready_status, ready = get_json("/health/ready")
    if ready_status != 200 or ready.get("lifecycle_state") != "ready":
        raise RuntimeError("optional Redis interruption blocked core readiness")

    run([*compose, "start", "redis"])
    wait_dependency("redis_secret_store", "ready", args.health_timeout_seconds)
    print("\nSprint 27.3 deterministic startup and readiness gate passed.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
