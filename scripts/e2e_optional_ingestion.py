from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
SUPERVISOR = ROOT / "scripts" / "local_platform.py"
API_BASE_URL = "http://127.0.0.1:8000"
EVIDENCE_PATH = ROOT / "runtime" / "evidence" / "optional-ingestion-e2e.json"


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


def request_json(method: str, path: str, payload: dict[str, Any] | None = None) -> tuple[int, Any]:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(
        f"{API_BASE_URL}{path}",
        data=body,
        method=method,
        headers={"Content-Type": "application/json"} if body is not None else {},
    )
    try:
        with urlopen(request, timeout=20) as response:
            raw = response.read().decode("utf-8")
            return response.status, json.loads(raw) if raw else None
    except HTTPError as exc:
        raw = exc.read().decode("utf-8")
        raise RuntimeError(f"HTTP {exc.code} for {method} {path}: {raw}") from exc


def wait_ready(timeout: float = 120) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urlopen(f"{API_BASE_URL}/health/ready", timeout=5) as response:
                if response.status == 200:
                    return
        except Exception as exc:
            last_error = exc
            time.sleep(1)
    raise RuntimeError(f"API readiness timeout: {last_error}")


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


def sql(sql_text: str, *, env: dict[str, str]) -> str:
    return run(
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
            sql_text,
        ],
        env=env,
        capture=True,
    )


def cleanup(organization_id: str, *, env: dict[str, str]) -> None:
    statement = f"""
    BEGIN;
    DELETE FROM documents.indexing_jobs WHERE organization_id = '{organization_id}';
    DELETE FROM documents.chunks WHERE organization_id = '{organization_id}';
    DELETE FROM documents.ingestion_jobs WHERE organization_id = '{organization_id}';
    DELETE FROM documents.document_versions WHERE organization_id = '{organization_id}';
    DELETE FROM documents.document_records WHERE organization_id = '{organization_id}';
    DELETE FROM core.organizations WHERE id = '{organization_id}';
    COMMIT;
    """
    sql(" ".join(statement.split()), env=env)


def write_evidence(payload: dict[str, Any]) -> None:
    EVIDENCE_PATH.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(f"Evidence: {EVIDENCE_PATH}")


def main() -> int:
    env = environment()
    token = uuid4().hex
    unique_text = f"optional ingestion lexical evidence {token}"
    organization_id: str | None = None
    evidence: dict[str, Any] = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "status": "running",
        "api_url": API_BASE_URL,
        "ai_required": False,
        "embeddings_enabled": False,
        "vector_retrieval_enabled": False,
        "object_storage_enabled": False,
        "execution_mode": "registration_and_controlled_persistence",
        "steps": [],
    }

    try:
        run([sys.executable, str(SUPERVISOR), "compose-down"], env=env)
        run([sys.executable, str(SUPERVISOR), "compose-up", "--build", "--keep-failed"], env=env)
        wait_ready()
        evidence["steps"].append("platform_started")

        status, organization = request_json(
            "POST",
            "/api/core/organizations",
            {
                "slug": f"ingestion-e2e-{token}",
                "name": "Optional Ingestion E2E",
                "description": "Generic temporary organization for ingestion validation.",
                "status": "active",
                "config": {"e2e": True},
            },
        )
        if status != 201:
            raise RuntimeError(f"unexpected organization status: {status}")
        organization_id = str(organization["id"])
        evidence["organization_id"] = organization_id
        evidence["steps"].append("organization_created")

        source_bytes = unique_text.encode("utf-8")
        checksum = hashlib.sha256(source_bytes).hexdigest()
        status, registration = request_json(
            "POST",
            "/api/ingestion/register",
            {
                "organization_id": organization_id,
                "title": "Optional ingestion E2E source",
                "source_type": "inline_test_source",
                "source_ref": {"test_reference": token},
                "external_reference": f"e2e:{token}",
                "description": "Registration-only ingestion source used for platform validation.",
                "metadata": {"e2e": True, "token": token},
                "classification": {},
                "requested_by": "optional-ingestion-e2e",
                "version_label": "1",
                "file_name": "e2e.txt",
                "content_type": "text/plain",
                "size_bytes": len(source_bytes),
                "checksum_sha256": checksum,
                "pipeline_name": "registration_e2e",
                "pipeline_version": "1",
                "priority": 10,
                "max_attempts": 2,
            },
        )
        if status != 201 or registration["job_status"] != "pending":
            raise RuntimeError(f"unexpected ingestion registration: {registration}")
        document_id = str(registration["document_record_id"])
        version_id = str(registration["document_version_id"])
        job_id = str(registration["ingestion_job_id"])
        evidence.update({"document_id": document_id, "document_version_id": version_id, "ingestion_job_id": job_id})
        evidence["steps"].append("ingestion_registered")

        status, claimed = request_json(
            "POST",
            "/api/ingestion/jobs/claim",
            {"worker_id": "optional-ingestion-e2e", "organization_id": organization_id, "job_type": "ingestion"},
        )
        if status != 200 or str(claimed["id"]) != job_id or claimed["status"] != "claimed":
            raise RuntimeError(f"unexpected claim result: {claimed}")
        evidence["steps"].append("job_claimed")

        for target in ("running", "succeeded"):
            status, transitioned = request_json(
                "POST",
                f"/api/ingestion/jobs/{job_id}/transition",
                {
                    "status": target,
                    "worker_id": "optional-ingestion-e2e",
                    "metrics": {"e2e": True, "target": target},
                },
            )
            if status != 200 or transitioned["status"] != target:
                raise RuntimeError(f"unexpected transition to {target}: {transitioned}")
        evidence["steps"].append("job_succeeded")

        status, persisted = request_json(
            "POST",
            "/api/documents/chunks/persist",
            {
                "organization_id": organization_id,
                "document_version_id": version_id,
                "chunks": [
                    {
                        "chunk_index": 0,
                        "text": unique_text,
                        "content_type": "text/plain",
                        "provenance": {"adapter": "controlled_e2e"},
                        "quality": {"accepted": True},
                        "metadata": {"e2e": True},
                        "status": "created",
                    }
                ],
            },
        )
        if status != 201 or persisted["chunk_count"] != 1:
            raise RuntimeError(f"unexpected chunk persistence result: {persisted}")
        chunk_id = str(persisted["chunks"][0]["id"])
        evidence["chunk_id"] = chunk_id
        evidence["steps"].append("chunk_persisted")

        status, index_job = request_json(
            "POST",
            "/api/indexing/jobs",
            {
                "organization_id": organization_id,
                "document_record_id": document_id,
                "document_version_id": version_id,
                "ingestion_job_id": job_id,
                "index_target": "postgres_fts",
                "metrics": {"e2e": True},
            },
        )
        if status != 201:
            raise RuntimeError(f"unexpected indexing job result: {index_job}")
        indexing_job_id = str(index_job["id"])
        evidence["indexing_job_id"] = indexing_job_id

        status, indexed = request_json("POST", f"/api/indexing/jobs/{indexing_job_id}/run", {"force": False, "metrics": {"e2e": True}})
        if status != 200 or indexed["status"] != "succeeded" or indexed["indexed_chunk_count"] != 1:
            raise RuntimeError(f"unexpected indexing execution: {indexed}")
        if indexed["metrics"].get("embedding_generated") is not False or indexed["metrics"].get("llm_used") is not False:
            raise RuntimeError("indexing unexpectedly used AI capabilities")
        evidence["steps"].append("postgres_fts_indexed")

        status, search = request_json(
            "POST",
            "/api/knowledge/search",
            {
                "organization_id": organization_id,
                "query_text": token,
                "top_k": 5,
                "candidate_k": 10,
                "retrieval_mode": "lexical_only",
                "embedding_enabled": False,
            },
        )
        if status != 200 or not search["candidates"]:
            raise RuntimeError(f"lexical retrieval returned no candidates: {search}")
        if not any(str(item["chunk_id"]) == chunk_id for item in search["candidates"]):
            raise RuntimeError("persisted chunk was not returned by lexical retrieval")
        metrics = search.get("metrics", {})
        if metrics.get("vector_retrieval_enabled") is not False or metrics.get("embedding_execution_enabled") is not False:
            raise RuntimeError("retrieval unexpectedly enabled vector or embedding execution")
        evidence["retrieval_candidate_count"] = len(search["candidates"])
        evidence["steps"].append("lexical_retrieval_verified")

        counts = sql(
            "SELECT "
            f"(SELECT count(*) FROM documents.document_records WHERE id = '{document_id}'),"
            f"(SELECT count(*) FROM documents.document_versions WHERE id = '{version_id}'),"
            f"(SELECT count(*) FROM documents.ingestion_jobs WHERE id = '{job_id}'),"
            f"(SELECT count(*) FROM documents.chunks WHERE id = '{chunk_id}'),"
            f"(SELECT count(*) FROM documents.indexing_jobs WHERE id = '{indexing_job_id}');",
            env=env,
        )
        if counts.splitlines()[-1].strip() != "1|1|1|1|1":
            raise RuntimeError(f"unexpected persistence counts: {counts!r}")
        evidence["postgresql_counts"] = counts.splitlines()[-1].strip()
        evidence["steps"].append("postgresql_state_verified")

        evidence["status"] = "passed"
        evidence["completed_at"] = datetime.now(timezone.utc).isoformat()
        return 0
    except Exception as exc:
        evidence["status"] = "failed"
        evidence["error"] = str(exc)
        evidence["completed_at"] = datetime.now(timezone.utc).isoformat()
        print(f"OPTIONAL INGESTION E2E FAILED: {exc}", file=sys.stderr)
        return 1
    finally:
        if organization_id is not None:
            try:
                cleanup(organization_id, env=env)
                evidence["steps"].append("temporary_data_cleaned")
            except Exception as cleanup_error:
                evidence["cleanup_error"] = str(cleanup_error)
        try:
            run([sys.executable, str(SUPERVISOR), "compose-down"], env=env)
            evidence["steps"].append("clean_shutdown")
        except Exception as shutdown_error:
            evidence["shutdown_error"] = str(shutdown_error)
        write_evidence(evidence)


if __name__ == "__main__":
    raise SystemExit(main())
