from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
SUPERVISOR = ROOT / "scripts" / "local_platform.py"
API_URL = "http://127.0.0.1:8000"
PORTAL_URL = "http://127.0.0.1:3000"

PLATFORM_CONFIGURATION_PATH = "/platform/configuration"
PLATFORM_STATUS_PATH = "/platform/status"

EVIDENCE_PATH = ROOT / "runtime" / "evidence" / "admin-portal-validation.json"

ROUTES = (
    "/",
    "/operations",
    "/organization",
    "/documents",
    "/knowledge",
    "/connectors",
    "/runtime",
    "/scheduler",
    "/ai",
)


def run(command: list[str], *, env: dict[str, str]) -> None:
    print("+", " ".join(command), flush=True)
    completed = subprocess.run(command, cwd=ROOT, env=env, check=False)
    if completed.returncode:
        raise RuntimeError(f"command failed ({completed.returncode}): {' '.join(command)}")


def fetch_text(url: str, timeout: float = 15) -> tuple[int, str, float]:
    started = time.perf_counter()
    with urlopen(url, timeout=timeout) as response:
        body = response.read().decode("utf-8", errors="replace")
        return response.status, body, time.perf_counter() - started


def fetch_json(url: str) -> tuple[int, Any, float]:
    status, body, elapsed = fetch_text(url)
    return status, json.loads(body), elapsed


def wait_ready(timeout: float = 120) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            status, payload, _ = fetch_json(f"{API_URL}/health/ready")
            if status == 200 and payload.get("status") == "ready":
                status, _, _ = fetch_text(f"{PORTAL_URL}/operations")
                if status == 200:
                    return
        except Exception as exc:
            last_error = exc
            time.sleep(1)
    raise RuntimeError(f"portal readiness timeout: {last_error}")


def environment() -> dict[str, str]:
    value = os.environ.copy()
    value.update(
        {
            "API_PORT": "8000",
            "PORTAL_PORT": "3000",
            "API_INTERNAL_BASE_URL": "http://api:8000",
            "FEATURE_EMBEDDINGS_ENABLED": "false",
            "FEATURE_VECTOR_RETRIEVAL_ENABLED": "false",
            "FEATURE_ENTERPRISE_EXTENSIONS_ENABLED": "false",
        }
    )
    return value


def validate_route(path: str) -> dict[str, Any]:
    status, body, elapsed = fetch_text(f"{PORTAL_URL}{path}")
    return {
        "path": path,
        "status": status,
        "duration_ms": round(elapsed * 1000, 3),
        "html_present": "<html" in body.lower(),
        "platform_title_present": "Industrial AI Platform" in body,
        "next_payload_present": "__next" in body.lower() or "_next/" in body.lower(),
        "body_length": len(body),
    }


def write_evidence(payload: dict[str, Any]) -> None:
    EVIDENCE_PATH.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(f"Evidence: {EVIDENCE_PATH}")


def main() -> int:
    env = environment()
    evidence: dict[str, Any] = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "status": "running",
        "api_url": API_URL,
        "portal_url": PORTAL_URL,
        "routes": [],
        "steps": [],
    }

    try:
        run([sys.executable, str(SUPERVISOR), "compose-down"], env=env)
        run([sys.executable, str(SUPERVISOR), "compose-up", "--build", "--keep-failed"], env=env)
        wait_ready()
        evidence["steps"].append("platform_started")

        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(validate_route, route) for route in ROUTES]
            for future in as_completed(futures):
                evidence["routes"].append(future.result())
        evidence["routes"] = sorted(evidence["routes"], key=lambda item: item["path"])

        failed_routes = [
            item
            for item in evidence["routes"]
            if item["status"] != 200
            or not item["html_present"]
            or not item["platform_title_present"]
            or not item["next_payload_present"]
        ]
        if failed_routes:
            raise RuntimeError(f"portal route validation failed: {failed_routes}")
        evidence["steps"].append("all_routes_rendered")

        status, configuration, _ = fetch_json(f"{API_URL}{PLATFORM_CONFIGURATION_PATH}")
        if status != 200:
            raise RuntimeError(f"configuration endpoint returned {status}")
        if configuration.get("portal_port") != 3000:
            raise RuntimeError(f"unexpected portal port: {configuration.get('portal_port')}")
        cors_origins = configuration.get("cors_origins", [])
        if not any(origin in {"http://127.0.0.1:3000", "http://localhost:3000"} for origin in cors_origins):
            raise RuntimeError(f"portal origin missing from effective CORS configuration: {cors_origins}")
        evidence["configuration"] = configuration
        evidence["steps"].append("api_configuration_verified")

        status, platform, _ = fetch_json(f"{API_URL}{PLATFORM_STATUS_PATH}")
        if status != 200:
            raise RuntimeError(f"platform status returned {status}")
        evidence["platform"] = platform
        evidence["steps"].append("platform_metadata_verified")

        evidence["status"] = "passed"
        evidence["completed_at"] = datetime.now(timezone.utc).isoformat()
        return 0
    except Exception as exc:
        evidence["status"] = "failed"
        evidence["error"] = str(exc)
        evidence["completed_at"] = datetime.now(timezone.utc).isoformat()
        print(f"ADMIN PORTAL VALIDATION FAILED: {exc}", file=sys.stderr)
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
