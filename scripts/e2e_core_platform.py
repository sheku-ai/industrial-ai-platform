from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
SUPERVISOR = ROOT / "scripts" / "local_platform.py"
API_BASE_URL = "http://127.0.0.1:8000"
PORTAL_URL = "http://127.0.0.1:3000/operations"
EVIDENCE_PATH = ROOT / "runtime" / "evidence" / "core-platform-e2e.json"


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
    if completed.returncode != 0:
        detail = ""
        if capture:
            detail = (completed.stderr or completed.stdout or "").strip()
        raise RuntimeError(f"command failed ({completed.returncode}): {' '.join(command)}\n{detail}")
    return completed.stdout.strip() if capture else ""


def request_json(method: str, path: str, payload: dict[str, Any] | None = None) -> tuple[int, Any]:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(
        f"{API_BASE_URL}{path}",
        data=body,
        method=method,
        headers={"Content-Type": "application/json"} if body is not None else {},
    )
    try:
        with urlopen(request, timeout=15) as response:
            raw = response.read().decode("utf-8")
            return response.status, json.loads(raw) if raw else None
    except HTTPError as exc:
        raw = exc.read().decode("utf-8")
        raise RuntimeError(f"HTTP {exc.code} for {method} {path}: {raw}") from exc


def wait_http(url: str, timeout: float = 120) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urlopen(url, timeout=5) as response:
                if 200 <= response.status < 500:
                    return
        except Exception as exc:
            last_error = exc
            time.sleep(1)
    raise RuntimeError(f"endpoint unavailable: {url}; last_error={last_error}")


def compose_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment.update(
        {
            "API_PORT": "8000",
            "PORTAL_PORT": "3000",
            "API_INTERNAL_BASE_URL": "http://api:8000",
            "FEATURE_EMBEDDINGS_ENABLED": "false",
            "FEATURE_VECTOR_RETRIEVAL_ENABLED": "false",
            "FEATURE_WORKER_ENABLED": "false",
            "FEATURE_ENTERPRISE_EXTENSIONS_ENABLED": "false",
            "CONTAINER_OBJECT_STORAGE_ENDPOINT_URL": "",
            "CONTAINER_OBJECT_STORAGE_ACCESS_KEY": "",
            "CONTAINER_OBJECT_STORAGE_SECRET_KEY": "",
            "CONTAINER_OBJECT_STORAGE_BUCKET": "",
        }
    )
    return environment


def verify_postgresql(slug: str, *, env: dict[str, str]) -> int:
    sql = f"SELECT count(*) FROM core.organizations WHERE slug = '{slug}';"
    output = run(
        [
            "docker",
            "compose",
            "exec",
            "-T",
            "postgres",
            "psql",
            "-U",
            os.getenv("POSTGRES_USER", "industrial_ai"),
            "-d",
            os.getenv("POSTGRES_DB", "industrial_ai"),
            "-tAc",
            sql,
        ],
        env=env,
        capture=True,
    )
    try:
        return int(output.splitlines()[-1].strip())
    except (ValueError, IndexError) as exc:
        raise RuntimeError(f"unexpected PostgreSQL verification output: {output!r}") from exc


def write_evidence(payload: dict[str, Any]) -> None:
    EVIDENCE_PATH.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(f"Evidence: {EVIDENCE_PATH}")


def main() -> int:
    env = compose_environment()
    slug = f"core-e2e-{uuid4().hex}"
    resource_id: str | None = None
    started_at = datetime.now(timezone.utc)
    evidence: dict[str, Any] = {
        "started_at": started_at.isoformat(),
        "api_url": API_BASE_URL,
        "portal_url": PORTAL_URL,
        "ai_required": False,
        "embeddings_enabled": False,
        "vector_retrieval_enabled": False,
        "object_storage_enabled": False,
        "resource_slug": slug,
        "steps": [],
        "status": "running",
    }

    try:
        run([sys.executable, str(SUPERVISOR), "compose-down"], env=env)
        evidence["steps"].append("clean_stack")

        run([sys.executable, str(SUPERVISOR), "compose-up", "--build", "--keep-failed"], env=env)
        wait_http(f"{API_BASE_URL}/health/ready")
        wait_http(PORTAL_URL)
        evidence["steps"].append("initial_startup")

        status_code, created = request_json(
            "POST",
            "/api/core/organizations",
            {
                "slug": slug,
                "name": "Core Platform E2E Resource",
                "description": "Generic persistent resource created by the core platform E2E.",
                "status": "active",
                "config": {"e2e": True, "requires_ai": False},
            },
        )
        if status_code != 201:
            raise RuntimeError(f"unexpected create status: {status_code}")
        resource_id = str(created["id"])
        evidence["resource_id"] = resource_id
        evidence["steps"].append("resource_created")

        status_code, fetched = request_json("GET", f"/api/core/organizations/{resource_id}")
        if status_code != 200 or fetched["slug"] != slug:
            raise RuntimeError("created resource could not be retrieved before restart")
        evidence["steps"].append("resource_retrieved_before_restart")

        before_count = verify_postgresql(slug, env=env)
        if before_count != 1:
            raise RuntimeError(f"expected one PostgreSQL row before restart, found {before_count}")
        evidence["postgresql_count_before_restart"] = before_count
        evidence["steps"].append("postgresql_persistence_verified")

        run([sys.executable, str(SUPERVISOR), "compose-down"], env=env)
        run([sys.executable, str(SUPERVISOR), "compose-up", "--keep-failed"], env=env)
        wait_http(f"{API_BASE_URL}/health/ready")
        wait_http(PORTAL_URL)
        evidence["steps"].append("stack_restarted")

        status_code, fetched_after = request_json("GET", f"/api/core/organizations/{resource_id}")
        if status_code != 200 or fetched_after["slug"] != slug:
            raise RuntimeError("resource did not persist across stack restart")
        after_count = verify_postgresql(slug, env=env)
        if after_count != 1:
            raise RuntimeError(f"expected one PostgreSQL row after restart, found {after_count}")
        evidence["postgresql_count_after_restart"] = after_count
        evidence["steps"].append("resource_persisted_after_restart")

        delete_status, _ = request_json("DELETE", f"/api/core/organizations/{resource_id}")
        if delete_status != 204:
            raise RuntimeError(f"unexpected cleanup status: {delete_status}")
        resource_id = None
        evidence["steps"].append("resource_cleaned")

        evidence["status"] = "passed"
        evidence["completed_at"] = datetime.now(timezone.utc).isoformat()
        return 0
    except Exception as exc:
        evidence["status"] = "failed"
        evidence["error"] = str(exc)
        evidence["completed_at"] = datetime.now(timezone.utc).isoformat()
        print(f"E2E FAILED: {exc}", file=sys.stderr)
        return 1
    finally:
        if resource_id is not None:
            try:
                request_json("DELETE", f"/api/core/organizations/{resource_id}")
            except Exception:
                pass
        try:
            run([sys.executable, str(SUPERVISOR), "compose-down"], env=env)
            evidence["steps"].append("clean_shutdown")
        except Exception as shutdown_error:
            evidence["shutdown_error"] = str(shutdown_error)
        write_evidence(evidence)


if __name__ == "__main__":
    raise SystemExit(main())
