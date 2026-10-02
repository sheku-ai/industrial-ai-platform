#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from alembic.config import Config
from alembic.script import ScriptDirectory


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-base-url", default="http://127.0.0.1:8000/api")
    parser.add_argument("--backup-evidence-id", required=True, type=uuid.UUID)
    parser.add_argument("--execution-key", required=True)
    parser.add_argument("--timeout", type=float, default=30)
    arguments = parser.parse_args()
    api_base_url = arguments.api_base_url.rstrip("/")
    root = Path(__file__).resolve().parents[3]
    manifest = json.loads((root / "release/manifest.json").read_text(encoding="utf-8"))
    edition = os.getenv("PLATFORM_EDITION", "community").strip().lower()
    if edition not in {"community", "enterprise"}:
        parser.error("PLATFORM_EDITION must be community or enterprise")
    manifest["edition_manifest"] = json.loads(
        (root / f"release/editions/{edition}.json").read_text(encoding="utf-8")
    )
    alembic_config = Config(str(root / "apps/api/alembic.ini"))
    manifest["repository_heads"] = ScriptDirectory.from_config(alembic_config).get_heads()
    execution_identity = f"rc-refresh:{edition}:{manifest['version']}:{arguments.execution_key}"
    correlation_id = execution_identity
    headers = {
        "Content-Type": "application/json",
        "X-Authorization-Scope": "platform",
        "X-Principal-Type": "reference_principal",
        "X-Actor-Reference": "reference-platform-operator",
        "X-Correlation-ID": correlation_id,
    }
    errors: list[dict[str, Any]] = []

    def request(method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        body = json.dumps(payload).encode() if payload is not None else None
        operation = urllib.request.Request(
            f"{api_base_url}{path}", data=body, headers=headers, method=method
        )
        try:
            with urllib.request.urlopen(operation, timeout=arguments.timeout) as response:
                return json.loads(response.read().decode())
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode()
            errors.append({"step": path, "status": exc.code, "detail": detail})
            return {}

    backup = request(
        "GET",
        f"/platform/recovery/backups/{arguments.backup_evidence_id}/operational-evidence",
    )
    preflight_request = {
        "scope": "platform",
        "release_version": manifest["version"],
        "alembic_revision": manifest["alembic_head"],
        "edition": edition,
        "execution_key": f"configuration-preflight:{edition}:{manifest['version']}:{arguments.execution_key}:preflight",
    }
    preflight = request("POST", "/platform/configuration/preflight/refresh", preflight_request)

    observability_readiness = request("GET", "/platform/observability/readiness")
    profile_id = (observability_readiness.get("active_profile") or {}).get("id")
    observability = {}
    if profile_id:
        observability = request(
            "POST",
            "/platform/observability/evaluations",
            {
                "scope": "platform",
                "profile_id": profile_id,
                "idempotency_key": f"{execution_identity}:observability",
                "requested_by": "reference-platform-operator",
            },
        )
    else:
        errors.append({"step": "observability", "detail": "active_observability_profile_not_found"})

    lpa_process = subprocess.run(
        [
            str(root / "apps/api/.venv/bin/python"),
            str(root / "apps/api/scripts/run_local_product_acceptance.py"),
            "--api-base-url",
            api_base_url,
            "--timeout",
            str(arguments.timeout),
        ],
        cwd=root / "apps/api",
        capture_output=True,
        text=True,
        check=False,
    )
    if lpa_process.returncode != 0:
        errors.append({"step": "local_product_acceptance", "detail": lpa_process.stderr[-2000:]})

    production_acceptance = request(
        "POST",
        "/platform/production-acceptance/runs",
        {
            "scope": "platform",
            "idempotency_key": f"{execution_identity}:production-acceptance",
            "requested_by": "reference-platform-operator",
        },
    )
    production_readiness = request("GET", "/platform/production-readiness/runtime")
    eligibility_payload = {
        **preflight_request,
        "backup_evidence_id": str(arguments.backup_evidence_id),
        "manifest": manifest,
    }
    upgrade = request(
        "POST",
        "/platform/release-operational-evidence/upgrade-readiness",
        {
            **eligibility_payload,
            "execution_key": f"upgrade:{edition}:{manifest['version']}:{arguments.execution_key}:upgrade",
        },
    )
    rollback = request(
        "POST",
        "/platform/release-operational-evidence/rollback-eligibility",
        {
            **eligibility_payload,
            "execution_key": f"rollback:{edition}:{manifest['version']}:{arguments.execution_key}:rollback",
        },
    )
    production_ready = bool(
        production_readiness.get("overall_production_readiness", {}).get("production_candidate")
    )
    output = {
        "release_version": manifest["version"],
        "alembic_head": manifest["alembic_head"],
        "backup_evidence_status": backup.get("status", "not_evaluated"),
        "configuration_preflight_status": preflight.get("status", "not_evaluated"),
        "observability_status": observability.get("acceptance_status", "not_evaluated"),
        "production_acceptance_status": production_acceptance.get("status", "not_evaluated"),
        "upgrade_readiness": upgrade.get("status", "not_evaluated"),
        "rollback_eligibility": rollback.get("status", "not_evaluated"),
        "production_ready": production_ready,
        "deployment_performed": False,
        "rollback_performed": False,
        "llm_used": False,
        "embeddings_used": False,
        "vector_database_used": False,
        "errors": errors,
    }
    source_evidence_ids = [
        str(value)
        for value in (
            backup.get("evidence_id"),
            preflight.get("id"),
            observability.get("id"),
            production_acceptance.get("run_id"),
            upgrade.get("id"),
            rollback.get("id"),
        )
        if value
    ]
    refresh_summary = request(
        "POST",
        "/platform/release-operational-evidence/refresh-summary",
        {
            "scope": "platform",
            "release_version": manifest["version"],
            "alembic_revision": manifest["alembic_head"],
            "edition": edition,
            "execution_key": execution_identity,
            "backup_evidence_id": str(arguments.backup_evidence_id),
            "summary": output,
            "source_evidence_ids": source_evidence_ids,
        },
    )
    passed = (
        not errors
        and output["backup_evidence_status"] == "passed"
        and output["configuration_preflight_status"] == "passed"
        and output["observability_status"] == "passed"
        and output["production_acceptance_status"] == "passed"
        and output["upgrade_readiness"] == "passed"
        and output["rollback_eligibility"] in {"passed", "requires_restore"}
        and production_ready
        and refresh_summary.get("status") == "passed"
    )
    print(json.dumps({**output, "passed": passed}, indent=2, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
