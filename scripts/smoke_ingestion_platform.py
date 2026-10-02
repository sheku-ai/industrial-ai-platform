from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

try:
    import psycopg
except ImportError:  # pragma: no cover - environment validation
    psycopg = None


@dataclass
class StageResult:
    name: str
    status: str
    started_at: str
    completed_at: str
    checks: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None


class SmokeFailure(RuntimeError):
    pass


class SmokeRunner:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.evidence_dir = Path(args.evidence_dir)
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        self.results: dict[str, StageResult] = {}

    def run_stage(self, order: int, name: str, fn: Callable[[], list[dict[str, Any]]]) -> None:
        started = now_iso()
        try:
            checks = fn()
            result = StageResult(name, "passed", started, now_iso(), checks)
        except Exception as exc:
            result = StageResult(name, "failed", started, now_iso(), error=str(exc))
            self.results[name] = result
            self.write_stage(order, result)
            self.write_summary()
            raise
        self.results[name] = result
        self.write_stage(order, result)

    def write_stage(self, order: int, result: StageResult) -> None:
        path = self.evidence_dir / f"{order:02d}-{result.name.replace('_', '-')}.json"
        path.write_text(json.dumps(asdict(result), indent=2, sort_keys=True), encoding="utf-8")

    def write_summary(self) -> None:
        passed = bool(self.results) and all(item.status == "passed" for item in self.results.values())
        payload = {
            "passed": passed,
            "completed_at": now_iso(),
            "api_url": self.args.api_url,
            "stages": {name: result.status for name, result in self.results.items()},
        }
        (self.evidence_dir / "summary.json").write_text(
            json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
        )


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_command(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(command, text=True, capture_output=True, check=False)
    if check and completed.returncode != 0:
        raise SmokeFailure(
            f"command failed ({completed.returncode}): {' '.join(command)}\n"
            f"stdout={completed.stdout.strip()}\nstderr={completed.stderr.strip()}"
        )
    return completed


def http_json(
    method: str,
    url: str,
    *,
    payload: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = 20,
) -> tuple[int, Any]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request_headers = {"Accept": "application/json", **(headers or {})}
    if data is not None:
        request_headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, method=method, headers=request_headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            return response.status, json.loads(body) if body else None
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        try:
            parsed = json.loads(body) if body else None
        except json.JSONDecodeError:
            parsed = body
        return exc.code, parsed


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SmokeFailure(message)


def _compose_service_command(config: dict[str, Any], service_name: str) -> list[str]:
    services = config.get("services")
    require(isinstance(services, dict), "Compose config does not contain services")
    service = services.get(service_name)
    require(isinstance(service, dict), f"Compose service is missing: {service_name}")
    command = service.get("command")
    if isinstance(command, str):
        return command.split()
    require(isinstance(command, list), f"Compose service has no command: {service_name}")
    return [str(value) for value in command]


def infrastructure_stage(args: argparse.Namespace) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    status, payload = http_json("GET", f"{args.api_url.rstrip('/')}/health/ready")
    require(status == 200, f"API readiness failed: {status} {payload}")
    checks.append({"check": "api_ready", "status": status})

    compose = run_command([
        "docker", "compose", "--profile", "ingestion", "--profile", "object-storage",
        "ps", "--format", "json",
    ])
    output = compose.stdout.strip()
    require(output, "docker compose ps returned no services")
    checks.append({"check": "docker_compose_ps", "output": output})

    config_result = run_command([
        "docker", "compose", "--profile", "ingestion", "--profile", "object-storage",
        "config", "--format", "json",
    ])
    try:
        config = json.loads(config_result.stdout)
    except json.JSONDecodeError as exc:
        raise SmokeFailure("docker compose config did not return valid JSON") from exc
    command = _compose_service_command(config, "ingestion-worker")
    command_text = " ".join(command)
    require(
        "app.workers.runtime_ingestion_worker" in command,
        f"runtime ingestion worker is not configured: {command}",
    )
    require(
        "app.workers.ingestion_bridge" not in command_text,
        "legacy ingestion bridge is still configured",
    )
    checks.append({"check": "worker_entrypoint", "command": command})
    return checks


def migrations_stage(args: argparse.Namespace) -> list[dict[str, Any]]:
    require(psycopg is not None, "psycopg is required for database smoke checks")
    checks: list[dict[str, Any]] = []
    with psycopg.connect(args.database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT version_num FROM alembic_version")
            versions = [row[0] for row in cursor.fetchall()]
            require(len(versions) == 1, f"expected one Alembic head, found {versions}")
            checks.append({"check": "alembic_version", "value": versions[0]})

            required_relations = [
                "documents.document_review_cases",
                "documents.document_review_events",
                "runtime.executions",
                "documents.chunks",
                "documents.ingestion_pipeline_profiles",
            ]
            for relation in required_relations:
                cursor.execute("SELECT to_regclass(%s)", (relation,))
                value = cursor.fetchone()[0]
                require(value is not None, f"missing relation: {relation}")
                checks.append({"check": "relation_exists", "relation": relation})
    return checks


def composition_stage(args: argparse.Namespace) -> list[dict[str, Any]]:
    code = """
from app.db.session import SessionLocal
from app.workers.runtime_registry import build_runtime_adapter_registry
registry = build_runtime_adapter_registry(session_factory=SessionLocal)
adapter = registry.resolve('document.ingestion')
assert adapter is not None
print(type(adapter).__name__)
print(type(adapter._delegate).__name__)
print(type(adapter._delegate._delegate).__name__)
print(','.join(adapter._delegate._delegate._pipeline._resolver.registered_adapter_keys()))
""".strip()
    completed = run_command([
        "docker", "compose", "--profile", "ingestion", "exec", "-T",
        "ingestion-worker", "python", "-c", code,
    ])
    lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    require(lines[:3] == [
        "ProtectedDocumentRuntimeAdapter",
        "DocumentIngestionStatusAdapter",
        "DocumentIngestionRuntimeAdapter",
    ], f"unexpected worker composition: {lines}")
    require("platform.text.plain" in lines[-1], "plain text adapter is not registered")
    require("platform.pdf.text_layer" in lines[-1], "PDF adapter is not registered")
    return [{"check": "runtime_composition", "chain": lines[:3], "adapters": lines[-1].split(",")}]


def database_integrity_stage(args: argparse.Namespace) -> list[dict[str, Any]]:
    require(psycopg is not None, "psycopg is required for database smoke checks")
    checks: list[dict[str, Any]] = []
    with psycopg.connect(args.database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT document_version_id, chunk_index, COUNT(*)
                FROM documents.chunks
                GROUP BY document_version_id, chunk_index
                HAVING COUNT(*) > 1
                """
            )
            duplicates = cursor.fetchall()
            require(not duplicates, f"duplicate chunk ordinals found: {duplicates[:10]}")
            checks.append({"check": "duplicate_chunk_ordinals", "count": 0})

            cursor.execute(
                """
                SELECT COUNT(*)
                FROM runtime.executions
                WHERE status = 'succeeded'
                  AND execution_type = 'document.ingestion'
                  AND COALESCE(metrics->>'validation_only', 'false') = 'true'
                """
            )
            simulated_successes = cursor.fetchone()[0]
            require(simulated_successes == 0, "validation-only ingestion executions were marked succeeded")
            checks.append({"check": "simulated_successes", "count": simulated_successes})
    return checks


def wait_for_execution(args: argparse.Namespace, execution_id: str) -> dict[str, Any]:
    require(psycopg is not None, "psycopg is required for execution polling")
    deadline = time.monotonic() + args.timeout_seconds
    terminal = {"succeeded", "failed", "cancelled"}
    while time.monotonic() < deadline:
        with psycopg.connect(args.database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT status, metrics, error_code, error_message FROM runtime.executions WHERE id = %s",
                    (execution_id,),
                )
                row = cursor.fetchone()
        if row and row[0] in terminal:
            return {"status": row[0], "metrics": row[1] or {}, "error_code": row[2], "error_message": row[3]}
        time.sleep(1)
    raise SmokeFailure(f"execution did not reach terminal state: {execution_id}")


def existing_execution_stage(args: argparse.Namespace) -> list[dict[str, Any]]:
    require(args.execution_id, "--execution-id is required for existing-execution stage")
    result = wait_for_execution(args, args.execution_id)
    require(result["status"] == args.expected_status, f"unexpected execution result: {result}")
    return [{"check": "execution_terminal", "execution_id": args.execution_id, **result}]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Industrial AI Platform ingestion smoke harness")
    parser.add_argument("--api-url", default=os.getenv("API_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL"))
    parser.add_argument("--evidence-dir", default="runtime/evidence/ingestion-smoke")
    parser.add_argument("--timeout-seconds", type=int, default=180)
    parser.add_argument("--execution-id")
    parser.add_argument("--expected-status", default="succeeded")
    parser.add_argument(
        "--stages",
        default="infrastructure,migrations,composition,database_integrity",
        help="comma-separated stages: infrastructure,migrations,composition,existing_execution,database_integrity",
    )
    args = parser.parse_args()
    if not args.database_url and any(
        stage in args.stages for stage in ("migrations", "existing_execution", "database_integrity")
    ):
        parser.error("--database-url or DATABASE_URL is required")
    return args


def main() -> int:
    args = parse_args()
    runner = SmokeRunner(args)
    stages = [value.strip() for value in args.stages.split(",") if value.strip()]
    available = {
        "infrastructure": infrastructure_stage,
        "migrations": migrations_stage,
        "composition": composition_stage,
        "existing_execution": existing_execution_stage,
        "database_integrity": database_integrity_stage,
    }
    try:
        for index, stage in enumerate(stages, start=1):
            require(stage in available, f"unknown stage: {stage}")
            runner.run_stage(index, stage, lambda fn=available[stage]: fn(args))
        runner.write_summary()
        print(json.dumps({"passed": True, "evidence_dir": str(runner.evidence_dir)}, indent=2))
        return 0
    except Exception as exc:
        print(json.dumps({"passed": False, "error": str(exc)}, indent=2), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
