from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
SUPERVISOR = ROOT / "scripts" / "local_platform.py"
API_BASE_URL = "http://127.0.0.1:8000"
EVIDENCE_PATH = ROOT / "runtime" / "evidence" / "runtime-resilience.json"


def run(command: list[str], *, env: dict[str, str], capture: bool = False) -> str:
    print("+", " ".join(command), flush=True)
    completed = subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        check=False,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )
    if completed.returncode:
        detail = (completed.stderr or completed.stdout or "").strip() if capture else ""
        raise RuntimeError(f"command failed ({completed.returncode}): {' '.join(command)}\n{detail}")
    return completed.stdout.strip() if capture else ""


def request_json(method: str, path: str, payload: dict[str, Any] | None = None, timeout: float = 15) -> tuple[int, Any, float]:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(
        f"{API_BASE_URL}{path}",
        data=body,
        method=method,
        headers={"Content-Type": "application/json"} if body is not None else {},
    )
    started = time.perf_counter()
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            return response.status, json.loads(raw) if raw else None, time.perf_counter() - started
    except HTTPError as exc:
        raw = exc.read().decode("utf-8")
        raise RuntimeError(f"HTTP {exc.code} for {method} {path}: {raw}") from exc


def wait_ready(timeout: float = 120) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            status, payload, _ = request_json("GET", "/health/ready", timeout=5)
            if status == 200 and payload.get("status") == "ready":
                return
        except Exception as exc:
            last_error = exc
            time.sleep(1)
    raise RuntimeError(f"API readiness timeout: {last_error}")


def percentile(values: list[float], percent: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * percent))))
    return ordered[index]


def environment() -> dict[str, str]:
    value = os.environ.copy()
    value.update(
        {
            "FEATURE_EMBEDDINGS_ENABLED": "false",
            "FEATURE_VECTOR_RETRIEVAL_ENABLED": "false",
            "FEATURE_ENTERPRISE_EXTENSIONS_ENABLED": "false",
            "FEATURE_WORKER_ENABLED": "false",
            "CONTAINER_OBJECT_STORAGE_ENDPOINT_URL": "",
            "CONTAINER_OBJECT_STORAGE_ACCESS_KEY": "",
            "CONTAINER_OBJECT_STORAGE_SECRET_KEY": "",
            "CONTAINER_OBJECT_STORAGE_BUCKET": "",
        }
    )
    return value


def concurrent_gets(path: str, requests: int, concurrency: int) -> dict[str, Any]:
    latencies: list[float] = []
    failures: list[str] = []

    def call() -> float:
        status, _, elapsed = request_json("GET", path)
        if status != 200:
            raise RuntimeError(f"unexpected status {status}")
        return elapsed

    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [executor.submit(call) for _ in range(requests)]
        for future in as_completed(futures):
            try:
                latencies.append(future.result())
            except Exception as exc:
                failures.append(str(exc))
    duration = time.perf_counter() - started
    return {
        "path": path,
        "requests": requests,
        "concurrency": concurrency,
        "successes": len(latencies),
        "failures": len(failures),
        "failure_samples": failures[:5],
        "duration_seconds": round(duration, 3),
        "throughput_rps": round(len(latencies) / duration, 3) if duration else 0.0,
        "latency_ms": {
            "min": round(min(latencies) * 1000, 3) if latencies else 0.0,
            "mean": round(statistics.fmean(latencies) * 1000, 3) if latencies else 0.0,
            "p50": round(percentile(latencies, 0.50) * 1000, 3),
            "p95": round(percentile(latencies, 0.95) * 1000, 3),
            "max": round(max(latencies) * 1000, 3) if latencies else 0.0,
        },
    }


def create_resource(index: int, token: str) -> tuple[str, float]:
    status, payload, elapsed = request_json(
        "POST",
        "/api/core/organizations",
        {
            "slug": f"resilience-{token}-{index}",
            "name": f"Runtime Resilience Resource {index}",
            "description": "Temporary generic resource for bounded concurrency validation.",
            "status": "active",
            "config": {"resilience_test": True, "index": index},
        },
    )
    if status != 201:
        raise RuntimeError(f"unexpected create status {status}")
    return str(payload["id"]), elapsed


def delete_resource(resource_id: str) -> float:
    status, _, elapsed = request_json("DELETE", f"/api/core/organizations/{resource_id}")
    if status != 204:
        raise RuntimeError(f"unexpected delete status {status}")
    return elapsed


def concurrent_resource_cycle(count: int, concurrency: int) -> dict[str, Any]:
    token = uuid4().hex
    ids: list[str] = []
    create_latencies: list[float] = []
    delete_latencies: list[float] = []
    failures: list[str] = []

    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [executor.submit(create_resource, index, token) for index in range(count)]
        for future in as_completed(futures):
            try:
                resource_id, elapsed = future.result()
                ids.append(resource_id)
                create_latencies.append(elapsed)
            except Exception as exc:
                failures.append(str(exc))

    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [executor.submit(delete_resource, resource_id) for resource_id in ids]
        for future in as_completed(futures):
            try:
                delete_latencies.append(future.result())
            except Exception as exc:
                failures.append(str(exc))

    return {
        "requested_resources": count,
        "created_resources": len(ids),
        "deleted_resources": len(delete_latencies),
        "failures": len(failures),
        "failure_samples": failures[:5],
        "create_p95_ms": round(percentile(create_latencies, 0.95) * 1000, 3),
        "delete_p95_ms": round(percentile(delete_latencies, 0.95) * 1000, 3),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run bounded load and runtime resilience validation")
    parser.add_argument("--requests", type=int, default=200)
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--resources", type=int, default=25)
    parser.add_argument("--max-p95-ms", type=float, default=1500.0)
    return parser.parse_args()


def write_evidence(payload: dict[str, Any]) -> None:
    EVIDENCE_PATH.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(f"Evidence: {EVIDENCE_PATH}")


def main() -> int:
    args = parse_args()
    env = environment()
    evidence: dict[str, Any] = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "status": "running",
        "bounded": True,
        "api_url": API_BASE_URL,
        "ai_required": False,
        "configuration": {
            "requests": args.requests,
            "concurrency": args.concurrency,
            "resources": args.resources,
            "max_p95_ms": args.max_p95_ms,
        },
        "steps": [],
    }

    try:
        run([sys.executable, str(SUPERVISOR), "compose-down"], env=env)
        run([sys.executable, str(SUPERVISOR), "compose-up", "--build", "--keep-failed"], env=env)
        wait_ready()
        evidence["steps"].append("platform_started")

        _, dependencies, _ = request_json("GET", "/health/dependencies")
        evidence["dependency_snapshot_before"] = dependencies
        if dependencies.get("status") != "healthy":
            raise RuntimeError(f"dependency health is not healthy: {dependencies}")
        evidence["steps"].append("dependencies_verified")

        live_load = concurrent_gets("/health/live", args.requests, args.concurrency)
        ready_load = concurrent_gets("/health/ready", args.requests, args.concurrency)
        evidence["live_load"] = live_load
        evidence["ready_load"] = ready_load
        if live_load["failures"] or ready_load["failures"]:
            raise RuntimeError("health load produced failed requests")
        if live_load["latency_ms"]["p95"] > args.max_p95_ms or ready_load["latency_ms"]["p95"] > args.max_p95_ms:
            raise RuntimeError("health endpoint p95 exceeded the configured bounded threshold")
        evidence["steps"].append("bounded_health_load_passed")

        resource_cycle = concurrent_resource_cycle(args.resources, min(args.concurrency, args.resources))
        evidence["resource_cycle"] = resource_cycle
        if resource_cycle["failures"] or resource_cycle["created_resources"] != args.resources or resource_cycle["deleted_resources"] != args.resources:
            raise RuntimeError(f"concurrent resource cycle failed: {resource_cycle}")
        evidence["steps"].append("concurrent_resource_cycle_passed")

        run(["docker", "compose", "restart", "api"], env=env)
        wait_ready()
        evidence["steps"].append("api_restart_recovered")

        _, dependencies_after, _ = request_json("GET", "/health/dependencies")
        evidence["dependency_snapshot_after"] = dependencies_after
        if dependencies_after.get("status") != "healthy":
            raise RuntimeError(f"dependencies did not recover after API restart: {dependencies_after}")
        evidence["steps"].append("dependencies_recovered")

        evidence["status"] = "passed"
        evidence["completed_at"] = datetime.now(timezone.utc).isoformat()
        return 0
    except Exception as exc:
        evidence["status"] = "failed"
        evidence["error"] = str(exc)
        evidence["completed_at"] = datetime.now(timezone.utc).isoformat()
        print(f"RUNTIME RESILIENCE FAILED: {exc}", file=sys.stderr)
        return 1
    finally:
        try:
            run([sys.executable, str(SUPERVISOR), "compose-down"], env=env)
            evidence["steps"].append("clean_shutdown")
        except Exception as shutdown_error:
            evidence["shutdown_error"] = str(shutdown_error)
        write_evidence(evidence)


if __name__ == "__main__":
    raise SystemExit(main())
